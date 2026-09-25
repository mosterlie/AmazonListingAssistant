"""
每日汇总邮件服务 (DailyDigestService) — 监控与邮件解耦后的独立邮件任务

调度: 每天 digest_time (默认 08:15) 触发一次 (心跳 60s; 当天已发不再发; email_enabled 总开关)
内容 (两个独立区块, 对应两路监控任务的采集结果):
  A. 货代文档采集: 今日批次结果 (forwarder_doc_sync_logs 今日最新批次, 每日 8 点采集)
     - 今日无成功批次 → 「未采集到」提醒 (含失败原因)
     - 成功 → 采集统计 + 超期未发货告警明细 (forwarder_ship_alerts 今日, 按货代分组)
  B. 店小秘订单预警 (今日 8 点批次): dxm_order_sync_logs 中今日 08:00-08:59 的成功批次
     - 无 8 点成功批次 → 「未采集到」提醒
     - 有 → 库内橘色(黄)+红色/超时未发货订单明细 (dxm_order_deadlines, alert_level>=1)

SMTP/收件人复用货代采集配置 (fwd_doc_* 扁平键); 发送结果记 system_settings.daily_digest_last。
店小秘红色/超时预警的即时单独邮件仍由 DxmOrderService 在每轮采集中触发, 与本任务互不影响。
"""
import json
import smtplib
import threading
from datetime import datetime
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any, Dict, List, Optional

from server.database import get_db_connection, get_setting, set_setting
from server.services.forwarder_doc_service import ForwarderDocService

# 货代告警明细邮件中优先展示的列 (与「发货数据」表头对应, 缺列自动跳过)
_ALERT_DISPLAY_COLUMNS = ["产品名称及备注", "国内包裹数量", "国际单号", "订单号"]

# 「店小秘 8 点批次」判定窗口 (自然小时, 按需求固定为每天 8 点那次)
_DXM_EIGHT_BATCH_START = 8
_DXM_EIGHT_BATCH_END = 9

_SEND_LOCK = threading.Lock()
_SENDING = {"sending": False, "trigger": None}


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


