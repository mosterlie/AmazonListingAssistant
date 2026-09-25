"""
日本节假日服务 (JpHolidayService) — 日历同步 + 大节日邮件提醒

同步: 定时从 date.nager.at 公共 API 拉取日本法定节假日 (当年+次年) 入库 jp_holidays 表,
      心跳每天检查一次 (last_sync_date ≠ 今天或数据缺失即同步)。
提醒: 每天心跳检查 advance_days (默认7) 内是否有法定节假日, 有且当天未发 → 发送邮件。
      连休自动计算 (节假日+相邻周六日连续区间), 连休 >= MAJOR_BREAK_DAYS 视为「大节日」高亮。

SMTP 通道复用货代采集配置 (fwd_doc_* 扁平键), 提醒配置用 jp_holiday_* 扁平键存 system_settings。
"""
import json
import smtplib
import threading
import urllib.request
from datetime import date, datetime, timedelta
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any, Dict, List, Optional, Set, Tuple

from server.database import get_db_connection, get_setting, set_setting
from server.services.forwarder_doc_service import ForwarderDocService

_API_URL = "https://date.nager.at/api/v3/PublicHolidays/{year}/JP"

# 连休 >= 此天数视为「大节日」(黄金周/正月等)
MAJOR_BREAK_DAYS = 3

_WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _today() -> date:
    return date.today()


def _fmt(d: date) -> str:
    return d.strftime("%Y-%m-%d")


_SEND_LOCK = threading.Lock()
_SENDING = {"sending": False}
_SYNC_LOCK = threading.Lock()


