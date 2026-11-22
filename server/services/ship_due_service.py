"""即将发货提醒 (ShipDueService)

规则:
- 每小时检查一次待发货订单 (fm_orders.order_status = 'wait_seller_send')
- 剩余发货时间 <= 阈值 (默认 2 小时, 可配置) 时发送邮件提醒
- 支持多个收件人 (英文逗号分隔); SMTP 通道复用 系统管理 → 邮件配置

数据来源: dxm_order_deadlines.deadline_at (由店小秘 orderTimeoutTime 采集而来)
"""
import json
import smtplib
import threading
import time
from datetime import datetime
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any, Dict, List, Optional

from server.database import get_db_connection, get_setting, set_setting

# settings 键
K_ENABLED = "ship_due_enabled"
K_HOURS = "ship_due_hours"
K_MAIL_TO = "ship_due_mail_to"
K_SUBJECT = "ship_due_subject_prefix"
K_ALERTED = "ship_due_alerted"          # 已提醒记录 {order_sn: deadline_at}
K_LAST_RUN = "ship_due_last_run"

DEFAULTS = {
    "enabled": False,
    "hours": 2,
    "mail_to": "",
    "subject_prefix": "[即将超时发货提醒]",
}

_RUN_LOCK = threading.Lock()
_STATE: Dict[str, Any] = {"running": False, "last_run": None, "last_result": None}


