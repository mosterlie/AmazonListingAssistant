"""
ASIN 生成池业务服务层 (AsinPoolService)

对齐参考工具 getASIN/main.py 的核心逻辑:
  1. 导入赛狐导出的「所有 SKU 在线产品」Excel (父ASIN/子ASIN), 追加入库并保留历史批次
  2. 输入已投放 ASIN → 在最新批次反查所属父 ASIN → 未覆盖父体各随机取 1 个子 ASIN
  3. 每次生成的输入/结果/忽略项自动登记
"""
import io
import json
import random
from datetime import datetime
from typing import Any, Dict, List, Optional

from openpyxl import Workbook, load_workbook

from server.database import get_db_connection
from server.models.ad_schemas import parse_asins

# 兼容模板列名调整: 父列/子列按顺序取第一个匹配的表头 (与参考工具一致)
PARENT_COLS = ["父ASIN", "父Asin", "父asin"]
CHILD_COLS = ["ASIN", "子ASIN", "子Asin", "子asin"]


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _norm(s: Any) -> str:
    return str(s).strip().upper() if s is not None else ""


def _pick_col(columns: List[str], candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in columns:
            return c
    return None


class AsinPoolService:
    """ASIN 生成池: Excel 导入 / 随机生成 / 记录查询 / 入库总览"""

    # ================= 批次与父子关系 =================

    @staticmethod
    def _latest_batch(conn) -> Optional[Dict[str, Any]]:
        row = conn.execute(
            "SELECT * FROM asin_import_batches ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_batches() -> List[Dict[str, Any]]:
        """全部导入批次 (最新在前), 首条即当前生效批次"""
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT b.*, "
            "  (SELECT COUNT(*) FROM asin_parent_child pc WHERE pc.batch_id = b.id) AS rel_count "
            "FROM asin_import_batches b ORDER BY b.id DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def purge_all() -> Dict[str, int]:
        """清空 ASIN 生成池: 全部导入批次 + 父子关系 + 生成记录 (自增序列重置)"""
        conn = get_db_connection()
        try:
            counts = {
                "batches": conn.execute("SELECT COUNT(*) FROM asin_import_batches").fetchone()[0],
                "pairs": conn.execute("SELECT COUNT(*) FROM asin_parent_child").fetchone()[0],
                "logs": conn.execute("SELECT COUNT(*) FROM asin_query_logs").fetchone()[0],
            }
            conn.execute("DELETE FROM asin_parent_child")
            conn.execute("DELETE FROM asin_import_batches")
            conn.execute("DELETE FROM asin_query_logs")
            conn.execute(
                "DELETE FROM sqlite_sequence WHERE name IN "
                "('asin_import_batches','asin_parent_child','asin_query_logs')")
            conn.commit()
        finally:
            conn.close()
        return counts

    @staticmethod
    def _load_sheet_rows(content: bytes):
        """打开 Excel 并定位首个工作表的数据行迭代器。

        赛狐导出的 xlsx 存在 dimension 元数据错误 (实际 600 行却标记 A1:A1),
        read_only 模式依据 dimension 会漏读全部数据; 故先流式读首行探测,
        找不到必要列时回退普通模式重新加载。
        :return (wb, rows_iter, pi, ci, columns); 失败抛 ValueError
        """
        try:
            wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception as e:
            raise ValueError(f"Excel 文件无法解析, 请确认是 .xlsx 格式: {e}")
        ws = wb.worksheets[0]

        rows_iter = ws.iter_rows(values_only=True)
        try:
            header = next(rows_iter)
        except StopIteration:
            wb.close()
            raise ValueError("Excel 内容为空")
        columns = [_norm(c) for c in header]
        pcol, ccol = _pick_col(columns, PARENT_COLS), _pick_col(columns, CHILD_COLS)

        if not pcol or not ccol:
            # 回退: dimension 元数据损坏导致 read_only 漏读, 普通模式按实际单元格读取
            wb.close()
            wb = load_workbook(io.BytesIO(content), read_only=False, data_only=True)
            ws = wb.worksheets[0]
            rows_iter = ws.iter_rows(values_only=True)
            try:
                header = next(rows_iter)
            except StopIteration:
                wb.close()
                raise ValueError("Excel 内容为空")
            columns = [_norm(c) for c in header]
            pcol, ccol = _pick_col(columns, PARENT_COLS), _pick_col(columns, CHILD_COLS)
            if not pcol or not ccol:
                wb.close()
                raise ValueError(
                    f"缺少必要列! 当前表头: {[c for c in columns if c]}; "
                    f"需要包含父ASIN列({'/'.join(PARENT_COLS)}) 和子ASIN列({'/'.join(CHILD_COLS)})"
                )
        return wb, rows_iter, columns.index(pcol), columns.index(ccol), columns

    @staticmethod
    def import_excel(filename: str, content: bytes, operator: str = "") -> Dict[str, Any]:
        """解析赛狐在线产品 Excel 并追加为一个新批次。

        父 ASIN 为空的独立商品视为自身父级 (parent=child), 与参考工具一致。
        """
        wb, rows_iter, pi, ci, _columns = AsinPoolService._load_sheet_rows(content)

        pairs: set = set()
        excel_rows = 0
        for row in rows_iter:
            if row is None:
                continue
            excel_rows += 1
            child = _norm(row[ci]) if ci < len(row) else ""
            if not child:
                continue
            parent = _norm(row[pi]) if pi < len(row) and row[pi] is not None else ""
            if not parent:
                parent = child
            pairs.add((parent, child))
        wb.close()

        # 兜底: read_only 表头正常但数据行被错误 dimension 截断 (0 数据行),
        # 普通模式重读一次, 避免静默导入空批次
        if excel_rows == 0:
            wb = load_workbook(io.BytesIO(content), read_only=False, data_only=True)
            ws = wb.worksheets[0]
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i == 0:
                    continue
                excel_rows += 1
                child = _norm(row[ci]) if ci < len(row) else ""
                if not child:
                    continue
                parent = _norm(row[pi]) if pi < len(row) and row[pi] is not None else ""
                if not parent:
                    parent = child
                pairs.add((parent, child))
            wb.close()

        if not pairs:
            raise ValueError("未从 Excel 中解析到任何有效 ASIN, 请检查子ASIN列数据")

        imported_at = _now_str()
        conn = get_db_connection()
        try:
            cur = conn.execute(
                "INSERT INTO asin_import_batches "
                "(imported_at, filename, excel_rows, pair_count, parent_count, imported_by) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (imported_at, filename, excel_rows, len(pairs),
                 len({p for p, _ in pairs}), operator),
            )
            batch_id = cur.lastrowid
            conn.executemany(
                "INSERT OR IGNORE INTO asin_parent_child (batch_id, parent, child) VALUES (?, ?, ?)",
                [(batch_id, p, c) for p, c in pairs],
            )
            conn.commit()
        finally:
            conn.close()

        return {
            "batch_id": batch_id,
            "imported_at": imported_at,
            "filename": filename,
            "excel_rows": excel_rows,
            "pair_count": len(pairs),
            "parent_count": len({p for p, _ in pairs}),
            "skipped": excel_rows - len(pairs),
        }

    # ================= 生成 ASIN =================

    @staticmethod
    def generate(asins_text: str, operator: str = "") -> Dict[str, Any]:
        """输入已投放 ASIN → 未覆盖父体各随机取 1 个子 ASIN (算法对齐参考工具)"""
        asins = parse_asins(asins_text, dedup=True)
        if not asins:
            raise ValueError("请输入至少一个 ASIN")

        conn = get_db_connection()
        try:
            batch = AsinPoolService._latest_batch(conn)
            if not batch:
                raise ValueError("ASIN 池为空, 请先导入赛狐在线产品 Excel")
            batch_id = batch["id"]

            # 输入 ASIN -> 所属父 ASIN (仅最新批次)
            ph = ",".join("?" * len(asins))
            found_rows = conn.execute(
                f"SELECT child, parent FROM asin_parent_child "
                f"WHERE batch_id = ? AND child IN ({ph})",
                [batch_id] + asins,
            ).fetchall()
            found = {r["child"]: r["parent"] for r in found_rows}
            matched_parents = sorted({p for p in found.values()})
            missing = [a for a in asins if a not in found]

            # 全部父 ASIN (按入库顺序) 与未覆盖集合
            all_parents = [r["parent"] for r in conn.execute(
                "SELECT parent FROM asin_parent_child WHERE batch_id = ? GROUP BY parent",
                (batch_id,),
            ).fetchall()]
            matched_set = set(matched_parents)
            uncovered = [p for p in all_parents if p not in matched_set]

            # 每个未覆盖父体随机取一个子 ASIN
            results: List[str] = []
            for p in uncovered:
                children = [r["child"] for r in conn.execute(
                    "SELECT child FROM asin_parent_child WHERE batch_id = ? AND parent = ?",
                    (batch_id, p),
                ).fetchall()]
                results.append(random.choice(children))

            queried_at = _now_str()
            cur = conn.execute(
                "INSERT INTO asin_query_logs "
                "(queried_at, batch_id, input_count, result_count, "
                " input_asins_json, result_asins_json, ignored_asins_json, created_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (queried_at, batch_id, len(asins), len(results),
                 json.dumps(asins, ensure_ascii=False),
                 json.dumps(results, ensure_ascii=False),
                 json.dumps(missing, ensure_ascii=False), operator),
            )
            log_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

        return {
            "log_id": log_id,
            "batch_id": batch_id,
            "batch_time": batch["imported_at"],
            "input_asins": asins,
            "matched_parents": matched_parents,
            "ignored_asins": missing,
            "result_asins": results,
        }

    # ================= 生成记录 =================

    @staticmethod
    def list_query_logs(limit: int = 50) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT q.*, b.imported_at AS batch_time "
            "FROM asin_query_logs q LEFT JOIN asin_import_batches b ON b.id = q.batch_id "
            "ORDER BY q.id DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        ).fetchall()
        conn.close()
        logs = []
        for r in rows:
            d = dict(r)
            for k in ("input_asins_json", "result_asins_json", "ignored_asins_json"):
                d[k.replace("_json", "")] = _safe_json(d.pop(k, "[]"), [])
            logs.append(d)
        return logs

    # ================= 入库总览 =================

    @staticmethod
    def overview(search: str = "", page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """当前生效批次统计 + 父 ASIN 分页列表"""
        conn = get_db_connection()
        try:
            batch = AsinPoolService._latest_batch(conn)
            stats = {
                "batch_count": conn.execute(
                    "SELECT COUNT(*) FROM asin_import_batches").fetchone()[0],
                "total_pairs": conn.execute(
                    "SELECT COUNT(*) FROM asin_parent_child").fetchone()[0],
                "latest_batch": None,
                "parent_count": 0,
                "child_count": 0,
            }
            parents: List[Dict[str, Any]] = []
            total = 0
            if batch:
                bid = batch["id"]
                stats["latest_batch"] = {k: batch[k] for k in
                                         ("id", "imported_at", "filename", "pair_count", "parent_count")}
                stats["parent_count"] = conn.execute(
                    "SELECT COUNT(DISTINCT parent) FROM asin_parent_child WHERE batch_id = ?",
                    (bid,)).fetchone()[0]
                stats["child_count"] = conn.execute(
                    "SELECT COUNT(DISTINCT child) FROM asin_parent_child WHERE batch_id = ?",
                    (bid,)).fetchone()[0]

                like = f"%{search.strip().upper()}%" if search and search.strip() else None
                if like:
                    total = conn.execute(
                        "SELECT COUNT(*) FROM (SELECT parent FROM asin_parent_child "
                        "WHERE batch_id = ? AND parent LIKE ? GROUP BY parent)",
                        (bid, like)).fetchone()[0]
                    rows = conn.execute(
                        "SELECT parent, COUNT(*) AS child_count, "
                        "SUM(CASE WHEN child = parent THEN 1 ELSE 0 END) AS self_count "
                        "FROM asin_parent_child WHERE batch_id = ? AND parent LIKE ? "
                        "GROUP BY parent ORDER BY parent LIMIT ? OFFSET ?",
                        (bid, like, page_size, (page - 1) * page_size)).fetchall()
                else:
                    total = stats["parent_count"]
                    rows = conn.execute(
                        "SELECT parent, COUNT(*) AS child_count, "
                        "SUM(CASE WHEN child = parent THEN 1 ELSE 0 END) AS self_count "
                        "FROM asin_parent_child WHERE batch_id = ? "
                        "GROUP BY parent ORDER BY parent LIMIT ? OFFSET ?",
                        (bid, page_size, (page - 1) * page_size)).fetchall()
                for r in rows:
                    d = dict(r)
                    # 独立商品: 仅 1 个子且子=父
                    d["is_standalone"] = (d["child_count"] == 1 and (d["self_count"] or 0) == 1)
                    d.pop("self_count", None)
                    parents.append(d)
        finally:
            conn.close()

        return {
            "stats": stats,
            "parents": parents,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @staticmethod
    def list_children(parent: str, batch_id: Optional[int] = None) -> Dict[str, Any]:
        """查看某父 ASIN 下的全部子 ASIN"""
        parent = (parent or "").strip().upper()
        if not parent:
            raise ValueError("父 ASIN 不能为空")
        conn = get_db_connection()
        try:
            if not batch_id:
                batch = AsinPoolService._latest_batch(conn)
                if not batch:
                    raise ValueError("ASIN 池为空")
                batch_id = batch["id"]
            rows = conn.execute(
                "SELECT child FROM asin_parent_child WHERE batch_id = ? AND parent = ? ORDER BY child",
                (batch_id, parent)).fetchall()
        finally:
            conn.close()
        return {"parent": parent, "batch_id": batch_id,
                "children": [r["child"] for r in rows]}

    # ================= Excel 模板 =================

    @staticmethod
    def build_template() -> bytes:
        """生成导入模板 (两列: 父ASIN / ASIN, 附两行示例)"""
        wb = Workbook()
        ws = wb.active
        ws.title = "在线产品"
        ws.append(["父ASIN", "ASIN"])
        ws.append(["B0EXAMPLE01", "B0EXAMPLE01"])
        ws.append(["B0EXAMPLE01", "B0EXAMPLE02"])
        for col, width in (("A", 16), ("B", 16)):
            ws.column_dimensions[col].width = width
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()


def _safe_json(text: str, default):
    try:
        return json.loads(text) if text else default
    except Exception:
        return default