class JpHolidayService:

    # ───────────────── 配置 ─────────────────
    @staticmethod
    def get_config(override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """SMTP 通道复用货代采集配置 (fwd_doc_*), 叠加 jp_holiday_* 提醒配置"""
        smtp = ForwarderDocService.get_config(override)
        ov = override or {}
        cfg = {
            "email_enabled": bool(get_setting("jp_holiday_email_enabled", False)),
            "advance_days": 7,
            "mail_to": [],
            "smtp_host": smtp.get("smtp_host", ""),
            "smtp_port": smtp.get("smtp_port", 465),
            "smtp_ssl": smtp.get("smtp_ssl", True),
            "smtp_user": smtp.get("smtp_user", ""),
            "smtp_password": smtp.get("smtp_password", ""),
            "mail_from": smtp.get("mail_from", ""),
        }
        if "email_enabled" in ov:
            cfg["email_enabled"] = bool(ov["email_enabled"])
        try:
            cfg["advance_days"] = max(1, int(get_setting("jp_holiday_advance_days", 7)))
        except Exception:
            pass
        if "advance_days" in ov:
            try:
                cfg["advance_days"] = max(1, int(ov["advance_days"]))
            except Exception:
                pass
        mail_to = str(ov.get("mail_to") or get_setting("jp_holiday_mail_to", "") or "").strip()
        if mail_to:
            cfg["mail_to"] = [x.strip() for x in mail_to.split(",") if x.strip()]
        else:  # 未配置独立收件人 → 用默认收件人
            cfg["mail_to"] = smtp.get("mail_to", [])
        return cfg

    @staticmethod
    def save_config(patch: Dict[str, Any]) -> Dict[str, Any]:
        if "email_enabled" in patch:
            set_setting("jp_holiday_email_enabled", bool(patch["email_enabled"]))
        if "advance_days" in patch:
            try:
                set_setting("jp_holiday_advance_days", max(1, int(patch["advance_days"])))
            except Exception:
                pass
        if "mail_to" in patch:
            set_setting("jp_holiday_mail_to", str(patch["mail_to"] or "").strip())
        return JpHolidayService.get_config()

    # ───────────────── 同步 ─────────────────
    @staticmethod
    def sync_year(year: int) -> int:
        """从 date.nager.at 拉取指定年份日本法定节假日并入库, 返回条数"""
        url = _API_URL.format(year=year)
        req = urllib.request.Request(url, headers={"User-Agent": "ERP-Middleware/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            items = json.loads(resp.read().decode("utf-8"))
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db_connection()
        try:
            for it in items:
                conn.execute(
                    "INSERT INTO jp_holidays (date, name, local_name, types, synced_at) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(date) DO UPDATE SET name = excluded.name, "
                    "local_name = excluded.local_name, types = excluded.types, "
                    "synced_at = excluded.synced_at",
                    (it.get("date"), it.get("name") or "", it.get("localName") or "",
                     ",".join(it.get("types") or []), now_str))
            conn.commit()
        finally:
            conn.close()
        return len(items)

    @staticmethod
    def sync_due(force: bool = False) -> Dict[str, Any]:
        """心跳调用 (每天一次): 当年+次年数据缺失或未同步过 → 拉取; 返回同步摘要"""
        if not _SYNC_LOCK.acquire(blocking=False):
            return {"skipped": True, "msg": "已有同步在执行"}
        try:
            now = _today()
            last = get_setting("jp_holiday_last_sync", None)
            years_needed = [now.year, now.year + 1]
            conn = get_db_connection()
            try:
                counts = {}
                for y in years_needed:
                    row = conn.execute(
                        "SELECT COUNT(*) AS n FROM jp_holidays WHERE date LIKE ?",
                        (f"{y}-%",)).fetchone()
                    counts[y] = row["n"] if row else 0
            finally:
                conn.close()
            need = force or last is None or any(counts[y] == 0 for y in years_needed)
            if not need:
                return {"skipped": True, "msg": "今日已同步且数据齐全"}
            result: Dict[str, Any] = {"years": {}}
            for y in years_needed:
                try:
                    result["years"][str(y)] = JpHolidayService.sync_year(y)
                except Exception as e:
                    result["years"][str(y)] = f"failed: {e.__class__.__name__}: {str(e)[:150]}"
            set_setting("jp_holiday_last_sync", {
                "date": _fmt(now), "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
            return result
        finally:
            _SYNC_LOCK.release()

    # ───────────────── 日历/连休 ─────────────────
    @staticmethod
    def _load_holidays(years: List[int]) -> Dict[str, Dict[str, str]]:
        """加载指定年份的节假日 (date -> {name, local_name, types})"""
        conds = " OR ".join(["date LIKE ?"] * len(years))
        params = [f"{y}-%" for y in years]
        conn = get_db_connection()
        try:
            rows = conn.execute(
                f"SELECT date, name, local_name, types FROM jp_holidays WHERE {conds}",
                params).fetchall()
        finally:
            conn.close()
        return {r["date"]: {"name": r["name"], "local_name": r["local_name"],
                            "types": r["types"]} for r in rows}

    @staticmethod
    def break_window(d: date, hol_set: Set[str]) -> Tuple[date, date]:
        """包含 d 的连休区间 (节假日 + 相邻周六日连续扩展)"""
        start = end = d
        while True:
            prev = start - timedelta(days=1)
            if prev.weekday() >= 5 or _fmt(prev) in hol_set:
                start = prev
            else:
                break
        while True:
            nxt = end + timedelta(days=1)
            if nxt.weekday() >= 5 or _fmt(nxt) in hol_set:
                end = nxt
            else:
                break
        return start, end

    @staticmethod
    def upcoming(days: Optional[int] = None) -> List[Dict[str, Any]]:
        """未来 N 天 (默认取配置 advance_days) 内的节假日, 附连休信息; 同一连休只列首日"""
        cfg = JpHolidayService.get_config()
        n = days if days is not None else cfg["advance_days"]
        today = _today()
        hol = JpHolidayService._load_holidays([today.year - 1, today.year, today.year + 1])
        hol_set = set(hol.keys())
        seen_windows: Set[str] = set()
        out: List[Dict[str, Any]] = []
        for i in range(max(1, int(n)) + 1):
            d = today + timedelta(days=i)
            key = _fmt(d)
            if key not in hol_set:
                continue
            start, end = JpHolidayService.break_window(d, hol_set)
            wkey = _fmt(start)
            if wkey in seen_windows:
                continue
            seen_windows.add(wkey)
            length = (end - start).days + 1
            info = hol[key]
            out.append({
                "date": key,
                "weekday": _WEEKDAY_CN[d.weekday()],
                "name": info["name"],
                "local_name": info["local_name"],
                "break_start": _fmt(start),
                "break_end": _fmt(end),
                "break_days": length,
                "is_major": length >= MAJOR_BREAK_DAYS,
                "days_until": i,
            })
        return out

    @staticmethod
    def month_calendar(year: int, month: int) -> Dict[str, Any]:
        """月历数据: 每天附 is_holiday/is_weekend/holiday 信息"""
        hol = JpHolidayService._load_holidays([year])  # 跨月周末扩展需要邻月, 下方单独补
        hol_next = JpHolidayService._load_holidays(
            [year - 1, year, year + 1])
        hol.update(hol_next)
        first = date(year, month, 1)
        nxt_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        days: List[Dict[str, Any]] = []
        d = first
        while d < nxt_month:
            key = _fmt(d)
            info = hol.get(key)
            days.append({
                "date": key,
                "weekday": d.weekday(),
                "is_weekend": d.weekday() >= 5,
                "is_off": d.weekday() >= 5 or info is not None,  # 休息日 = 周末或法定节假日
                "holiday_name": (info or {}).get("local_name") or (info or {}).get("name") or "",
            })
            d += timedelta(days=1)
        return {"year": year, "month": month,
                "first_weekday": first.weekday(), "days": days}

    # ───────────────── 邮件提醒 ─────────────────
    @staticmethod
    def maybe_send_reminder() -> bool:
        """心跳调用 (每60s): 开关开启 + advance_days 内有节日 + 今天未发 → 后台线程发送"""
        if _SEND_LOCK.locked() or _SENDING["sending"]:
            return False
        cfg = JpHolidayService.get_config()
        if not cfg["email_enabled"]:
            return False
        items = JpHolidayService.upcoming()
        if not items:
            return False
        last = get_setting("jp_holiday_reminder_last", None)
        if isinstance(last, dict) and last.get("date") == _fmt(_today()):
            return False
        threading.Thread(target=JpHolidayService.send_reminder,
                         kwargs={"trigger": "scheduled", "items": items},
                         daemon=True).start()
        return True

    @staticmethod
    def send_reminder(trigger: str = "manual", items: Optional[List[Dict[str, Any]]] = None) -> str:
        """组装并发送临近节日提醒邮件 (阻塞); 结果记入 jp_holiday_reminder_last"""
        if not _SEND_LOCK.acquire(blocking=False):
            return "skipped: 已有发送任务在执行"
        _SENDING["sending"] = True
        try:
            cfg = JpHolidayService.get_config()
            if items is None:
                items = JpHolidayService.upcoming()
            if not cfg.get("mail_to"):
                status = "failed: 未配置收件人"
            elif not items:
                status = "skipped: 提前窗口内无节日"
            else:
                status = JpHolidayService._send_email(cfg, items)
            set_setting("jp_holiday_reminder_last", {
                "date": _fmt(_today()), "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "trigger": trigger, "status": status})
            return status
        finally:
            _SENDING["sending"] = False
            _SEND_LOCK.release()

    @staticmethod
    def _send_email(cfg: Dict[str, Any], items: List[Dict[str, Any]]) -> str:
        try:
            today = _fmt(_today())
            majors = [x for x in items if x["is_major"]]
            top = items[0]
            subject = (f"[日本节日提醒] {top['date']} {top['local_name'] or top['name']}"
                       f"{' 等 %d 个节日' % len(items) if len(items) > 1 else ''}"
                       f"{' (含大节日连休)' if majors else ''}")
            html = JpHolidayService._build_html(today, items)
            msg = MIMEMultipart("alternative")
            msg["Subject"] = Header(subject, "utf-8")
            msg["From"] = formataddr((Header("ERP日本节日提醒", "utf-8").encode(),
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
    def _build_html(today: str, items: List[Dict[str, Any]]) -> str:
        rows = ""
        for x in items:
            major_badge = (f"<span style='background:#dc2626;color:#fff;border-radius:4px;"
                           f"padding:1px 6px;font-size:11px;margin-left:6px;'>大节日 连休{x['break_days']}天</span>"
                           if x["is_major"] else
                           (f"<span style='background:#d97706;color:#fff;border-radius:4px;"
                            f"padding:1px 6px;font-size:11px;margin-left:6px;'>连休{x['break_days']}天</span>"
                            if x["break_days"] > 1 else ""))
            range_txt = (x["date"] if x["break_days"] <= 1
                         else f"{x['break_start']} ~ {x['break_end']}")
            rows += (
                f"<tr><td style='border:1px solid #e5e7eb;padding:5px 8px;white-space:nowrap;'>{range_txt}</td>"
                f"<td style='border:1px solid #e5e7eb;padding:5px 8px;'>{x['weekday']}</td>"
                f"<td style='border:1px solid #e5e7eb;padding:5px 8px;font-weight:700;'>"
                f"{x['local_name'] or x['name']}{major_badge}</td>"
                f"<td style='border:1px solid #e5e7eb;padding:5px 8px;color:#6b7280;'>{x['name']}</td>"
                f"<td style='border:1px solid #e5e7eb;padding:5px 8px;'>还有 {x['days_until']} 天</td></tr>")
        head_cells = "".join(
            f"<th style='border:1px solid #e5e7eb;background:#f8fafc;padding:5px 8px;text-align:left;'>{c}</th>"
            for c in ["日期", "星期", "节日", "英文名", "倒计时"])
        return (
            f"<div style='font-family:Microsoft YaHei,Arial;font-size:13px;'>"
            f"<h2 style='margin:0 0 10px;'>🇯🇵 日本节日临近提醒 "
            f"<small style='color:#6b7280;font-size:12px;'>{today}</small></h2>"
            f"<p>未来 <b>{JpHolidayService.get_config()['advance_days']}</b> 天内有 "
            f"<b>{len(items)}</b> 个日本法定节假日"
            f"{'，其中 <b style=color:#dc2626>大节日连休</b> 请提前安排发货计划' if any(x['is_major'] for x in items) else ''}：</p>"
            f"<table style='border-collapse:collapse;font-size:12.5px;'>"
            f"<thead><tr>{head_cells}</tr></thead><tbody>{rows}</tbody></table>"
            f"<p style='color:#94a3b8;font-size:11px;margin-top:14px;'>"
            f"本邮件由 ERP 中间件日本节日提醒任务自动发送 (日历来源: date.nager.at)</p></div>")

    @staticmethod
    def send_test_email(cfg_override: Optional[Dict[str, Any]] = None) -> str:
        """发送测试提醒邮件 (表单当前值不落库; 无临近节日时发送全库概要)"""
        cfg = JpHolidayService.get_config(cfg_override)
        if not cfg.get("mail_to"):
            return "failed: 未配置收件人"
        items = JpHolidayService.upcoming(days=max(cfg["advance_days"], 90))
        if not items:
            return "skipped: 90 天内无法定节假日"
        return JpHolidayService._send_email(cfg, items)

    # ───────────────── 状态 ─────────────────
    @staticmethod
    def get_status() -> Dict[str, Any]:
        conn = get_db_connection()
        try:
            total = conn.execute("SELECT COUNT(*) AS n FROM jp_holidays").fetchone()["n"]
            years = [dict(r) for r in conn.execute(
                "SELECT SUBSTR(date, 1, 4) AS y, COUNT(*) AS n FROM jp_holidays "
                "GROUP BY y ORDER BY y").fetchall()]
            latest = conn.execute(
                "SELECT MAX(synced_at) AS t FROM jp_holidays").fetchone()["t"]
        finally:
            conn.close()
        return {
            "sending": bool(_SENDING["sending"]),
            "last_sync": get_setting("jp_holiday_last_sync", None),
            "last_reminder": get_setting("jp_holiday_reminder_last", None),
            "total": total,
            "years": years,
            "latest_synced_at": latest,
            "upcoming": JpHolidayService.upcoming(days=90),
            "config": JpHolidayService.get_config(),
        }
