"""
本地运单库服务 (运单管理: 运单查询 / 轨迹跟踪)

背景: 初道 API 不提供订单列表接口, 无法枚举 appToken 下所有订单 →
本地建 forwarder_waybills 运单库, 页面批量粘贴单号入库并调初道 API
识别 + 刷新运输状态; 「轨迹跟踪」页按单实时查轨迹。

表结构见 database.py #12c forwarder_waybills。
"""
import sqlite3
from typing import Any, Dict, List, Optional

from server.database import get_db_connection
from server.services.chudao_service import ChudaoService, ChudaoApiError

MAX_BATCH_ADD = 200  # 单次入库单号上限


class WaybillService:
    """运单库: 列表 / 批量入库识别 / 状态刷新 / 删除"""

    # ─────────────────────────── 查询 ───────────────────────────

    @staticmethod
    def list_waybills(keyword: str = "", limit: int = 500) -> List[Dict[str, Any]]:
        """运单列表 (keyword 模糊匹配 参考号/运单号/尾程单号/渠道单号), 按更新时间倒序"""
        sql = ("SELECT id, reference_no, tracking_number, server_hawbcode, channel_hawbcode, "
               "dest_country, track_status, track_status_name, last_track_desc, last_track_time, "
               "source, note, created_by, created_at, updated_at FROM forwarder_waybills")
        params: List[Any] = []
        if keyword:
            kw = f"%{keyword.strip()}%"
            sql += (" WHERE IFNULL(reference_no,'') LIKE ? OR IFNULL(tracking_number,'') LIKE ? "
                    "OR IFNULL(server_hawbcode,'') LIKE ? OR IFNULL(channel_hawbcode,'') LIKE ?")
            params = [kw, kw, kw, kw]
        sql += " ORDER BY datetime(updated_at) DESC, id DESC LIMIT ?"
        params.append(max(1, min(limit, 2000)))
        conn = get_db_connection()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    # ─────────────────────────── 入库识别 ───────────────────────────

    @staticmethod
    def _normalize_numbers(raw_numbers: List[str]) -> List[str]:
        """清洗单号: 去空白/去重, 保持输入顺序"""
        seen, out = set(), []
        for no in raw_numbers:
            no = str(no or "").strip().strip(",").strip()
            if no and no not in seen:
                seen.add(no)
                out.append(no)
        return out

    @staticmethod
    def _track_summary(track: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """gettrack data[0] → 表字段摘要"""
        if not track:
            return {}
        details = track.get("details") or []
        last = details[0] if details else {}
        return {
            "dest_country": track.get("destination_country") or "",
            "track_status": track.get("track_status") or "",
            "track_status_name": track.get("track_status_name") or "",
            "last_track_desc": (last.get("track_description") or "").strip(),
            "last_track_time": last.get("track_occur_date") or "",
            "server_hawbcode": track.get("server_hawbcode") or "",
            "channel_hawbcode": track.get("channel_hawbcode") or "",
        }

    @staticmethod
    def _row_exists(number: str) -> Optional[int]:
        """按 运单号/尾程单号/参考号 查已有行 id (三列任一命中即视为已入库); 不存在返回 None"""
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT id FROM forwarder_waybills "
                "WHERE tracking_number = ? OR reference_no = ? OR server_hawbcode = ? LIMIT 1",
                (number, number, number)).fetchone()
        finally:
            conn.close()
        return row["id"] if row else None

    @staticmethod
    def _insert_waybill(number: str, summary: Dict[str, Any], created_by: str,
                        reference_no: str = "", source: str = "paste", note: str = "") -> int:
        conn = get_db_connection()
        try:
            cur = conn.execute(
                "INSERT INTO forwarder_waybills "
                "(reference_no, tracking_number, server_hawbcode, channel_hawbcode, "
                 "dest_country, track_status, track_status_name, last_track_desc, "
                 "last_track_time, source, note, created_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (reference_no or None, number, summary.get("server_hawbcode", ""),
                 summary.get("channel_hawbcode", ""), summary.get("dest_country", ""),
                 summary.get("track_status", ""), summary.get("track_status_name", ""),
                 summary.get("last_track_desc", ""), summary.get("last_track_time", ""),
                 source, note, created_by))
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    @staticmethod
    def add_numbers(raw_numbers: List[str], created_by: str = "") -> Dict[str, Any]:
        """批量入库: 清洗 → 批量识别(gettrackingnumberbatch) → 逐单调轨迹(gettrack)补状态 → 落库

        返回 {"added": [...], "existing": [...], "failed": [{"number","reason"}], "total": n}
        - added: 新增成功 (返回运单号)
        - existing: 库中已存在 (返回运单号)
        - failed: 初道系统未查到 / 调用失败
        """
        numbers = WaybillService._normalize_numbers(raw_numbers)
        if not numbers:
            return {"added": [], "existing": [], "failed": [], "total": 0}
        if len(numbers) > MAX_BATCH_ADD:
            raise ValueError(f"单次最多入库 {MAX_BATCH_ADD} 个单号 (本次 {len(numbers)} 个)")

        added: List[str] = []
        existing: List[str] = []
        failed: List[Dict[str, str]] = []

        # 1) 批量识别 (调用失败整体失败, 不产生脏数据)
        try:
            batch_map = ChudaoService.get_tracking_numbers_batch(numbers)
        except ChudaoApiError as exc:
            return {"added": [], "existing": [],
                    "failed": [{"number": n, "reason": f"批量识别调用失败: {exc}"} for n in numbers],
                    "total": len(numbers)}

        # 2) 逐单落库 + 调轨迹补状态
        for no in numbers:
            if WaybillService._row_exists(no):
                existing.append(no)
                continue
            if no not in batch_map:
                failed.append({"number": no, "reason": "初道系统中未查到该单号"})
                continue
            try:
                track = ChudaoService.get_track(no)
            except ChudaoApiError as exc:
                failed.append({"number": no, "reason": f"轨迹查询失败: {exc}"})
                continue
            try:
                WaybillService._insert_waybill(no, WaybillService._track_summary(track), created_by)
                added.append(no)
            except sqlite3.IntegrityError:
                existing.append(no)  # 并发重复插入兜底

        return {"added": added, "existing": existing, "failed": failed, "total": len(numbers)}

    # ─────────────────────── 妙手同步入库 ───────────────────────

    @staticmethod
    def sync_from_miaoshou(packages: List[Dict[str, Any]], created_by: str = "") -> Dict[str, Any]:
        """妙手包裹批量入库 (packages 为 MiaoshouService.fetch_shipped_packages 归一化结果)

        流程: 尾程号(logisticsNo) 批量反查初岛号(gettrackingnumberbatch) →
        tracking_number=初岛号(未反查到则用尾程号), server_hawbcode=尾程号,
        reference_no=平台订单号 → 幂等去重后逐单调 gettrack 补状态 → 落库。

        返回 {"fetched", "added", "existing", "failed", "total"}
        """
        # 清洗尾程号 (保持顺序去重)
        tail_nos = WaybillService._normalize_numbers(
            [p.get("tracking_no") for p in packages if p.get("tracking_no")])
        empty = {"fetched": len(packages), "added": [], "existing": [], "failed": [], "total": 0}
        if not tail_nos:
            return empty

        # 1) 批量反查: 尾程号 → 初岛号 (反查失败不阻塞, 退回尾程号直接入库)
        reverse: Dict[str, str] = {}  # {尾程号: 初岛号}
        try:
            batch_map = ChudaoService.get_tracking_numbers_batch(tail_nos[:MAX_BATCH_ADD])
            for initial_no, info in batch_map.items():
                sm_no = (info.get("shipping_method_no") or "").strip()
                if sm_no:
                    reverse[sm_no] = initial_no
        except ChudaoApiError:
            pass

        added: List[str] = []
        existing: List[str] = []
        failed: List[Dict[str, str]] = []
        for p in packages:
            tail_no = (p.get("tracking_no") or "").strip()
            if not tail_no:
                continue
            initial_no = reverse.get(tail_no, "")
            primary = initial_no or tail_no
            if WaybillService._row_exists(primary) or WaybillService._row_exists(tail_no):
                existing.append(primary)
                continue
            try:
                track = ChudaoService.get_track(primary)
            except ChudaoApiError as exc:
                failed.append({"number": primary, "reason": f"轨迹查询失败: {exc}"})
                continue
            if not track:
                failed.append({"number": primary, "reason": "初道系统中未查到该单号"})
                continue
            summary = WaybillService._track_summary(track)
            if not summary.get("server_hawbcode"):
                summary["server_hawbcode"] = tail_no  # 尾程号兜底
            try:
                WaybillService._insert_waybill(
                    primary, summary, created_by,
                    reference_no=p.get("platform_order_sn") or "",
                    source="miaoshou", note=p.get("note") or "")
                added.append(primary)
            except sqlite3.IntegrityError:
                existing.append(primary)  # 并发重复插入兜底

        return {"fetched": len(packages), "added": added, "existing": existing,
                "failed": failed, "total": len(added) + len(existing) + len(failed)}

    # ─────────────────────────── 状态刷新 ───────────────────────────

    @staticmethod
    def refresh_one(number: str) -> bool:
        """按运单号刷新单行状态 (gettrack → UPDATE); 找不到该行返回 False"""
        track = ChudaoService.get_track(number)
        if not track:
            return False
        s = WaybillService._track_summary(track)
        conn = get_db_connection()
        try:
            cur = conn.execute(
                "UPDATE forwarder_waybills SET server_hawbcode=?, channel_hawbcode=?, dest_country=?, "
                "track_status=?, track_status_name=?, last_track_desc=?, last_track_time=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE tracking_number=?",
                (s.get("server_hawbcode", ""), s.get("channel_hawbcode", ""), s.get("dest_country", ""),
                 s.get("track_status", ""), s.get("track_status_name", ""),
                 s.get("last_track_desc", ""), s.get("last_track_time", ""), number))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    @staticmethod
    def refresh_waybills(waybill_ids: Optional[List[int]] = None) -> Dict[str, Any]:
        """批量刷新状态 (不传 ids 刷全部); 返回 {refreshed, missing, failed}"""
        conn = get_db_connection()
        try:
            if waybill_ids:
                marks = ",".join("?" * len(waybill_ids))
                rows = conn.execute(
                    f"SELECT id, tracking_number FROM forwarder_waybills WHERE id IN ({marks})",
                    waybill_ids).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, tracking_number FROM forwarder_waybills "
                    "WHERE tracking_number IS NOT NULL").fetchall()
        finally:
            conn.close()
        refreshed: List[int] = []
        missing: List[int] = []
        failed: List[Dict[str, Any]] = []
        for r in rows:
            try:
                if WaybillService.refresh_one(r["tracking_number"]):
                    refreshed.append(r["id"])
                else:
                    missing.append(r["id"])
            except ChudaoApiError as exc:
                failed.append({"id": r["id"], "reason": str(exc)})
        return {"refreshed": refreshed, "missing": missing, "failed": failed}

    # ─────────────────────────── 删除 ───────────────────────────

    @staticmethod
    def delete_waybill(waybill_id: int) -> None:
        conn = get_db_connection()
        try:
            cur = conn.execute("DELETE FROM forwarder_waybills WHERE id = ?", (waybill_id,))
            if cur.rowcount == 0:
                raise ValueError(f"运单不存在: #{waybill_id}")
            conn.commit()
        finally:
            conn.close()
