"""
货代在线登记文档定时采集服务 (ForwarderDocService)

流程 (每批次, 纯采集不发邮件 — 邮件已解耦至 daily_digest_service 每日汇总任务):
  1. 读取 forwarders 表全部货代的「在线链接」(在线登记文档, 不含货代网址)
  2. 按 (doc_id, tab) 去重后, 无头浏览器直读腾讯文档全部 sheet (TencentDocExtractor)
  3. 幂等入库: 先删当天 (biz_date) 同链接快照再插入 (重跑=删当天重跑)
  4. 告警: 「发货数据」sheet 内, 采购日期可解析 + 发货列为空 + (当天-采购日期) >= 阈值(默认7, 大于等于)

配置全部存 system_settings (fwd_doc_* 扁平键), 系统管理页维护。
其中 smtp_*/mail_*/subject_prefix/email_enabled/digest_time 由每日汇总邮件任务
(DailyDigestService) 消费, email_enabled=每日汇总邮件总开关, digest_time=发送时间(默认08:15)。
"""
import json
import re
import threading
import traceback
from datetime import datetime, date
from typing import Any, Dict, List, Optional

from server.database import get_db_connection, get_setting, set_setting
from server.services.forwarder_service import ForwarderService
from server.services.tencent_doc_extractor import TencentDocExtractor, parse_doc_url

_DEFAULT_CONFIG = {
    "sync_mode": "daily",        # daily=每天定时 / interval=间隔轮询
    "sync_time": "08:00",
    "interval_hours": 24,
    "alert_days": 7,
    "date_column": "采购日期",
    "ship_column": "仓库发货日期",
    "sheet_name": "发货数据",
    "email_enabled": False,      # 每日汇总邮件总开关 (DailyDigestService 消费)
    "digest_time": "08:15",      # 每日汇总邮件发送时间 (HH:MM)
    "smtp_host": "smtp.qq.com",
    "smtp_port": 465,
    "smtp_ssl": True,
    "smtp_user": "",
    "smtp_password": "",
    "mail_from": "",
    "mail_to": [],
    "subject_prefix": "[货代发货提醒]",
}

_RUN_LOCK = threading.Lock()
_RUNNING = {"running": False, "trigger": None, "started_at": None}


def _today() -> date:
    return date.today()


def _norm_header(h: Any) -> str:
    """表头规范化: 富文本已拍平, 折叠换行/空白"""
    if h is None:
        return ""
    s = str(h)
    return re.sub(r"[\s\r\n]+", "", s)


