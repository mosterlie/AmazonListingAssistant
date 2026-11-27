"""每日订单同步 (OrderDailySyncService)

每日 02:00 (可配) 自动执行, 覆盖近 N 天 (默认 30 天), 等价于页面「同步」按钮的完整链路:
  1. 妙手订单包裹同步        OrderService.sync_orders(days)
  2. 初岛运单轨迹刷新        OrderService.refresh_tracks(ids)
  3. 佐川官网轨迹补全        OrderService.apply_sagawa_tracks(ids)
     (未签收的佐川单号自动查官网; 配達完了 → 运单状态置「派送妥投」)
  4. 履约订单/包裹同步       FulfillmentService.sync_from_miaoshou(days, pull=False)
  5. 发货文档回补 + 登记判定  ShipDocService.backfill_domestic / mark_registration

配置存 system_settings (order_daily_sync_*):
  enabled / time / days / sagawa_limit
上次执行结果存 order_daily_sync_last (JSON), 供「今日是否已跑」判断与页面展示。
"""
import json
import threading
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

from server.database import get_db_connection, get_setting, set_setting
from server.services.order_service import OrderService

_DEFAULT_CONFIG = {
    "enabled": True,
    "time": "02:00",        # 每日执行时间 (HH:MM)
    "days": 30,             # 同步/更新近 N 天
    "sagawa_limit": 300,    # 单次最多补多少单佐川轨迹
}

_RUN_LOCK = threading.Lock()
_STATE: Dict[str, Any] = {"running": False, "trigger": "", "started_at": ""}