class ShipDueService:

    # ───────── 配置 ─────────
    @staticmethod
    def get_config() -> Dict[str, Any]:
        def _num(key: str, default: float) -> float:
            try:
                return float(get_setting(key) or default)
            except (TypeError, ValueError):
                return default

        return {
            "email_enabled": str(get_setting(K_ENABLED) or "").lower() in ("1", "true", "yes"),
            "hours": _num(K_HOURS, DEFAULTS["hours"]),
            "mail_to": str(get_setting(K_MAIL_TO) or ""),
            "subject_prefix": str(get_setting(K_SUBJECT) or DEFAULTS["subject_prefix"]),
        }

    @staticmethod
    def save_config(patch: Dict[str, Any]) -> Dict[str, Any]:
        patch = patch or {}
        if "email_enabled" in patch:
            set_setting(K_ENABLED, "1" if patch["email_enabled"] else "0")
        if "hours" in patch and patch["hours"] not in (None, ""):
            try:
                hour = max(0.1, min(float(patch["hours"]), 240))
            except (TypeError, ValueError):
                hour = DEFAULTS["hours"]
            set_setting(K_HOURS, str(hour))
        if "mail_to" in patch:
            set_setting(K_MAIL_TO, str(patch.get("mail_to") or "").strip())
        if "subject_prefix" in patch:
            set_setting(K_SUBJECT, str(patch.get("subject_prefix") or "").strip()
                        or DEFAULTS["subject_prefix"])
        return ShipDueService.get_config()

    @staticmethod
    def _smtp_config() -> Dict[str, Any]:
        """复用货代采集的 SMTP 通道配置"""
        from server.services.forwarder_doc_service import ForwarderDocService
        fwd = ForwarderDocService.get_config()
        return {k: fwd.get(k) for k in ("smtp_host", "smtp_port", "smtp_ssl", "smtp_user",
                                        "smtp_password", "mail_from")}

    # ───────── 数据 ─────────
    @staticmethod
    def pending_orders(hours: float) -> List[Dict[str, Any]]:
        """剩余发货时间 <= hours 的待发货订单 (含已超时)"""
        limit_min = float(hours) * 60
        now = datetime.now()
        conn = get_db_connection()
        try:
            rows = conn.execute("""
                SELECT o.order_sn, o.order_status_text, o.gmt_order,
                       d.deadline_at, d.shop_name
                  FROM fm_orders o
                  JOIN dxm_order_deadlines d ON d.order_no = o.order_sn
                 WHERE o.order_status = 'wait_seller_send'
                   AND IFNULL(d.deadline_at, '') <> ''
                 ORDER BY d.deadline_at
            """).fetchall()
        finally:
            conn.close()

        out = []
        for r in rows:
            try:
                deadline = datetime.strptime(str(r["deadline_at"])[:19], "%Y-%m-%d %H:%M:%S")
            except (TypeError, ValueError):
                continue
            remain_min = int((deadline - now).total_seconds() // 60)
            if remain_min > limit_min:
                continue
            out.append({
                "order_sn": r["order_sn"],
                "shop_name": r["shop_name"] or "",
                "order_status": r["order_status_text"] or "",
                "deadline_at": str(r["deadline_at"])[:19],
                "remaining_minutes": remain_min,
                "overdue": remain_min <= 0,
            })
        return out

    @staticmethod
    def _fmt_remaining(minutes: int) -> str:
        """剩余/超时时长, 精确到分钟: 1天10小时23分 / 5小时8分 / 42分钟"""
        prefix = "已超时 " if minutes <= 0 else ""
        total = abs(int(minutes))
        d, rem = divmod(total, 1440)
        h, m = divmod(rem, 60)
        if d:
            return f"{prefix}{d}天{h}小时{m}分"
        if h:
            return f"{prefix}{h}小时{m}分"
        return f"{prefix}{m}分钟"

    # ───────── 邮件 ─────────
    @staticmethod
    def _send_email(cfg: Dict[str, Any], rows: List[Dict[str, Any]],
                    hours: float) -> str:
        try:
            to_list = [x.strip() for x in str(cfg.get("mail_to") or "").split(",") if x.strip()]
            if not to_list:
                return "failed: 未配置收件人"
            smtp = ShipDueService._smtp_config()
            if not smtp.get("smtp_user"):
                return "failed: 未配置 SMTP (系统管理 → 邮件配置)"
            overdue_n = sum(1 for r in rows if r["overdue"])
            subject = (f"{cfg.get('subject_prefix') or DEFAULTS['subject_prefix']} "
                       f"{len(rows)} 单剩余不足 {hours:g} 小时"
                       f"{f'（已超时 {overdue_n} 单）' if overdue_n else ''} "
                       f"({datetime.now().strftime('%m-%d %H:%M')})")
            body_rows = ""
            for r in rows:
                color = "#dc2626" if r["overdue"] else "#d97706"
                body_rows += (
                    f"<tr><td style='border:1px solid #e5e7eb;padding:4px 8px;'>{r['order_sn']}</td>"
                    f"<td style='border:1px solid #e5e7eb;padding:4px 8px;'>{(r['shop_name'] or '-')[:40]}</td>"
                    f"<td style='border:1px solid #e5e7eb;padding:4px 8px;color:{color};font-weight:700;'>"
                    f"{ShipDueService._fmt_remaining(r['remaining_minutes'])}</td>"
                    f"<td style='border:1px solid #e5e7eb;padding:4px 8px;'>{r['deadline_at']}</td>"
                    f"<td style='border:1px solid #e5e7eb;padding:4px 8px;'>{r['order_status'] or '-'}</td></tr>")
            html = (
                "<div style='font-family:Microsoft YaHei,Arial;font-size:13px;'>"
                "<h2 style='color:#ea580c;'>⏰ 即将超时发货提醒</h2>"
                f"<p>以下 <b>{len(rows)}</b> 单待发货订单的剩余发货时间已不足 "
                f"<b>{hours:g} 小时</b>（阈值可在 系统管理 → 告警任务 中调整）：</p>"
                "<table style='border-collapse:collapse;font-size:12.5px;'>"
                "<thead><tr>" + "".join(
                    f"<th style='border:1px solid #e5e7eb;background:#f8fafc;padding:5px 8px;text-align:left;'>{c}</th>"
                    for c in ["订单号", "店铺", "剩余时间", "发货截止", "状态"]) +
                f"</tr></thead><tbody>{body_rows}</tbody></table>"
                "<p style='color:#94a3b8;font-size:11px;margin-top:14px;'>"
                "本邮件由 ERP「即将发货提醒」任务自动发送（每小时检查一次）</p></div>")
            msg = MIMEMultipart("alternative")
            msg["Subject"] = Header(subject, "utf-8")
            msg["From"] = formataddr((Header("ERP即将发货提醒", "utf-8").encode(),
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

    # ───────── 执行 ─────────
    @staticmethod
    def run_once(force: bool = False) -> Dict[str, Any]:
        """检查一次并发送提醒; force=True 时忽略开关与去重 (手动执行)"""
        if not _RUN_LOCK.acquire(blocking=False):
            return {"skipped": True, "msg": "上一次检查仍在进行"}
        _STATE["running"] = True
        started = datetime.now()
        try:
            cfg = ShipDueService.get_config()
            if not cfg["email_enabled"] and not force:
                return {"skipped": True, "msg": "提醒未开启"}
            if not cfg["mail_to"] and not force:
                return {"skipped": True, "msg": "未配置收件人"}

            hours = float(cfg["hours"] or DEFAULTS["hours"])
            rows = ShipDueService.pending_orders(hours)

            # 去重: 同一订单同一截止时间只提醒一次 (deadline 变化会再提醒)
            # force=True (手动点「立即检查」) 时跳过去重, 总是发送本次匹配结果
            try:
                alerted = json.loads(get_setting(K_ALERTED) or "{}")
            except Exception:
                alerted = {}
            fresh = rows if force else [
                r for r in rows if alerted.get(r["order_sn"]) != r["deadline_at"]]
            result: Dict[str, Any] = {
                "hours": hours, "matched": len(rows), "alerted": 0,
                "skipped_dup": len(rows) - len(fresh), "email_status": "",
                "orders": [r["order_sn"] for r in rows],
            }
            if fresh:
                result["email_status"] = ShipDueService._send_email(cfg, fresh, hours)
                if result["email_status"] == "sent":
                    for r in fresh:
                        alerted[r["order_sn"]] = r["deadline_at"]
                    # 清理已不在列表里的旧记录, 防止无限增长
                    keep = {r["order_sn"] for r in rows}
                    alerted = {k: v for k, v in alerted.items() if k in keep}
                    set_setting(K_ALERTED, json.dumps(alerted, ensure_ascii=False))
                    result["alerted"] = len(fresh)
            else:
                result["email_status"] = "skip: 无新增提醒"

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            set_setting(K_LAST_RUN, now_str)
            result["at"] = now_str
            _STATE["last_run"] = now_str
            _STATE["last_result"] = result
            return result
        finally:
            _STATE["running"] = False
            _RUN_LOCK.release()
            _STATE["duration_ms"] = int((datetime.now() - started).total_seconds() * 1000)

    @staticmethod
    def maybe_trigger_scheduled() -> bool:
        """每小时整点后触发一次 (60s 心跳调用)"""
        cfg = ShipDueService.get_config()
        if not cfg["email_enabled"]:
            return False
        last = str(get_setting(K_LAST_RUN) or "")
        now = datetime.now()
        hour_key = now.strftime("%Y-%m-%d %H")
        if last.startswith(hour_key):
            return False
        threading.Thread(target=ShipDueService.run_once, daemon=True).start()
        return True

    @staticmethod
    def send_test_email(cfg_override: Optional[Dict[str, Any]] = None) -> str:
        cfg = ShipDueService.get_config()
        if isinstance(cfg_override, dict):
            if str(cfg_override.get("mail_to") or "").strip():
                cfg["mail_to"] = str(cfg_override["mail_to"]).strip()
            if str(cfg_override.get("subject_prefix") or "").strip():
                cfg["subject_prefix"] = str(cfg_override["subject_prefix"]).strip()
        hours = float(cfg.get("hours") or DEFAULTS["hours"])
        sample = [{"order_sn": "TEST-000-0000000", "shop_name": "测试店铺",
                   "order_status": "待发货", "deadline_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   "remaining_minutes": int(hours * 60) - 30,
                   "overdue": False}]
        return ShipDueService._send_email(cfg, sample, hours)

    @staticmethod
    def get_status() -> Dict[str, Any]:
        cfg = ShipDueService.get_config()
        try:
            hours = float(cfg["hours"] or DEFAULTS["hours"])
            matched = len(ShipDueService.pending_orders(hours))
        except Exception:
            matched = 0
        return {
            "running": _STATE["running"],
            "enabled": bool(cfg["email_enabled"]),
            "hours": cfg["hours"],
            "matched_now": matched,
            "last_run": _STATE["last_run"] or get_setting(K_LAST_RUN) or "",
            "last_result": _STATE["last_result"],
        }
