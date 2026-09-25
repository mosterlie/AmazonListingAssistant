"""
店小秘订单剩余发货时间采集与预警服务 (DxmOrderService)

流程 (每批次):
  1. 复用 9222 CDP Chrome 独立 tab 打开订单页 (未启动则按 erp_bridge 同款逻辑自动拉起专属 Chrome)
  2. 登录态检测: 未登录 → 用配置账密模拟登录 (图形验证码 ddddocr 本地识别, 最多3次/每次换新图)
  3. 在已登录页面上下文调用内部接口 /api/package/list.json 拉全量订单 (自动翻页)
  4. 幂等入库 dxm_order_deadlines (UPSERT by order_no; 已发货/消失订单保留快照)
  5. 预警: 未发货且剩余 < warn_hours → 黄; < danger_hours → 红; <= 0 → 超时
     红色/超时订单出现即单独发预警邮件 (SMTP 复用货代配置);
     每日 8:15 汇总邮件 (含橘色+红色明细) 由 daily_digest_service 独立发送, 与本服务解耦
调度: 每自然小时一次 (整点后首个心跳触发, 保证每天 8 点有「8点批次」供汇总邮件取数)
互斥: product_items 中存在 status='publishing' 的商品 (上件任务运行中) 时跳过本轮采集。
"""
import json
import smtplib
import threading
import time
import traceback
from datetime import datetime
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any, Dict, List, Optional, Tuple

from server.database import get_db_connection, get_setting, set_setting
from server.services.forwarder_doc_service import ForwarderDocService

try:
    from browser_engine import BrowserEngine
except ImportError:  # 直接以脚本方式运行时兜底
    import os
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from browser_engine import BrowserEngine

ORDER_URL = "https://www.dianxiaomi.com/web/order/all?go=m1-1&timeOut=1&index=1"

# /api/package/list.json 请求模板 (实测抓包: orderField=order_timeout_time, timeOut=1=临期筛选, 0=全量)
_LIST_POST_TPL = ("pageNo={page}&pageSize=100&shopId=-1&state=&platform=&isSearch=0&searchType=orderId"
                  "&authId=-1&startTime=&endTime=&country=&orderField=order_timeout_time&isVoided=-1"
                  "&isRemoved=-1&ruleId=-1&sysRule=&applyType=&applyStatus=&printJh=-1&printMd=-1"
                  "&commitPlatform=&productStatus=&jhComment=-1&storageId=0&isOversea=-1&isFree=-1"
                  "&isBatch=-1&history=&custom=-1&timeOut={timeout}&refundStatus=0&buyerAccount="
                  "&forbiddenStatus=-1&forbiddenReason=0&behindTrack=-1&orderId=&axios_cancelToken=true")

# 页面上下文内 fetch 内部接口 (携带登录 cookie)
_FETCH_JS = """(async (postData) => {
    const resp = await fetch('/api/package/list.json', {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                  'X-Requested-With': 'XMLHttpRequest'},
        body: postData, credentials: 'include'
    });
    return await resp.json();
})"""

_DEFAULT_CONFIG = {
    "dxm_account": "",
    "dxm_password": "",
    "scan_enabled": True,
    "warn_hours": 24,
    "danger_hours": 6,
    "repeat_red_alert": True,
    "alert_email_enabled": False,
    "alert_mail_to": "",
    "subject_prefix": "[店小秘发货预警]",
}

_RUN_LOCK = threading.Lock()
_RUNNING = {"running": False, "trigger": None, "started_at": None}
_OCR = None  # ddddocr 惰性单例 (仅模拟登录时加载)


def _get_ocr():
    """ddddocr 本地 OCR 单例 (首次调用加载 onnx 模型, 约2秒)"""
    global _OCR
    if _OCR is None:
        try:
            import ddddocr
        except ImportError:
            raise RuntimeError("ddddocr 未安装, 无法识别验证码 (pip install ddddocr)")
        _OCR = ddddocr.DdddOcr(show_ad=False)
    return _OCR