class OrderDailySyncService:

    # ───────────────── 配置 ─────────────────
    @staticmethod
    def get_config() -> Dict[str, Any]:
        cfg = dict(_DEFAULT_CONFIG)
        for key in _DEFAULT_CONFIG:
            val = get_setting(f"order_daily_sync_{key}")
            if val is not None:
                cfg[key] = val
        cfg["enabled"] = bool(cfg.get("enabled", True))
        try:
            cfg["days"] = max(1, int(cfg["days"]))
        except Exception:
            cfg["days"] = 30
        try:
            cfg["sagawa_limit"] = max(1, int(cfg["sagawa_limit"]))
        except Exception:
            cfg["sagawa_limit"] = 300
        return cfg

    @staticmethod
    def save_config(patch: Dict[str, Any]) -> Dict[str, Any]:
        for key, val in (patch or {}).items():
            if key in _DEFAULT_CONFIG:
                set_setting(f"order_daily_sync_{key}", val)
        return OrderDailySyncService.get_config()

    # ───────────────── 执行 ─────────────────
    @staticmethod
    def is_running() -> bool:
        return bool(_STATE["running"])

    @staticmethod
    def run(trigger: str = "manual", days: Optional[int] = None,
            on_progress=None) -> Dict[str, Any]:
        """执行一次完整同步 (阻塞); 已有任务在跑则返回 skipped"""
        if not _RUN_LOCK.acquire(blocking=False):
            return {"skipped": True, "msg": "已有同步任务在运行"}
        cfg = OrderDailySyncService.get_config()
        days = int(days or cfg["days"])
        started = datetime.now()
        _STATE.update(running=True, trigger=trigger, started_at=started.isoformat())
        summary: Dict[str, Any] = {"trigger": trigger, "days": days,
                                   "started_at": started.strftime("%Y-%m-%d %H:%M:%S"),
                                   "steps": {}, "error": ""}

        def progress(msg: str) -> None:
            if on_progress:
                try:
                    on_progress(msg)
                except Exception:
                    pass
            print(f"[OrderDailySync] {msg}", flush=True)

        try:
            # 1) 妙手同步
            progress(f"① 妙手同步近 {days} 天订单…")
            sync = OrderService.sync_orders(days=days, on_progress=progress)
            ids = sync.get("ids") or []
            summary["steps"]["miaoshou"] = {"fetched": sync.get("fetched", 0),
                                            "inserted": sync.get("inserted", 0),
                                            "updated": sync.get("updated", 0),
                                            "ids": len(ids)}
            progress(f"① 妙手完成: 拉取 {sync.get('fetched', 0)} / 涉及 {len(ids)} 单")

            # 2) 初岛轨迹
            if ids:
                progress(f"② 刷新初岛轨迹 {len(ids)} 单…")
                tracks = OrderService.refresh_tracks(ids)
                summary["steps"]["chudao"] = {"refreshed": len(tracks.get("refreshed") or []),
                                              "failed": len(tracks.get("failed") or [])}
                progress(f"② 初岛完成: 成功 {summary['steps']['chudao']['refreshed']} / "
                         f"失败 {summary['steps']['chudao']['failed']}")
            else:
                summary["steps"]["chudao"] = {"refreshed": 0, "failed": 0}

            # 3) 佐川官网轨迹 (配達完了自动置派送妥投)
            if ids:
                progress("③ 查询佐川官网轨迹…")
                sg = OrderService.apply_sagawa_tracks(ids, limit=cfg["sagawa_limit"])
                summary["steps"]["sagawa"] = sg
                progress(f"③ 佐川完成: 命中 {sg.get('queried', 0)} 单 / "
                         f"签收 {sg.get('delivered', 0)} / 更新 {sg.get('updated', 0)}")
            else:
                summary["steps"]["sagawa"] = {"checked": 0}

            # 4) 履约订单/包裹
            try:
                progress("④ 同步履约订单…")
                from server.services.fulfillment_service import FulfillmentService
                fm = FulfillmentService.sync_from_miaoshou(days=days, pull=False,
                                                           username="system")
                summary["steps"]["fulfillment"] = {"orders": fm.get("orders", 0),
                                                   "packages": fm.get("packages", 0)}
                progress(f"④ 履约完成: {fm.get('orders', 0)} 单 / {fm.get('packages', 0)} 包裹")
            except Exception as exc:
                summary["steps"]["fulfillment"] = {"error": f"{exc.__class__.__name__}: {exc}"}
                progress(f"④ 履约同步失败: {exc}")

            # 5) 发货文档: 回补国内单号 + 在线登记判定
            try:
                progress("⑤ 读取发货文档…")
                from server.services.ship_doc_service import ShipDocService
                dom = ShipDocService.backfill_domestic(limit=200)
                reg = ShipDocService.mark_registration()
                summary["steps"]["ship_doc"] = {
                    "domestic_backfilled": dom.get("updated", 0),
                    "registered_missing": reg.get("missing", 0),
                    "error": dom.get("error") or reg.get("error") or "",
                }
                progress(f"⑤ 发货文档: 回补 {dom.get('updated', 0)} 单 / "
                         f"未登记 {reg.get('missing', 0)} 单")
            except Exception as exc:
                summary["steps"]["ship_doc"] = {"error": f"{exc.__class__.__name__}: {exc}"}

            summary["ok"] = True
        except Exception as exc:
            summary["error"] = f"{exc.__class__.__name__}: {exc}"
            summary["traceback"] = traceback.format_exc()[-1200:]
            progress(f"同步失败: {summary['error']}")
        finally:
            finished = datetime.now()
            summary["finished_at"] = finished.strftime("%Y-%m-%d %H:%M:%S")
            summary["duration_s"] = int((finished - started).total_seconds())
            _STATE.update(running=False, trigger="", started_at="")
            _RUN_LOCK.release()
            try:
                set_setting("order_daily_sync_last", summary)
            except Exception:
                pass
            try:
                OrderDailySyncService._insert_log(summary)
            except Exception:
                pass
        return summary

    # ───────────────── 记录 ─────────────────
    @staticmethod
    def _insert_log(summary: Dict[str, Any]) -> None:
        """每次执行落一条记录 (页面「同步记录」列表用)"""
        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO order_sync_logs (trigger_type, days, status, started_at, finished_at, "
                "duration_s, summary_json, error) VALUES (?,?,?,?,?,?,?,?)",
                (summary.get("trigger", ""), int(summary.get("days") or 0),
                 "success" if summary.get("ok") else "failed",
                 summary.get("started_at", ""), summary.get("finished_at", ""),
                 int(summary.get("duration_s") or 0),
                 json.dumps(summary.get("steps") or {}, ensure_ascii=False),
                 summary.get("error", "")))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _import_legacy_last() -> None:
        """老版本只存了 order_daily_sync_last: 表为空时补录成第一条记录"""
        conn = get_db_connection()
        try:
            cnt = conn.execute("SELECT COUNT(*) c FROM order_sync_logs").fetchone()["c"]
        finally:
            conn.close()
        if cnt:
            return
        last = get_setting("order_daily_sync_last")
        if isinstance(last, dict) and last.get("started_at"):
            OrderDailySyncService._insert_log(last)

    @staticmethod
    def get_logs(limit: int = 30) -> List[Dict[str, Any]]:
        """执行记录 (新→旧), 每条带 steps 供页面展开详情"""
        OrderDailySyncService._import_legacy_last()
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT id, trigger_type, days, status, started_at, finished_at, duration_s, "
                "summary_json, error FROM order_sync_logs ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit or 30), 200)),)).fetchall()
        finally:
            conn.close()
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            try:
                d["steps"] = json.loads(d.pop("summary_json") or "{}")
            except Exception:
                d["steps"] = {}
            d["ok"] = d.get("status") == "success"
            out.append(d)
        return out

    # ───────────────── 调度 ─────────────────
    @staticmethod
    def maybe_trigger_scheduled() -> bool:
        """心跳 (每 60s): 到达配置时间且今天还没跑过 → 后台线程执行"""
        if _RUN_LOCK.locked() or _STATE["running"]:
            return False
        cfg = OrderDailySyncService.get_config()
        if not cfg.get("enabled", True):
            return False
        now = datetime.now()
        try:
            hh, mm = str(cfg.get("time") or "02:00").split(":")[:2]
            due = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        except Exception:
            due = now.replace(hour=2, minute=0, second=0, microsecond=0)
        if now < due:
            return False
        last = get_setting("order_daily_sync_last")
        now_str = now.strftime("%Y-%m-%d")
        if isinstance(last, dict):
            started = str(last.get("started_at") or "")
            if started[:10] == now_str:
                if last.get("ok"):
                    return False        # 今天已成功跑过
                try:                    # 今天跑失败了: 10 分钟后重试, 避免每分钟反复起浏览器
                    last_dt = datetime.strptime(started, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    last_dt = None
                if last_dt and (now - last_dt).total_seconds() < 600:
                    return False
        threading.Thread(target=OrderDailySyncService.run,
                         kwargs={"trigger": "scheduled"}, daemon=True).start()
        return True

    @staticmethod
    def get_status() -> Dict[str, Any]:
        return {"running": _STATE["running"], "trigger": _STATE["trigger"],
                "started_at": _STATE["started_at"],
                "config": OrderDailySyncService.get_config(),
                "last": get_setting("order_daily_sync_last") or {}}