def _parse_purchase_date(v: Any) -> Optional[date]:
    """采购日期解析: 支持 20260921 整数 / '2026-9-21' / '2026/9/21' / '2026.9.21'"""
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        n = int(v)
        if 19990101 <= n <= 21001231:
            try:
                return date(n // 10000, (n // 100) % 100, n % 100)
            except ValueError:
                return None
        return None
    s = str(v).strip()
    if re.fullmatch(r"\d{8}", s):
        try:
            return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        except ValueError:
            return None
    m = re.fullmatch(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def _is_empty(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or v == 0


class ForwarderDocService:

    # ───────────────── 配置 ─────────────────
    @staticmethod
    def get_config(override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        cfg = dict(_DEFAULT_CONFIG)
        raw = get_setting("fwd_doc_config")
        if isinstance(raw, dict):
            cfg.update({k: v for k, v in raw.items() if k in _DEFAULT_CONFIG})
        # 兼容扁平键覆盖 (settings_router 逐键保存)
        for key in _DEFAULT_CONFIG:
            val = get_setting(f"fwd_doc_{key}")
            if val is not None:
                cfg[key] = val
        if override:
            cfg.update({k: v for k, v in override.items() if k in _DEFAULT_CONFIG})
        try:
            cfg["alert_days"] = max(1, int(cfg["alert_days"]))
        except Exception:
            cfg["alert_days"] = 7
        try:
            cfg["interval_hours"] = max(1, int(cfg["interval_hours"]))
        except Exception:
            cfg["interval_hours"] = 24
        try:
            cfg["smtp_port"] = int(cfg["smtp_port"] or 465)
        except Exception:
            cfg["smtp_port"] = 465
        if isinstance(cfg["mail_to"], str):
            cfg["mail_to"] = [x.strip() for x in cfg["mail_to"].split(",") if x.strip()]
        cfg["email_enabled"] = bool(cfg["email_enabled"])
        cfg["smtp_ssl"] = bool(cfg["smtp_ssl"])
        return cfg

    @staticmethod
    def save_config(patch: Dict[str, Any]) -> Dict[str, Any]:
        current = {k: v for k, v in ForwarderDocService.get_config().items()}
        for k, v in (patch or {}).items():
            if k in _DEFAULT_CONFIG:
                current[k] = v
        for key, val in current.items():
            set_setting(f"fwd_doc_{key}", val)
        return ForwarderDocService.get_config()

    # ───────────────── 批次执行 ─────────────────
    @staticmethod
    def run_batch(trigger: str = "manual") -> Dict[str, Any]:
        """同步执行一个采集批次 (阻塞); 已有批次运行中则返回 skipped"""
        if not _RUN_LOCK.acquire(blocking=False):
            return {"skipped": True, "msg": "已有采集批次在运行"}
        started = datetime.now()
        biz_date = _today().isoformat()
        conn = get_db_connection()
        try:
            cur = conn.execute(
                "INSERT INTO forwarder_doc_sync_logs (biz_date, trigger_type, status, started_at) "
                "VALUES (?, ?, 'running', CURRENT_TIMESTAMP)", (biz_date, trigger))
            log_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        _RUNNING.update({"running": True, "trigger": trigger, "started_at": started.isoformat()})

        summary: Dict[str, Any] = {"log_id": log_id, "biz_date": biz_date, "docs": []}
        try:
            summary = ForwarderDocService._execute(biz_date, summary)
            docs = summary.get("docs", [])
            ok_n = sum(1 for d in docs if d.get("status") == "success")
            fail_n = len(docs) - ok_n
            status = "success" if fail_n == 0 else ("failed" if ok_n == 0 else "partial")
            ForwarderDocService._finish_log(log_id, status, summary)
        except Exception as e:
            summary["error"] = f"{e.__class__.__name__}: {e}"
            summary["traceback"] = traceback.format_exc()[-1500:]
            ForwarderDocService._finish_log(log_id, "failed", summary)
        finally:
            _RUNNING.update({"running": False, "trigger": None, "started_at": None})
            _RUN_LOCK.release()
        return summary

    @staticmethod
    def _execute(biz_date: str, summary: Dict[str, Any]) -> Dict[str, Any]:
        cfg = ForwarderDocService.get_config()
        today = _today()

        # 1. 收集全部货代的在线链接 (按 doc_id+tab 去重, 归属首个货代/链接)
        jobs: Dict[str, Dict[str, Any]] = {}
        for fwd in ForwarderService.list_forwarders(include_secret=False):
            for lk in (fwd.get("links") or []):
                try:
                    parsed = parse_doc_url(lk["url"])
                except ValueError as e:
                    summary["docs"].append({"forwarder": fwd["name"], "url": lk["url"][:60],
                                            "status": "skipped", "msg": str(e)[:120]})
                    continue
                key = f"{parsed['doc_id']}#{parsed['tab'] or ''}"
                if key not in jobs:
                    jobs[key] = {"doc_id": parsed["doc_id"], "tab": parsed["tab"],
                                 "forwarder_id": fwd["id"], "forwarder_name": fwd["name"],
                                 "link_label": lk.get("label", ""), "link_url": lk["url"]}
        summary["docs_total"] = len(jobs)
        summary["docs_ok"] = 0

        # 2. 逐文档提取 + 入库
        all_alerts: List[Dict[str, Any]] = []
        with TencentDocExtractor() as extractor:
            for key, job in jobs.items():
                doc_summary = {"forwarder": job["forwarder_name"], "doc_id": job["doc_id"],
                               "url": job["link_url"][:80]}
                try:
                    doc = extractor.extract_doc(job["link_url"])
                    rows_total = 0
                    # 登记表按 (link_url, biz_date) 先清后插: 只保留本次实际采集到的 sheet
                    conn = get_db_connection()
                    try:
                        conn.execute(
                            "DELETE FROM forwarder_doc_sheets WHERE link_url = ? AND biz_date = ?",
                            (job["link_url"], biz_date))
                        conn.commit()
                    finally:
                        conn.close()
                    for sheet in doc.get("sheets", []):
                        rows = sheet.get("rows") or []
                        ForwarderDocService._store_sheet(biz_date, job, sheet["sheet_name"],
                                                         sheet.get("sheet_id") or "", rows)
                        rows_total += max(0, len(rows) - 1)
                        if _norm_header(sheet["sheet_name"]) == _norm_header(cfg["sheet_name"]):
                            all_alerts.extend(ForwarderDocService._compute_alerts(
                                biz_date, job, sheet, cfg, today))
                    doc_summary.update({"status": "success", "rows": rows_total,
                                        "sheets": [s.get("sheet_name") for s in doc.get("sheets", [])]})
                    summary["docs_ok"] += 1
                except Exception as e:
                    doc_summary.update({"status": "failed", "msg": f"{e.__class__.__name__}: {e}"})
                summary["docs"].append(doc_summary)

        # 3. 告警落库
        ForwarderDocService._store_alerts(biz_date, all_alerts)
        summary["alerts_found"] = len(all_alerts)
        summary["alert_days"] = cfg["alert_days"]
        return summary

    @staticmethod
    def _store_sheet(biz_date: str, job: Dict[str, Any], sheet_name: str,
                     sheet_id: str, rows: List[List[Any]]) -> None:
        """幂等入库: 先删当天同链接快照, 再整批插入 (row_json 按列名存)"""
        conn = get_db_connection()
        try:
            conn.execute(
                "DELETE FROM forwarder_doc_snapshots "
                "WHERE link_url = ? AND biz_date = ? AND sheet_name = ?",
                (job["link_url"], biz_date, sheet_name))
            # sheet 登记: 无论有无数据行都登记, 供采集结果页展示 sheet 存在性
            conn.execute(
                "DELETE FROM forwarder_doc_sheets "
                "WHERE link_url = ? AND biz_date = ? AND sheet_name = ?",
                (job["link_url"], biz_date, sheet_name))
            conn.execute(
                "INSERT INTO forwarder_doc_sheets "
                "(forwarder_id, forwarder_name, link_url, doc_id, sheet_name, sheet_id, "
                " row_count, biz_date) VALUES (?,?,?,?,?,?,?,?)",
                (job["forwarder_id"], job["forwarder_name"], job["link_url"], job["doc_id"],
                 sheet_name, sheet_id, max(0, len(rows) - 1), biz_date))
            if not rows:
                conn.commit()
                return
            # 标题行为空的列不采集; 标题行本身不作为数据行入库 (row_index 从 1 起)
            headers = [_norm_header(h) or "" for h in rows[0]]
            valid_idx = [i for i, h in enumerate(headers) if h]
            batch = []
            for idx, row in enumerate(rows[1:], start=1):
                row_json = {headers[i]: row[i] for i in valid_idx if i < len(row)}
                batch.append((job["forwarder_id"], job["forwarder_name"], job["link_label"],
                              job["link_url"], job["doc_id"], sheet_name, sheet_id,
                              idx, json.dumps(row_json, ensure_ascii=False, default=str), biz_date))
            conn.executemany(
                "INSERT INTO forwarder_doc_snapshots "
                "(forwarder_id, forwarder_name, link_label, link_url, doc_id, sheet_name, "
                " sheet_id, row_index, row_json, biz_date) VALUES (?,?,?,?,?,?,?,?,?,?)", batch)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _compute_alerts(biz_date: str, job: Dict[str, Any], sheet: Dict[str, Any],
                        cfg: Dict[str, Any], today: date) -> List[Dict[str, Any]]:
        rows = sheet.get("rows") or []
        if len(rows) < 2:
            return []
        # 空标题列不参与
        headers = [_norm_header(h) or "" for h in rows[0]]
        valid_idx = [i for i, h in enumerate(headers) if h]
        date_col, ship_col = cfg["date_column"], cfg["ship_column"]
        if date_col not in headers:
            return []
        date_idx = headers.index(date_col)
        ship_idx = headers.index(ship_col) if ship_col in headers else None
        alerts = []
        for idx, row in enumerate(rows[1:], start=1):
            purchase = _parse_purchase_date(row[date_idx] if date_idx < len(row) else None)
            if purchase is None:
                continue
            shipped = ship_idx is not None and not _is_empty(row[ship_idx] if ship_idx < len(row) else None)
            if shipped:
                continue
            days = (today - purchase).days
            if days >= cfg["alert_days"]:
                row_json = {headers[i]: row[i] for i in valid_idx if i < len(row)}
                alerts.append({"forwarder_id": job["forwarder_id"], "forwarder_name": job["forwarder_name"],
                               "link_label": job["link_label"], "link_url": job["link_url"],
                               "sheet_name": sheet.get("sheet_name", ""), "row_index": idx,
                               "purchase_date": purchase.isoformat(), "days_elapsed": days,
                               "row_json": json.dumps(row_json, ensure_ascii=False, default=str),
                               "biz_date": biz_date})
        return alerts

    @staticmethod
    def _store_alerts(biz_date: str, alerts: List[Dict[str, Any]]) -> None:
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM forwarder_ship_alerts WHERE biz_date = ?", (biz_date,))
            if alerts:
                conn.executemany(
                    "INSERT INTO forwarder_ship_alerts "
                    "(forwarder_id, forwarder_name, link_label, link_url, sheet_name, row_index, "
                    " purchase_date, days_elapsed, row_json, biz_date) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [tuple(a[k] for k in ("forwarder_id", "forwarder_name", "link_label", "link_url",
                                          "sheet_name", "row_index", "purchase_date", "days_elapsed",
                                          "row_json", "biz_date")) for a in alerts])
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _finish_log(log_id: int, status: str, summary: Dict[str, Any]) -> None:
        conn = get_db_connection()
        try:
            docs = summary.get("docs", [])
            rows_total = sum(d.get("rows", 0) for d in docs if d.get("status") == "success")
            failed = [d for d in docs if d.get("status") == "failed"]
            msg = "; ".join(f"{d.get('forwarder')}/{d.get('doc_id')}: {d.get('msg', '')[:80]}"
                            for d in failed) or "全部文档采集成功"
            conn.execute(
                "UPDATE forwarder_doc_sync_logs SET status = ?, docs_total = ?, docs_ok = ?, "
                "docs_failed = ?, rows_total = ?, alert_rows = ?, email_status = ?, "
                "message = ?, duration_ms = ?, finished_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, summary.get("docs_total", len(docs)), summary.get("docs_ok", 0), len(failed),
                 rows_total, summary.get("alerts_found", 0), summary.get("email_status", ""),
                 msg[:500], int((datetime.now() - datetime.fromisoformat(_RUNNING["started_at"] or datetime.now().isoformat())).total_seconds() * 1000)
                 if _RUNNING.get("started_at") else 0, log_id))
            conn.commit()
        finally:
            conn.close()

    # ───────────────── 调度 ─────────────────
    @staticmethod
    def maybe_trigger_scheduled() -> bool:
        """调度心跳 (每 60s 调用): 到期且空闲则后台线程触发批次"""
        if _RUN_LOCK.locked() or _RUNNING["running"]:
            return False
        cfg = ForwarderDocService.get_config()
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT biz_date, status, started_at FROM forwarder_doc_sync_logs "
                "WHERE status IN ('success','partial') ORDER BY id DESC LIMIT 1").fetchone()
        finally:
            conn.close()
        now = datetime.now()
        if cfg["sync_mode"] == "daily":
            if row and row["biz_date"] == _today().isoformat():
                return False
            try:
                hh, mm = (cfg["sync_time"] or "08:00").split(":")[:2]
                due = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            except Exception:
                due = now.replace(hour=8, minute=0, second=0, microsecond=0)
            if now < due:
                return False
        else:  # interval
            if not row:
                pass  # 无历史 → 立即跑
            else:
                try:
                    last = datetime.fromisoformat(row["started_at"])
                except Exception:
                    last = None
                if last and (now - last).total_seconds() < cfg["interval_hours"] * 3600:
                    return False
        threading.Thread(target=ForwarderDocService.run_batch, kwargs={"trigger": "scheduled"},
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
                "SELECT * FROM forwarder_doc_sync_logs ORDER BY id DESC LIMIT 1").fetchone()
            today = _today().isoformat()
            alert_cnt = conn.execute(
                "SELECT COUNT(*) c FROM forwarder_ship_alerts WHERE biz_date = ?", (today,)).fetchone()["c"]
            doc_cnt = conn.execute(
                "SELECT COUNT(DISTINCT link_url) c FROM forwarder_doc_snapshots WHERE biz_date = ?",
                (today,)).fetchone()["c"]
        finally:
            conn.close()
        return {
            "running": _RUNNING["running"],
            "running_trigger": _RUNNING["trigger"],
            "last_log": dict(last) if last else None,
            "today_alert_count": alert_cnt,
            "today_doc_count": doc_cnt,
            "config": {k: v for k, v in ForwarderDocService.get_config().items() if "password" not in k},
        }

    @staticmethod
    def list_alerts(biz_date: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            if biz_date:
                rows = conn.execute(
                    "SELECT * FROM forwarder_ship_alerts WHERE biz_date = ? ORDER BY days_elapsed DESC",
                    (biz_date,)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM forwarder_ship_alerts ORDER BY biz_date DESC, days_elapsed DESC "
                    "LIMIT 500").fetchall()
        finally:
            conn.close()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["row_data"] = json.loads(d.pop("row_json", "{}"))
            except Exception:
                d["row_data"] = {}
            out.append(d)
        return out

    @staticmethod
    def list_records(biz_date: Optional[str] = None, link_url: Optional[str] = None,
                     sheet_name: Optional[str] = None, page: int = 1,
                     page_size: int = 50, forwarder_id: Optional[int] = None) -> Dict[str, Any]:
        where, params = ["1=1"], []
        if biz_date:
            where.append("biz_date = ?"); params.append(biz_date)
        if link_url:
            where.append("link_url = ?"); params.append(link_url)
        if sheet_name:
            where.append("sheet_name = ?"); params.append(sheet_name)
        if forwarder_id:
            where.append("forwarder_id = ?"); params.append(forwarder_id)
        wsql = " AND ".join(where)
        # sheet 列表过滤条件 (含无数据行的空 sheet, 来自登记表)
        sheet_where, sheet_params = [], []
        if biz_date:
            sheet_where.append("biz_date = ?"); sheet_params.append(biz_date)
        if forwarder_id:
            sheet_where.append("forwarder_id = ?"); sheet_params.append(forwarder_id)
        if link_url:
            sheet_where.append("link_url = ?"); sheet_params.append(link_url)
        swsql = " AND ".join(sheet_where) or "1=1"
        conn = get_db_connection()
        try:
            total = conn.execute(
                f"SELECT COUNT(*) c FROM forwarder_doc_snapshots WHERE {wsql}", params).fetchone()["c"]
            rows = conn.execute(
                f"SELECT * FROM forwarder_doc_snapshots WHERE {wsql} "
                f"ORDER BY link_url, sheet_name, row_index LIMIT ? OFFSET ?",
                params + [page_size, max(0, (page - 1) * page_size)]).fetchall()
            sheets = [r["sheet_name"] for r in conn.execute(
                f"SELECT DISTINCT sheet_name FROM forwarder_doc_sheets WHERE {swsql} "
                f"ORDER BY sheet_name", sheet_params).fetchall()]
        finally:
            conn.close()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["row_data"] = json.loads(d.pop("row_json", "{}"))
            except Exception:
                d["row_data"] = {}
            out.append(d)
        return {"total": total, "page": page, "page_size": page_size,
                "items": out, "sheets": sheets}

    @staticmethod
    def list_biz_dates() -> List[str]:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT DISTINCT biz_date FROM forwarder_doc_snapshots ORDER BY biz_date DESC LIMIT 60"
            ).fetchall()
        finally:
            conn.close()
        return [r["biz_date"] for r in rows]