class DxmOrderService:

    # ───────────────── 配置 ─────────────────
    @staticmethod
    def get_config(override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        cfg = dict(_DEFAULT_CONFIG)
        for key in _DEFAULT_CONFIG:
            val = get_setting(f"dxm_order_{key}")
            if val is not None:
                cfg[key] = val
        if override:
            cfg.update({k: v for k, v in override.items() if k in _DEFAULT_CONFIG})
        try:
            cfg["warn_hours"] = max(0.5, float(cfg["warn_hours"] or 24))
        except Exception:
            cfg["warn_hours"] = 24
        try:
            cfg["danger_hours"] = max(0, float(cfg["danger_hours"] or 6))
        except Exception:
            cfg["danger_hours"] = 6
        cfg["scan_enabled"] = bool(cfg["scan_enabled"])
        cfg["repeat_red_alert"] = bool(cfg["repeat_red_alert"])
        cfg["alert_email_enabled"] = bool(cfg["alert_email_enabled"])
        if isinstance(cfg["alert_mail_to"], list):
            cfg["alert_mail_to"] = ", ".join(str(x).strip() for x in cfg["alert_mail_to"] if str(x).strip())
        return cfg

    @staticmethod
    def save_config(patch: Dict[str, Any]) -> Dict[str, Any]:
        current = dict(DxmOrderService.get_config())
        for k, v in (patch or {}).items():
            if k in _DEFAULT_CONFIG:
                current[k] = v
        for key, val in current.items():
            set_setting(f"dxm_order_{key}", val)
        return DxmOrderService.get_config()

    # ───────────────── 浏览器通道 ─────────────────
    _ENGINE = None                # BrowserEngine 单例 (每个实例自带 Playwright 常驻线程, 必须复用避免泄漏)
    _ENGINE_LOCK = threading.Lock()

    @staticmethod
    def _ensure_browser() -> "BrowserEngine":
        """复用/拉起 9222 Chrome 并打开订单页独立 tab (照 erp_bridge 模式; 引擎单例复用)"""
        try:
            from core.browser_manager import cleanup_stale_drivers
            cleanup_stale_drivers()
        except Exception:
            pass
        with DxmOrderService._ENGINE_LOCK:
            engine = DxmOrderService._ENGINE
            if engine is None:
                chrome_user_dir = None
                try:
                    import sys
                    import os
                    _key = "chrome_user_data_dir_mac" if sys.platform == "darwin" else "chrome_user_data_dir_win"
                    _default = "~/ChromeDebugUser" if sys.platform == "darwin" else "C:\\ChromeDebugUser"
                    _dir = (get_setting(_key, "") or "").strip() or _default
                    chrome_user_dir = os.path.expanduser(_dir)
                except Exception:
                    pass
                engine = (BrowserEngine(port=9222, user_data_dir=chrome_user_dir)
                          if chrome_user_dir else BrowserEngine(port=9222))
                DxmOrderService._ENGINE = engine
        if not engine.is_running():
            ok, msg = engine.launch_browser(ORDER_URL)
            if not ok:
                raise RuntimeError(f"自动启动 Chrome 失败: {msg}")
        else:
            ok, msg = engine.connect(activate=False)
            if not ok:
                try:
                    engine.close()
                except Exception:
                    pass
                ok, msg = engine.launch_browser(ORDER_URL)
                if not ok:
                    raise RuntimeError(f"重新拉起 Chrome 失败: {msg}")
        engine.open_or_focus_url(ORDER_URL)
        time.sleep(2)
        return engine

    @staticmethod
    def _run_on_active_page(engine: "BrowserEngine", fn):
        """在浏览器专属线程内对前台活动页面执行 fn(page) (杜绝 greenlet 跨线程异常)"""
        def job():
            page = engine.manager._get_active_page_impl()
            if page is None:
                raise RuntimeError("未能找到浏览器活动页面")
            return fn(page)
        return engine.manager.run_on_browser_thread(job)

    # ───────────────── 登录态与模拟登录 ─────────────────
    @staticmethod
    def _is_logged_in(page) -> bool:
        """以内部接口能否返回 code=0 判定登录态 (最权威)"""
        try:
            r = page.evaluate(_FETCH_JS, _LIST_POST_TPL.format(page=1, timeout=0))
            return isinstance(r, dict) and r.get("code") == 0
        except Exception:
            return False

    @staticmethod
    def _simulate_login(page, cfg: Dict[str, Any]) -> Tuple[bool, str]:
        """模拟登录: 账密 + 图形验证码 ddddocr 本地识别 (最多3次, 每次换新图)"""
        account = (cfg.get("dxm_account") or "").strip()
        password = (cfg.get("dxm_password") or "").strip()
        if not account or not password:
            return False, "未配置店小秘账号/密码 (系统管理 → 店小秘订单预警)"
        try:
            ocr = _get_ocr()
        except RuntimeError as e:
            return False, str(e)
        for attempt in range(1, 4):
            try:
                page.wait_for_selector("img#verifyImgCode", timeout=10000)
                img = page.query_selector("img#verifyImgCode")
                if img is None:
                    return False, "登录页未找到验证码图片"
                png = img.screenshot()
                code_text = "".join(ch for ch in str(ocr.classification(png)) if ch.isalnum())[:4]
                page.fill("input#exampleInputName", account)
                page.fill("input#exampleInputPassword", password)
                page.fill("input#verifyCode", code_text)
                page.click("button#loginBtn")
                time.sleep(7)
                if DxmOrderService._is_logged_in(page):
                    return True, f"第{attempt}次尝试成功 (验证码识别: {code_text})"
                # 失败 → 刷新验证码换新图重试
                try:
                    page.evaluate("() => typeof updateVerifyCode === 'function' && updateVerifyCode('#verifyImgCode')")
                except Exception:
                    try:
                        page.click("span.checkcode_img a")
                    except Exception:
                        pass
                time.sleep(2)
            except Exception as e:
                return False, f"模拟登录异常: {e.__class__.__name__}: {str(e)[:150]}"
        return False, "验证码识别3次均失败, 本轮跳过 (需人工登录一次)"

    # ───────────────── 采集 ─────────────────
    @staticmethod
    def _fetch_all_orders(page) -> List[Dict[str, Any]]:
        """翻页拉全量订单 (每页100, 以 totalPage 为准, 上限50页)"""
        all_orders: List[Dict[str, Any]] = []
        page_no = 1
        while page_no <= 50:
            r = page.evaluate(_FETCH_JS, _LIST_POST_TPL.format(page=page_no, timeout=0))
            if not isinstance(r, dict) or r.get("code") != 0:
                raise RuntimeError(f"订单接口返回异常: {json.dumps(r, ensure_ascii=False)[:150] if r else '空响应'}")
            pg = (r.get("data") or {}).get("page") or {}
            lst = pg.get("list") or []
            all_orders.extend(lst)
            try:
                total_page = int(pg.get("totalPage") or 1)
            except Exception:
                total_page = 1
            if page_no >= total_page or not lst:
                break
            page_no += 1
            time.sleep(0.6)
        return all_orders

    @staticmethod
    def _collect(cfg: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str]:
        """打开订单页 → 登录态检测/模拟登录 → 拉全量订单"""
        engine = DxmOrderService._ensure_browser()

        def impl(page) -> Tuple[List[Dict[str, Any]], str]:
            if "web/order" not in page.url:
                page.goto(ORDER_URL, wait_until="domcontentloaded", timeout=40000)
                time.sleep(5)
            if not DxmOrderService._is_logged_in(page):
                ok, msg = DxmOrderService._simulate_login(page, cfg)
                if not ok:
                    return [], f"failed: {msg}"
                page.goto(ORDER_URL, wait_until="domcontentloaded", timeout=40000)
                time.sleep(5)
            orders = DxmOrderService._fetch_all_orders(page)
            return orders, "ok"

        return DxmOrderService._run_on_active_page(engine, impl)

    # ───────────────── 入库与预警 ─────────────────
    @staticmethod
    def _store_and_alert(orders: List[Dict[str, Any]], cfg: Dict[str, Any]) -> Dict[str, Any]:
        """UPSERT 快照 + 预警分级 + 邮件; 返回统计"""
        now_ts = time.time()
        warn_sec = cfg["warn_hours"] * 3600
        danger_sec = cfg["danger_hours"] * 3600
        stats = {"orders_total": 0, "pending_total": 0, "alert_yellow": 0,
                 "alert_red": 0, "alert_expired": 0, "orders_cancelled": 0, "email_rows": []}
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # Python 本地时间 (SQLite CURRENT_TIMESTAMP 是 UTC)
        conn = get_db_connection()
        try:
            for od in orders:
                order_no = str(od.get("orderId") or "").strip()
                if not order_no or od.get("isVoided") or od.get("isRemoved"):
                    continue
                stats["orders_total"] += 1
                state_l = (od.get("orderState") or "").strip().lower()
                platform_state = (od.get("orderStatePlatform") or "").strip()
                platform_l = platform_state.lower()
                # 已取消订单 (CANCELED/Cancelled/已取消): 不轮询预警, 库内标记 alert_level=-1 退出预警列表
                is_cancelled = ("cancel" in state_l or "cancel" in platform_l or "取消" in platform_state)
                status = platform_state or (od.get("orderState") or "").strip()
                is_shipped = (od.get("orderState") == "shipped" or status.lower() == "shipped")
                try:
                    timeout_ts = int(od.get("orderTimeoutTime") or 0)
                except (TypeError, ValueError):
                    timeout_ts = 0
                deadline_at = datetime.fromtimestamp(timeout_ts).strftime("%Y-%m-%d %H:%M:%S") if timeout_ts else ""
                remaining_min = int((timeout_ts - now_ts) // 60) if timeout_ts else -1
                if is_cancelled:
                    alert_level = -1
                    stats["orders_cancelled"] += 1
                elif is_shipped:
                    alert_level = 0
                else:
                    stats["pending_total"] += 1
                    if remaining_min <= 0:
                        alert_level = 2          # 超时 (页面置灰红字)
                        stats["alert_expired"] += 1
                    elif remaining_min * 60 < danger_sec:
                        alert_level = 2
                        stats["alert_red"] += 1
                    elif remaining_min * 60 < warn_sec:
                        alert_level = 1
                        stats["alert_yellow"] += 1
                    else:
                        alert_level = 0

                row = conn.execute(
                    "SELECT alerted_levels FROM dxm_order_deadlines WHERE order_no = ?", (order_no,)).fetchone()
                old_alerted = (row["alerted_levels"] or "") if row else ""
                # 邮件范围: 仅红/超时级 (首次触达或每轮重复提醒); 黄级只入库记录不发邮件
                if alert_level == 2:
                    red_repeat = cfg["repeat_red_alert"] or "2" not in old_alerted
                    if red_repeat:
                        stats["email_rows"].append({
                            "order_no": order_no, "shop_name": od.get("shopPlatform") or od.get("shopName") or "",
                            "site": od.get("buyerCountry") or "", "order_status": status,
                            "deadline_at": deadline_at, "remaining_minutes": remaining_min, "level": alert_level})
                conn.execute(
                    """INSERT INTO dxm_order_deadlines
                       (order_no, shop_name, site, order_status, deadline_at, remaining_minutes, alert_level, first_seen_at)
                       VALUES (?,?,?,?,?,?,?,?)
                       ON CONFLICT(order_no) DO UPDATE SET
                         shop_name = excluded.shop_name, site = excluded.site,
                         order_status = excluded.order_status, deadline_at = excluded.deadline_at,
                         remaining_minutes = excluded.remaining_minutes, alert_level = excluded.alert_level,
                         last_seen_at = ?, updated_at = ?""",
                    (order_no, od.get("shopPlatform") or od.get("shopName") or "", od.get("buyerCountry") or "",
                     status, deadline_at, remaining_min, alert_level, now_str, now_str, now_str))
                # 预警级别首次触达即登记 (避免后续重复轰炸; 邮件关闭时同样登记, 防止开启后旧单轰炸)
                marks = set(x for x in old_alerted.split(",") if x)
                if alert_level >= 1:
                    marks.add("1")
                if alert_level == 2:
                    marks.add("2")
                new_alerted = ",".join(sorted(marks))
                if new_alerted != old_alerted:
                    conn.execute("UPDATE dxm_order_deadlines SET alerted_levels = ? WHERE order_no = ?",
                                 (new_alerted, order_no))
            conn.commit()
        finally:
            conn.close()

        # 邮件: 仅红/超时级 (email_rows 已只含 level==2; 黄级静默记录)
        stats["email_status"] = "disabled"
        if cfg["alert_email_enabled"] and stats["email_rows"]:
            stats["email_status"] = DxmOrderService._send_alert_email(cfg, stats["email_rows"])
        return stats

    # ───────────────── 每日邮件快照 ─────────────────
    @staticmethod
    def timeout_orders_snapshot() -> List[Dict[str, Any]]:
        """库内最近一次采集快照中的 红/超时 未发货订单 (供状态页/汇总邮件查询)"""
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT order_no, shop_name, site, order_status, deadline_at, remaining_minutes "
                "FROM dxm_order_deadlines WHERE alert_level = 2 ORDER BY remaining_minutes ASC").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ───────────────── 邮件 ─────────────────
    @staticmethod
    def _smtp_config() -> Dict[str, Any]:
        """复用货代采集的 SMTP 通道配置"""
        fwd = ForwarderDocService.get_config()
        return {k: fwd.get(k) for k in ("smtp_host", "smtp_port", "smtp_ssl", "smtp_user",
                                        "smtp_password", "mail_from")}

    @staticmethod
    def _fmt_remaining(minutes: int) -> str:
        if minutes is None or minutes < 0:
            return "未知"
        if minutes <= 0:
            return "已超时"
        d, rem = divmod(minutes, 1440)
        h, m = divmod(rem, 60)
        return (f"{d}天{h}小时" if d else (f"{h}小时{m}分" if h else f"{m}分钟"))

    @staticmethod
    def _send_alert_email(cfg: Dict[str, Any], rows: List[Dict[str, Any]]) -> str:
        try:
            to_list = [x.strip() for x in (cfg.get("alert_mail_to") or "").split(",") if x.strip()]
            if not to_list:
                return "failed: 未配置收件人"
            smtp = DxmOrderService._smtp_config()
            if not smtp.get("smtp_user"):
                return "failed: 未配置 SMTP (系统管理 → 货代文档采集邮件配置)"
            red_n = sum(1 for r in rows if r["level"] == 2)
            subject = (f"{cfg.get('subject_prefix', '')} "
                       f"{red_n} 红/超时 共 {len(rows)} 单 ({datetime.now().strftime('%m-%d %H:%M')})")
            body_rows = ""
            for r in sorted(rows, key=lambda x: x["remaining_minutes"]):
                color = "#dc2626" if r["level"] == 2 else "#d97706"
                body_rows += (
                    f"<tr><td style='border:1px solid #e5e7eb;padding:4px 8px;'>{r['order_no']}</td>"
                    f"<td style='border:1px solid #e5e7eb;padding:4px 8px;'>{r['shop_name'][:40]}</td>"
                    f"<td style='border:1px solid #e5e7eb;padding:4px 8px;'>{r['site']}</td>"
                    f"<td style='border:1px solid #e5e7eb;padding:4px 8px;color:{color};font-weight:700;'>"
                    f"{DxmOrderService._fmt_remaining(r['remaining_minutes'])}</td>"
                    f"<td style='border:1px solid #e5e7eb;padding:4px 8px;'>{r['deadline_at']}</td>"
                    f"<td style='border:1px solid #e5e7eb;padding:4px 8px;'>{r['order_status']}</td></tr>")
            html = (
                "<div style='font-family:Microsoft YaHei,Arial;font-size:13px;'>"
                "<h2 style='color:#dc2626;'>⏰ 店小秘订单发货截止预警</h2>"
                f"<p>🔴 红/超时(剩余&lt;{cfg['danger_hours']}h 或已超时): <b>{red_n}</b> 单 (黄色订单仅页面展示, 不再邮件提醒)</p>"
                "<table style='border-collapse:collapse;font-size:12.5px;'>"
                "<thead><tr>" + "".join(
                    f"<th style='border:1px solid #e5e7eb;background:#f8fafc;padding:5px 8px;text-align:left;'>{c}</th>"
                    for c in ["订单号", "店铺", "站点", "剩余时间", "发货截止", "状态"]) +
                f"</tr></thead><tbody>{body_rows}</tbody></table>"
                "<p style='color:#94a3b8;font-size:11px;margin-top:14px;'>本邮件由 ERP 中间件店小秘订单监控自动发送</p></div>")
            msg = MIMEMultipart("alternative")
            msg["Subject"] = Header(subject, "utf-8")
            msg["From"] = formataddr((Header("ERP店小秘订单监控", "utf-8").encode(),
                                      smtp.get("mail_from") or smtp["smtp_user"]))
            msg["To"] = ", ".join(to_list)
            msg.attach(MIMEText(html, "html", "utf-8"))
            if smtp.get("smtp_ssl"):
                server = smtplib.SMTP_SSL(smtp["smtp_host"], int(smtp["smtp_port"] or 465), timeout=20)
            else:
                server = smtplib.SMTP(smtp["smtp_host"], int(smtp["smtp_port"] or 465), timeout=20)
            try:
                server.login(smtp["smtp_user"], smtp["smtp_password"])
                server.sendmail(smtp.get("mail_from") or smtp["smtp_user"], to_list, msg.as_string())
            finally:
                server.quit()
            return "sent"
        except Exception as e:
            return f"failed: {e.__class__.__name__}: {str(e)[:200]}"

    @staticmethod
    def send_test_email(cfg_override: Optional[Dict[str, Any]] = None) -> str:
        cfg = DxmOrderService.get_config(cfg_override)
        sample = [{"order_no": "TEST-000-0000000", "shop_name": "测试店铺", "site": "JP",
                   "order_status": "Unshipped", "deadline_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   "remaining_minutes": 300, "level": 1}]
        return DxmOrderService._send_alert_email(cfg, sample)

    # ───────────────── 批次执行 ─────────────────
    @staticmethod
    def _has_publishing_task() -> bool:
        """上件任务运行中 (存在 status='publishing' 的商品) → 采集让路"""
        conn = get_db_connection()
        try:
            n = conn.execute("SELECT COUNT(*) c FROM product_items WHERE status = 'publishing'").fetchone()["c"]
        finally:
            conn.close()
        return n > 0

    @staticmethod
    def run_batch(trigger: str = "manual") -> Dict[str, Any]:
        """同步执行一个采集批次 (阻塞); 已有批次运行中则返回 skipped"""
        if not _RUN_LOCK.acquire(blocking=False):
            return {"skipped": True, "msg": "已有采集批次在运行"}
        started = datetime.now()
        conn = get_db_connection()
        try:
            # 用 Python 本地时间写入 (SQLite CURRENT_TIMESTAMP 是 UTC, 与调度判定的本地时钟相差8h会导致重复触发)
            cur = conn.execute(
                "INSERT INTO dxm_order_sync_logs (trigger_type, status, started_at) "
                "VALUES (?, 'running', ?)", (trigger, started.strftime("%Y-%m-%d %H:%M:%S")))
            log_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        _RUNNING.update({"running": True, "trigger": trigger, "started_at": started.isoformat()})

        summary: Dict[str, Any] = {"log_id": log_id, "_started": started}
        try:
            if DxmOrderService._has_publishing_task():
                summary.update({"status": "skipped", "msg": "上件任务运行中, 本轮采集自动跳过"})
                DxmOrderService._finish_log(log_id, "skipped", summary)
                return summary
            cfg = DxmOrderService.get_config()
            orders, login_status = DxmOrderService._collect(cfg)
            summary["login_status"] = login_status
            if login_status.startswith("failed"):
                summary.update({"status": "failed", "msg": login_status})
                DxmOrderService._finish_log(log_id, "failed", summary)
                return summary
            stats = DxmOrderService._store_and_alert(orders, cfg)
            summary.update({"status": "success", **stats})
            DxmOrderService._finish_log(log_id, "success", summary)
        except Exception as e:
            summary["error"] = f"{e.__class__.__name__}: {e}"
            summary["traceback"] = traceback.format_exc()[-1200:]
            DxmOrderService._finish_log(log_id, "failed", summary)
        finally:
            _RUNNING.update({"running": False, "trigger": None, "started_at": None})
            _RUN_LOCK.release()
        return summary

    @staticmethod
    def _finish_log(log_id: int, status: str, summary: Dict[str, Any]) -> None:
        conn = get_db_connection()
        try:
            started = summary.get("_started") or datetime.now()
            conn.execute(
                "UPDATE dxm_order_sync_logs SET status = ?, login_status = ?, orders_total = ?, "
                "alert_yellow = ?, alert_red = ?, alert_expired = ?, email_status = ?, "
                "message = ?, duration_ms = ?, finished_at = ? WHERE id = ?",
                (status, summary.get("login_status", ""), summary.get("orders_total", 0),
                 summary.get("alert_yellow", 0), summary.get("alert_red", 0), summary.get("alert_expired", 0),
                 summary.get("email_status", ""), summary.get("msg", "") or summary.get("error", "")[:500],
                 int((datetime.now() - started).total_seconds() * 1000),
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S"), log_id))
            conn.commit()
        finally:
            conn.close()

    # ───────────────── 调度 ─────────────────
    @staticmethod
    def maybe_trigger_scheduled() -> bool:
        """调度心跳 (每60s调用): 开启采集 + 当前自然小时还没有成功批次 + 空闲 → 后台线程触发。

        按自然小时对齐 (整点后首个心跳触发), 保证每天 8 点时段有「8点批次」供每日汇总邮件取数;
        本小时内批次失败会在下个心跳自动重试, 直至该小时出现成功批次。
        """
        if _RUN_LOCK.locked() or _RUNNING["running"]:
            return False
        cfg = DxmOrderService.get_config()
        if not cfg["scan_enabled"]:
            return False
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT started_at FROM dxm_order_sync_logs WHERE status IN ('success','partial') "
                "ORDER BY id DESC LIMIT 1").fetchone()
        finally:
            conn.close()
        now = datetime.now()
        if row and row["started_at"]:
            try:
                last = datetime.fromisoformat(row["started_at"])
            except Exception:
                last = None
            if last and last.date() == now.date() and last.hour >= now.hour:
                return False   # 本自然小时已采集成功过
        threading.Thread(target=DxmOrderService.run_batch, kwargs={"trigger": "scheduled"},
                         daemon=True).start()
        return True

    @staticmethod
    def is_running() -> bool:
        return bool(_RUNNING["running"])

    # ───────────────── 查询 ─────────────────
    @staticmethod
    def get_status() -> Dict[str, Any]:
        conn = get_db_connection()
        try:
            last = conn.execute(
                "SELECT * FROM dxm_order_sync_logs ORDER BY id DESC LIMIT 1").fetchone()
            cnt = conn.execute(
                """SELECT
                     SUM(CASE WHEN alert_level = 1 AND order_status NOT LIKE 'Shipped%' THEN 1 ELSE 0 END) yellow,
                     SUM(CASE WHEN alert_level = 2 AND remaining_minutes > 0 THEN 1 ELSE 0 END) red,
                     SUM(CASE WHEN alert_level = 2 AND remaining_minutes <= 0 THEN 1 ELSE 0 END) expired,
                     SUM(CASE WHEN alert_level = -1 THEN 1 ELSE 0 END) cancelled,
                     COUNT(*) total
                   FROM dxm_order_deadlines""").fetchone()
        finally:
            conn.close()
        cfg = DxmOrderService.get_config()
        return {
            "running": _RUNNING["running"],
            "running_trigger": _RUNNING["trigger"],
            "last_log": dict(last) if last else None,
            "counts": {"yellow": cnt["yellow"] or 0, "red": cnt["red"] or 0,
                       "expired": cnt["expired"] or 0, "cancelled": cnt["cancelled"] or 0,
                       "total": cnt["total"] or 0},
            "publishing_busy": DxmOrderService._has_publishing_task(),
            "config": {k: ("" if "password" in k else v) for k, v in cfg.items()},
        }

    @staticmethod
    def list_orders(alert_level: Optional[int] = None, pending_only: bool = True,
                    keyword: str = "", page: int = 1, page_size: int = 50) -> Dict[str, Any]:
        """订单预警列表 (剩余时间升序; remaining 实时按 deadline_at 重算)"""
        where, params = ["1=1"], []
        if pending_only:
            where.append("order_status NOT LIKE 'Shipped%' AND order_status != 'shipped'")
            where.append("alert_level != -1")   # 已取消订单不进预警列表
        if alert_level is not None:
            where.append("alert_level = ?")
            params.append(int(alert_level))
        if keyword:
            where.append("(order_no LIKE ? OR shop_name LIKE ? OR site LIKE ?)")
            kw = f"%{keyword.strip()}%"
            params += [kw, kw, kw]
        wsql = " AND ".join(where)
        conn = get_db_connection()
        try:
            total = conn.execute(f"SELECT COUNT(*) c FROM dxm_order_deadlines WHERE {wsql}", params).fetchone()["c"]
            rows = conn.execute(
                f"SELECT * FROM dxm_order_deadlines WHERE {wsql} "
                "ORDER BY CASE WHEN remaining_minutes < 0 THEN 1 ELSE 0 END, remaining_minutes "
                "LIMIT ? OFFSET ?",
                params + [min(200, max(1, page_size)), max(0, (page - 1) * page_size)]).fetchall()
        finally:
            conn.close()
        now_ts = time.time()
        items = []
        for r in rows:
            d = dict(r)
            try:
                dl = datetime.strptime(d["deadline_at"], "%Y-%m-%d %H:%M:%S").timestamp()
                d["remaining_minutes_now"] = int((dl - now_ts) // 60)
            except Exception:
                d["remaining_minutes_now"] = d["remaining_minutes"]
            items.append(d)
        return {"total": total, "page": page, "page_size": page_size, "items": items}

    @staticmethod
    def test_login(cfg_override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """测试登录: 打开订单页 → 已登录直接返回成功, 未登录走模拟登录 (管理员验证配置用)"""
        cfg = DxmOrderService.get_config(cfg_override)
        engine = DxmOrderService._ensure_browser()

        def impl(page) -> Dict[str, Any]:
            if "web/order" not in page.url and "dianxiaomi.com" in page.url:
                page.goto(ORDER_URL, wait_until="domcontentloaded", timeout=40000)
                time.sleep(5)
            if DxmOrderService._is_logged_in(page):
                return {"ok": True, "msg": "当前浏览器已是登录态"}
            ok, msg = DxmOrderService._simulate_login(page, cfg)
            return {"ok": ok, "msg": msg}

        return DxmOrderService._run_on_active_page(engine, impl)
