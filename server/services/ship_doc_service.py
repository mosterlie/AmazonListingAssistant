"""发货文档同步 (ShipDocService)

用途: 从腾讯文档「发货数据」sheet 读取「订单号 → 国内单号」映射, 回补履约订单中为空的国内单号。

采集方式与「货代文档采集」一致: 复用 TencentDocExtractor (headless 浏览器直读全部 sheet 的二维行),
**只在内存中解析, 不落库、不落地文件**; 结果按 5 分钟缓存在进程内, 避免同步连点重复起浏览器。

同一订单在文档里出现多行 (分批发货) → 国内单号拼接为 "A、B"。
"""
import re
import time
from datetime import datetime
from typing import Any, Dict, List

from server.database import get_db_connection
from server.services.tencent_doc_extractor import TencentDocExtractor

DOC_URL = "https://docs.qq.com/sheet/DZUhLTndIdmJyY0dH?tab=BB08J2"
TARGET_SHEET = "发货数据"      # 只读这个 sheet (模糊匹配, 排除「已发货数据」)
CACHE_TTL = 300               # 采集结果缓存 5 分钟

_CACHE: Dict[str, Any] = {"at": 0.0, "map": {}}

ORDER_RE = re.compile(r"^\d{3}-\d{7}-\d{7}$")
# 占位/无效值: 不能当成真实国内单号
INVALID_NOS = {"", "-", "无", "None", "null", "待补录", "待补充", "待定", "待填", "暂无"}


class ShipDocService:

    # ───────── 采集 ─────────
    @staticmethod
    def _fetch_from_doc() -> Dict[str, List[str]]:
        """headless 浏览器读取在线文档 → {订单号: [国内单号]} (失败返回空)"""
        try:
            with TencentDocExtractor() as extractor:
                doc = extractor.extract_doc(DOC_URL)
        except Exception:
            return {}
        sheet = None
        for s in doc.get("sheets", []):
            name = str(s.get("sheet_name") or "").strip()
            if name == TARGET_SHEET:
                sheet = s
                break
        if sheet is None:                      # 兜底: 模糊匹配但排除「已发货数据」
            for s in doc.get("sheets", []):
                name = str(s.get("sheet_name") or "").strip()
                if TARGET_SHEET in name and "已发货" not in name:
                    sheet = s
                    break
        if sheet is None:
            return {}
        rows = sheet.get("rows") or []
        return ShipDocService.rows_to_map(rows[1:] if rows else [])

    # ───────── 解析 ─────────
    @staticmethod
    def rows_to_map(rows: List[List[Any]]) -> Dict[str, List[str]]:
        """二维行 → {订单号: [国内单号, ...]}; 按「订单号」动态定位, 国内单号取其左侧第 2 列"""
        out: Dict[str, List[str]] = {}
        for raw in rows or []:
            cells = [str(c or "").strip() for c in raw]
            oi = next((i for i, c in enumerate(cells) if ORDER_RE.match(c)), -1)
            if oi < 0:
                continue
            order_sn = cells[oi]
            cn_no = cells[oi - 2] if oi >= 2 else ""      # 国内单号 / 国际单号 / 订单号
            if not cn_no or cn_no in INVALID_NOS:
                continue
            bucket = out.setdefault(order_sn, [])
            if cn_no not in bucket:                        # 多行 → 去重保留顺序
                bucket.append(cn_no)
        return out

    # ───────── 缓存 ─────────
    @staticmethod
    def fetch_map(use_cache: bool = True) -> Dict[str, List[str]]:
        """{订单号: [国内单号]}, 进程内缓存 5 分钟"""
        now = time.time()
        if use_cache and _CACHE["map"] and (now - _CACHE["at"]) < CACHE_TTL:
            return _CACHE["map"]
        data = ShipDocService._fetch_from_doc()
        if data:
            _CACHE["map"] = data
            _CACHE["at"] = now
        return data

    # ───────── 回补 ─────────
    @staticmethod
    def backfill_domestic(limit: int = 100, dry_run: bool = False) -> Dict[str, Any]:
        """把文档里的国内单号回补到国内单号为空的履约订单 (已有值不覆盖)

        返回 {checked, matched, updated, doc_rows, samples, error}
        """
        stats: Dict[str, Any] = {"checked": 0, "matched": 0, "updated": 0,
                                 "doc_rows": 0, "samples": [], "error": ""}
        doc = ShipDocService.fetch_map()
        stats["doc_rows"] = len(doc)
        if not doc:
            stats["error"] = "未采集到发货文档数据 (文档未打开/结构变化/网络异常)"
            return stats

        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT id, order_sn FROM fm_orders "
                "WHERE IFNULL(domestic_tracking_no, '') = '' "
                "AND IFNULL(order_sn, '') <> '' ORDER BY id DESC"
            ).fetchall()
            stats["checked"] = len(rows)
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for r in rows:
                sn = str(r["order_sn"] or "").strip()
                nos = doc.get(sn) or []
                if not nos:
                    continue
                stats["matched"] += 1
                if len(stats["samples"]) < 10:
                    stats["samples"].append({"order_sn": sn,
                                             "domestic_tracking_no": "、".join(nos)})
                if dry_run:
                    continue
                conn.execute(
                    "UPDATE fm_orders SET domestic_tracking_no = ?, updated_at = ? "
                    "WHERE id = ? AND IFNULL(domestic_tracking_no, '') = ''",
                    ("、".join(nos), now_str, int(r["id"])))
                stats["updated"] += 1
                if limit and stats["updated"] >= int(limit):
                    break
            if not dry_run:
                conn.commit()
        finally:
            conn.close()
        return stats