class DailyDigestService:

    # ───────────────── 配置 ─────────────────
    @staticmethod
    def get_config(override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """复用货代采集配置 (fwd_doc_*), 取汇总邮件相关键;
        收件人优先级: override.digest_mail_to (表单测试值) > fwd_doc_digest_mail_to (提醒任务页独立收件人) > 默认收件人"""
        cfg = ForwarderDocService.get_config(override)
        ov = override or {}
        digest_to = str(ov.get("digest_mail_to") or "").strip()
        if not digest_to and "mail_to" not in ov:  # 显式传 mail_to (通道测试) 时跳过独立收件人
            digest_to = str(get_setting("fwd_doc_digest_mail_to", "") or "").strip()
        if digest_to:
            cfg["mail_to"] = [x.strip() for x in digest_to.split(",") if x.strip()]
        return {k: cfg[k] for k in ("email_enabled", "digest_time", "smtp_host", "smtp_port",
                                    "smtp_ssl", "smtp_user", "smtp_password", "mail_from",
                                    "mail_to", "subject_prefix", "alert_days")}

    @staticmethod
    def next_run_time() -> str:
        """下次发送时间描述 (供提醒任务页展示; 已发过当天则显示明日)"""
        cfg = DailyDigestService.get_config()
        if not cfg.get("email_enabled"):
            return "未开启"
        try:
            hh, mm = (cfg.get("digest_time") or "08:15").split(":")[:2]
        except Exception:
            hh, mm = "8", "15"
        now = datetime.now()
        sent = get_setting("daily_digest_last", None)
        today_sent = isinstance(sent, dict) and sent.get("date") == _today()
        from datetime import timedelta
        target = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        if today_sent or target <= now:
            target += timedelta(days=1)
        return target.strftime("%Y-%m-%d %H:%M")

    # ───────────────── 调度 ─────────────────
    @staticmethod
    def maybe_trigger_scheduled() -> bool:
        """调度心跳 (每 60s 调用): 开关开启 + 今天未发过 + 到达 digest_time → 后台线程发送"""
        if _SEND_LOCK.locked() or _SENDING["sending"]:
            return False
        cfg = DailyDigestService.get_config()
        if not cfg["email_enabled"]:
            return False
        now = datetime.now()
        try:
            hh, mm = (cfg.get("digest_time") or "08:15").split(":")[:2]
            due = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        except Exception:
            due = now.replace(hour=8, minute=15, second=0, microsecond=0)
        if now < due:
            return False
        last = get_setting("daily_digest_last", None)
        if isinstance(last, dict) and last.get("date") == _today():
            return False
        threading.Thread(target=DailyDigestService.send_digest,
                         kwargs={"trigger": "scheduled"}, daemon=True).start()
        return True

    @staticmethod
    def is_sending() -> bool:
        return bool(_SENDING["sending"])

    # ───────────────── 发送 ─────────────────
    @staticmethod
    def send_digest(trigger: str = "scheduled") -> str:
        """组装并发送今日汇总邮件 (阻塞); 结果记入 daily_digest_last"""
        if not _SEND_LOCK.acquire(blocking=False):
            return "skipped: 已有发送任务在执行"
        _SENDING.update({"sending": True, "trigger": trigger})
        try:
            cfg = DailyDigestService.get_config()
            if not cfg.get("mail_to"):
                status = "failed: 未配置收件人"
            else:
                status = DailyDigestService._send_email(cfg)
            set_setting("daily_digest_last", {
                "date": _today(), "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "trigger": trigger, "status": status})
            return status
        finally:
            _SENDING.update({"sending": False, "trigger": None})
            _SEND_LOCK.release()

    @staticmethod
    def _send_email(cfg: Dict[str, Any]) -> str:
        try:
            biz_date = _today()
            fwd_html, fwd_meta = DailyDigestService.forwarder_section(biz_date)
            dxm_html, dxm_meta = DailyDigestService.dxm_section(biz_date)
            subject = (f"{cfg.get('subject_prefix', '')} {biz_date} 每日汇总 "
                       f"(货代告警 {fwd_meta['alerts']} 行 · 店小橘/红 {dxm_meta['alert_rows']} 单)")
            html = DailyDigestService._build_digest_html(biz_date, fwd_html, dxm_html)
            msg = MIMEMultipart("alternative")
            msg["Subject"] = Header(subject, "utf-8")
            msg["From"] = formataddr((Header("ERP每日汇总", "utf-8").encode(),
                                      cfg.get("mail_from") or cfg["smtp_user"]))
            msg["To"] = ", ".join(cfg["mail_to"])
            msg.attach(MIMEText(html, "html", "utf-8"))
            if cfg["smtp_ssl"]:
                server = smtplib.SMTP_SSL(cfg["smtp_host"], int(cfg["smtp_port"] or 465), timeout=20)
            else:
                server = smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"] or 465), timeout=20)
            try:
                server.login(cfg["smtp_user"], cfg["smtp_password"])
                server.sendmail(cfg.get("mail_from") or cfg["smtp_user"],
                                cfg["mail_to"], msg.as_string())
            finally:
                server.quit()
            return "sent"
        except Exception as e:
            return f"failed: {e.__class__.__name__}: {str(e)[:200]}"

    @staticmethod
    def send_test_email(cfg_override: Optional[Dict[str, Any]] = None) -> str:
        """发送测试汇总邮件 (表单当前值不落库, 忽略开关直接发送, 内容取当前库内真实数据)"""
        cfg = DailyDigestService.get_config(cfg_override)
        if not cfg.get("mail_to"):
            return "failed: 未配置收件人"
        return DailyDigestService._send_email(cfg)

    # ───────────────── 区块A: 货代文档采集 ─────────────────
    @staticmethod
    def forwarder_section(biz_date: str) -> tuple:
        """今日货代采集区块; 返回 (html, {ok, alerts, docs_total, docs_ok, docs_failed})"""
        meta = {"ok": False, "alerts": 0, "docs_total": 0, "docs_ok": 0, "docs_failed": 0}
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT * FROM forwarder_doc_sync_logs WHERE biz_date = ? "
                "ORDER BY id DESC LIMIT 1", (biz_date,)).fetchone()
            alerts: List[Dict[str, Any]] = []
            if row and row["status"] in ("success", "partial"):
                alerts = [dict(r) for r in conn.execute(
                    "SELECT * FROM forwarder_ship_alerts WHERE biz_date = ? "
                    "ORDER BY days_elapsed DESC", (biz_date,)).fetchall()]
        finally:
            conn.close()
        if not row:
            html = (f"<h3 style='margin:0 0 6px;'>🚢 货代文档采集</h3>"
                    + DailyDigestService._miss_box("今日货代文档未采集到 (今日尚未执行采集批次)"))
            return html, meta
        if row["status"] not in ("success", "partial"):
            html = (f"<h3 style='margin:0 0 6px;'>🚢 货代文档采集</h3>"
                    + DailyDigestService._miss_box(
                        f"今日货代文档未采集到 (批次状态: {row['status']}{('; ' + row['message'][:150]) if row['message'] else ''})"))
            return html, meta
        meta.update({"ok": True, "alerts": len(alerts),
                     "docs_total": row["docs_total"] or 0, "docs_ok": row["docs_ok"] or 0,
                     "docs_failed": row["docs_failed"] or 0})
        head = f"<p>今日采集文档 <b>{meta['docs_total']}</b> 个, 成功 <b>{meta['docs_ok']}</b>"
        if meta["docs_failed"]:
            head += f", 失败 <b style='color:#dc2626;'>{meta['docs_failed']}</b>"
        if meta["alerts"]:
            head += f", 超期告警 <b style='color:#dc2626;'>{meta['alerts']}</b> 行</p>"
        else:
            head += "</p><p style='color:#16a34a;'>✅ 无超期告警</p>"
        if not alerts:
            return (f"<h3 style='margin:0 0 6px;'>🚢 货代文档采集</h3>{head}"
                    f"<p style='color:#16a34a;'>✅ 无超过 {DailyDigestService.get_config()['alert_days']} 天未发货的记录</p>"), meta
        # 按货代分组输出告警明细表
        groups: Dict[str, List[dict]] = {}
        for a in alerts:
            groups.setdefault(a.get("forwarder_name") or "未知货代", []).append(a)
        parts = [f"<h3 style='margin:0 0 6px;'>🚢 货代文档采集</h3>{head}"]
        for fwd_name, items in groups.items():
            parts.append(f"<p style='margin:10px 0 4px;font-weight:700;'>{fwd_name} ({len(items)} 行)</p>")
            parts.append(DailyDigestService._alert_table(items))
        return "".join(parts), meta

    @staticmethod
    def _alert_table(items: List[dict]) -> str:
        rows_html = ""
        cols_in_use = []
        parsed = []
        for a in items:
            try:
                data = json.loads(a.get("row_json") or "{}")
            except Exception:
                data = {}
            parsed.append(data)
            for c in _ALERT_DISPLAY_COLUMNS:
                if c in data and c not in cols_in_use:
                    cols_in_use.append(c)
        for a, data in zip(items, parsed):
            detail_cells = "".join(
                f"<td style='border:1px solid #e5e7eb;padding:4px 8px;'>{str(data.get(c, '') or '')[:60]}</td>"
                for c in cols_in_use)
            rows_html += (f"<tr><td style='border:1px solid #e5e7eb;padding:4px 8px;'>{a.get('purchase_date', '')}</td>"
                          f"<td style='border:1px solid #e5e7eb;padding:4px 8px;color:#dc2626;font-weight:700;'>"
                          f"{a.get('days_elapsed', '')} 天</td>{detail_cells}</tr>")
        head_cells = "".join(
            f"<th style='border:1px solid #e5e7eb;background:#f8fafc;padding:5px 8px;text-align:left;'>{c}</th>"
            for c in ["采购日期", "未发货天数"] + cols_in_use)
        return (f"<table style='border-collapse:collapse;font-size:12.5px;'>"
                f"<thead><tr>{head_cells}</tr></thead><tbody>{rows_html}</tbody></table>")

    # ───────────────── 区块B: 店小秘 8 点批次 ─────────────────
    @staticmethod
    def dxm_section(biz_date: str) -> tuple:
        """今日 8 点店小秘批次区块 (橘色+红色/超时未发货订单); 返回 (html, {ok, alert_rows, yellow, red})"""
        meta = {"ok": False, "alert_rows": 0, "yellow": 0, "red": 0}
        day_prefix = f"{biz_date} {_DXM_EIGHT_BATCH_START:02d}"
        window_end = f"{biz_date} {_DXM_EIGHT_BATCH_END:02d}"
        conn = get_db_connection()
        try:
            batch = conn.execute(
                "SELECT id, started_at, orders_total FROM dxm_order_sync_logs "
                "WHERE status = 'success' AND started_at >= ? AND started_at < ? "
                "ORDER BY id DESC LIMIT 1", (day_prefix, window_end)).fetchone()
            rows: List[Dict[str, Any]] = []
            if batch:
                rows = [dict(r) for r in conn.execute(
                    "SELECT order_no, shop_name, site, order_status, deadline_at, remaining_minutes, alert_level "
                    "FROM dxm_order_deadlines WHERE alert_level >= 1 "
                    "AND order_status NOT LIKE 'Shipped%' AND order_status != 'shipped' "
                    "ORDER BY remaining_minutes ASC").fetchall()]
        finally:
            conn.close()
        if not batch:
            html = (f"<h3 style='margin:0 0 6px;'>📦 店小秘订单预警 (今日 8 点批次 · 橘色+红色)</h3>"
                    + DailyDigestService._miss_box(
                        "今日店小秘订单未采集到 (8 点批次未执行成功, 上件任务占用或登录失败时批次会跳过)"))
            return html, meta
        meta.update({"ok": True, "alert_rows": len(rows),
                     "yellow": sum(1 for r in rows if r["alert_level"] == 1),
                     "red": sum(1 for r in rows if r["alert_level"] == 2)})
        head = (f"<p>8 点批次采集 <b>{batch['orders_total'] or 0}</b> 单 · "
                f"橘色预警 <b style='color:#d97706;'>{meta['yellow']}</b> 单 · "
                f"红色/超时 <b style='color:#dc2626;'>{meta['red']}</b> 单</p>")
        if not rows:
            return (f"<h3 style='margin:0 0 6px;'>📦 店小秘订单预警 (今日 8 点批次)</h3>{head}"
                    f"<p style='color:#16a34a;'>✅ 无橘色/红色预警未发货订单</p>"), meta
        body = ""
        for r in rows:
            color = "#d97706" if r["alert_level"] == 1 else "#dc2626"
            body += (
                f"<tr><td style='border:1px solid #e5e7eb;padding:4px 8px;'>{r['order_no']}</td>"
                f"<td style='border:1px solid #e5e7eb;padding:4px 8px;'>{str(r['shop_name'] or '')[:40]}</td>"
                f"<td style='border:1px solid #e5e7eb;padding:4px 8px;'>{r['site'] or ''}</td>"
                f"<td style='border:1px solid #e5e7eb;padding:4px 8px;color:{color};font-weight:700;'>"
                f"{DailyDigestService._fmt_remaining(r['remaining_minutes'])}</td>"
                f"<td style='border:1px solid #e5e7eb;padding:4px 8px;'>{r['deadline_at'] or ''}</td>"
                f"<td style='border:1px solid #e5e7eb;padding:4px 8px;'>{r['order_status'] or ''}</td></tr>")
        table = ("<table style='border-collapse:collapse;font-size:12.5px;'>"
                 "<thead><tr>" + "".join(
                     f"<th style='border:1px solid #e5e7eb;background:#f8fafc;padding:5px 8px;text-align:left;'>{c}</th>"
                     for c in ["订单号", "店铺", "站点", "剩余时间", "发货截止", "状态"]) +
                 f"</tr></thead><tbody>{body}</tbody></table>")
        return (f"<h3 style='margin:0 0 6px;'>📦 店小秘订单预警 (今日 8 点批次 · 橘色+红色)</h3>{head}{table}"), meta

    # ───────────────── 公共小件 ─────────────────
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
    def _miss_box(reason: str) -> str:
        return (f"<div style='border:1px solid #fecaca;background:#fef2f2;border-radius:6px;"
                f"padding:8px 12px;color:#b91c1c;'>⚠️ 未采集到 — {reason}</div>")

    @staticmethod
    def _build_digest_html(biz_date: str, fwd_html: str, dxm_html: str) -> str:
        return (f"<div style='font-family:Microsoft YaHei,Arial;font-size:13px;'>"
                f"<h2 style='margin:0 0 10px;'>📋 每日监控汇总 <small style='color:#6b7280;font-size:12px;'>{biz_date}</small></h2>"
                f"<div style='border:1px solid #e5e7eb;border-radius:8px;padding:12px 14px;margin-bottom:14px;'>{fwd_html}</div>"
                f"<div style='border:1px solid #e5e7eb;border-radius:8px;padding:12px 14px;'>{dxm_html}</div>"
                f"<p style='color:#94a3b8;font-size:11px;margin-top:14px;'>"
                f"本邮件由 ERP 中间件每日汇总任务自动发送 (货代文档采集 · 店小秘订单预警)</p></div>")

    @staticmethod
    def get_status() -> Dict[str, Any]:
        last = get_setting("daily_digest_last", None)
        return {"sending": DailyDigestService.is_sending(),
                "last": last if isinstance(last, dict) else None,
                "config": DailyDigestService.get_config()}
