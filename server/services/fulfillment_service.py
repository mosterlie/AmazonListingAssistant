"""
履约中心 · 业务服务

独立数据体系 (fm_*), 与现有订单模块隔离:
- fm_orders / fm_packages / fm_order_packages: 订单逐步跟踪与包裹自动匹配
- fm_purchase_orders + 明细/付款/订单关联: 国内采购单 (采购单截图、转账凭证)
- fm_tax_certs: 清关报税独立管理
- fm_invoices + 明细/关联: 发票管理 (订单/包裹/采购单/未关联)
- fm_documents: 各类资料统一存储

数据来源: 从妙手订单缓存 miaoshou_orders 只读导入, 不改动原表与原页面。
"""
import io
import json
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, UploadFile

from server.database import get_db_connection
from server.services.fulfillment_doc_service import (
    FM_DOC_CATEGORIES,
    FM_DOC_CATEGORY_MAP,
    FulfillmentDocService,
)
from server.services.fulfillment_parse_service import (
    parse_invoice_bytes,
    parse_purchase_order,
    parse_transfer_voucher,
)

FM_OWNER_TABLES = {
    "order": "fm_orders",
    "package": "fm_packages",
    "purchase_order": "fm_purchase_orders",
    "tax_cert": "fm_tax_certs",
    "invoice": "fm_invoices",
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_json(text: Any, default):
    try:
        return json.loads(text) if text else default
    except (TypeError, ValueError):
        return default


def _clean(value: Any, limit: int = 200) -> str:
    return str(value or "").strip()[:limit]


# 终态订单: 履约工作台默认不展示 (已关闭 / 已退还)
CLOSED_ORDER_STATUSES = ("cancelled", "returned")


def _remove_doc_files(docs: List[Dict[str, Any]]) -> None:
    """删除附件原文件与首页快照 (数据库由各自调用方清理)"""
    for doc in docs or []:
        folder = os.path.dirname(FulfillmentDocService.get_doc_path(doc))
        for name in (doc.get("stored_name"), doc.get("thumb_name")):
            if not name:
                continue
            try:
                path = os.path.join(folder, name)
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass


class FulfillmentService:
    """履约中心业务层"""

    # ═══════════════════════ 妙手同步 / 订单跟踪 ═══════════════════════

    @staticmethod
    def sync_from_miaoshou(days: int = 7, order_sn: str = "", pull: bool = False,
                           username: str = "") -> Dict[str, Any]:
        """从妙手同步订单/包裹到独立表

        pull=True 时先调用现有订单同步服务刷新妙手缓存 (复用原逻辑, 不影响原页面)。
        导入按 (platform, shop_id, order_sn) 合并订单, 按 source_package_id 合并包裹,
        自动建立多对多关联。
        """
        pull_result, pull_error = None, ""
        if pull:
            try:
                from server.services.order_service import OrderService
                pull_result = OrderService.sync_orders(days=max(int(days or 7), 1))
            except Exception as exc:
                pull_error = str(exc)

        where, params = [], []
        if order_sn:
            where.append("order_sn = ?")
            params.append(order_sn)
        elif days and int(days) > 0:
            cutoff = (datetime.now() - timedelta(days=int(days))).strftime("%Y-%m-%d 00:00:00")
            where.append("(gmt_order = '' OR gmt_order >= ?)")
            params.append(cutoff)
        sql = "SELECT * FROM miaoshou_orders"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY gmt_order DESC LIMIT 20000"

        conn = get_db_connection()
        stats = {"orders": 0, "packages": 0, "links": 0, "unlinked": 0,
                 "source_rows": 0, "pull": pull_result, "pull_error": pull_error}
        order_ids_seen = set()
        try:
            rows = conn.execute(sql, params).fetchall()
            stats["source_rows"] = len(rows)
            sync_time = _now()
            for row in rows:
                order_sn_val = _clean(row["order_sn"], 80)
                if not order_sn_val:
                    stats["unlinked"] += 1
                    continue
                platform = _clean(row["platform"], 32)
                shop_id = _clean(row["shop_id"], 64)
                conn.execute("""
                    INSERT INTO fm_orders (platform, shop_id, shop_name, order_sn, currency,
                        order_amount, pay_amount, order_status, order_status_text, gmt_order,
                        gmt_pay, dest_country, dest_country_name, receiver_state,
                        items_count, items_json, raw_json, source_row_id, sync_time, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(platform, shop_id, order_sn) DO UPDATE SET
                        shop_name = CASE WHEN excluded.shop_name <> '' THEN excluded.shop_name ELSE fm_orders.shop_name END,
                        currency = CASE WHEN excluded.currency <> '' THEN excluded.currency ELSE fm_orders.currency END,
                        order_amount = CASE WHEN excluded.order_amount > 0 THEN excluded.order_amount ELSE fm_orders.order_amount END,
                        pay_amount = CASE WHEN excluded.pay_amount > 0 THEN excluded.pay_amount ELSE fm_orders.pay_amount END,
                        order_status = CASE WHEN excluded.order_status <> '' THEN excluded.order_status ELSE fm_orders.order_status END,
                        order_status_text = CASE WHEN excluded.order_status_text <> '' THEN excluded.order_status_text ELSE fm_orders.order_status_text END,
                        gmt_order = CASE WHEN excluded.gmt_order <> '' THEN excluded.gmt_order ELSE fm_orders.gmt_order END,
                        gmt_pay = CASE WHEN excluded.gmt_pay <> '' THEN excluded.gmt_pay ELSE fm_orders.gmt_pay END,
                        dest_country = CASE WHEN excluded.dest_country <> '' THEN excluded.dest_country ELSE fm_orders.dest_country END,
                        dest_country_name = CASE WHEN excluded.dest_country_name <> '' THEN excluded.dest_country_name ELSE fm_orders.dest_country_name END,
                        receiver_state = CASE WHEN excluded.receiver_state <> '' THEN excluded.receiver_state ELSE fm_orders.receiver_state END,
                        items_count = CASE WHEN excluded.items_count > 0 THEN excluded.items_count ELSE fm_orders.items_count END,
                        items_json = CASE WHEN excluded.items_json NOT IN ('', '[]') THEN excluded.items_json ELSE fm_orders.items_json END,
                        raw_json = CASE WHEN excluded.raw_json NOT IN ('', '{}') THEN excluded.raw_json ELSE fm_orders.raw_json END,
                        source_row_id = excluded.source_row_id,
                        sync_time = excluded.sync_time,
                        updated_at = CURRENT_TIMESTAMP;
                """, (
                    platform, shop_id, _clean(row["shop_name"], 120), order_sn_val,
                    _clean(row["currency"], 12), float(row["order_amount"] or 0),
                    float(row["pay_amount"] or 0), _clean(row["order_status"], 40),
                    _clean(row["order_status_text"], 80), _clean(row["gmt_order"], 40),
                    _clean(row["gmt_pay"], 40), _clean(row["dest_country"], 20),
                    _clean(row["dest_country_name"], 80), _clean(row["receiver_state"], 80),
                    int(row["items_count"] or 0), row["items_json"] or "[]",
                    (row["raw_json"] if "raw_json" in row.keys() else "{}") or "{}",
                    int(row["id"] or 0), sync_time,
                ))
                order_row = conn.execute(
                    "SELECT id FROM fm_orders WHERE platform = ? AND shop_id = ? AND order_sn = ?",
                    (platform, shop_id, order_sn_val)).fetchone()
                order_id = order_row["id"]
                order_ids_seen.add(order_id)

                source_pkg = _clean(row["package_id"], 80)
                if not source_pkg:
                    stats["unlinked"] += 1
                    continue
                conn.execute("""
                    INSERT INTO fm_packages (source_package_id, app_package_no, order_sn,
                        package_status, package_status_text, tracking_no, tracking_company,
                        gmt_delivery, gmt_last_delivery, dest_country, track_status_name,
                        track_desc, track_time, items_count, items_json, source_row_id,
                        sync_time, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(source_package_id) DO UPDATE SET
                        app_package_no = CASE WHEN excluded.app_package_no <> '' THEN excluded.app_package_no ELSE fm_packages.app_package_no END,
                        order_sn = CASE WHEN excluded.order_sn <> '' THEN excluded.order_sn ELSE fm_packages.order_sn END,
                        package_status = CASE WHEN excluded.package_status <> '' THEN excluded.package_status ELSE fm_packages.package_status END,
                        package_status_text = CASE WHEN excluded.package_status_text <> '' THEN excluded.package_status_text ELSE fm_packages.package_status_text END,
                        tracking_no = CASE WHEN excluded.tracking_no <> '' THEN excluded.tracking_no ELSE fm_packages.tracking_no END,
                        tracking_company = CASE WHEN excluded.tracking_company <> '' THEN excluded.tracking_company ELSE fm_packages.tracking_company END,
                        gmt_delivery = CASE WHEN excluded.gmt_delivery <> '' THEN excluded.gmt_delivery ELSE fm_packages.gmt_delivery END,
                        gmt_last_delivery = CASE WHEN excluded.gmt_last_delivery <> '' THEN excluded.gmt_last_delivery ELSE fm_packages.gmt_last_delivery END,
                        dest_country = CASE WHEN excluded.dest_country <> '' THEN excluded.dest_country ELSE fm_packages.dest_country END,
                        track_status_name = CASE WHEN excluded.track_status_name <> '' THEN excluded.track_status_name ELSE fm_packages.track_status_name END,
                        track_desc = CASE WHEN excluded.track_desc <> '' THEN excluded.track_desc ELSE fm_packages.track_desc END,
                        track_time = CASE WHEN excluded.track_time <> '' THEN excluded.track_time ELSE fm_packages.track_time END,
                        items_count = CASE WHEN excluded.items_count > 0 THEN excluded.items_count ELSE fm_packages.items_count END,
                        items_json = CASE WHEN excluded.items_json NOT IN ('', '[]') THEN excluded.items_json ELSE fm_packages.items_json END,
                        source_row_id = excluded.source_row_id,
                        sync_time = excluded.sync_time,
                        updated_at = CURRENT_TIMESTAMP;
                """, (
                    source_pkg, _clean(row["app_package_no"], 80), order_sn_val,
                    _clean(row["package_status"], 40), _clean(row["package_status_text"], 80),
                    _clean(row["tracking_no"], 120), _clean(row["tracking_company"], 80),
                    _clean(row["gmt_delivery"], 40), _clean(row["gmt_last_delivery"], 40),
                    _clean(row["dest_country"], 20), _clean(row["track_status_name"], 80),
                    _clean(row["track_desc"], 300), _clean(row["track_time"], 40),
                    int(row["items_count"] or 0), row["items_json"] or "[]",
                    int(row["id"] or 0), sync_time,
                ))
                pkg_row = conn.execute(
                    "SELECT id FROM fm_packages WHERE source_package_id = ?", (source_pkg,)).fetchone()
                package_id = pkg_row["id"]
                stats["packages"] += 1
                before = conn.total_changes
                conn.execute("""
                    INSERT INTO fm_order_packages (order_id, package_id, link_source)
                    VALUES (?, ?, 'miaoshou')
                    ON CONFLICT(order_id, package_id) DO NOTHING;
                """, (order_id, package_id))
                if conn.total_changes > before:
                    stats["links"] += 1
            conn.commit()
        finally:
            conn.close()
        stats["orders"] = len(order_ids_seen)
        # 商品标识自动翻译: 复用订单管理页的大模型识别 (仅处理尚无标识的订单)
        try:
            from server.services.order_service import OrderService
            labeled = OrderService.tag_missing_product_labels()
            stats["labeled"] = int((labeled or {}).get("tagged") or 0)
        except Exception as exc:                       # 模型不可用不影响同步结果
            stats["labeled"] = 0
            stats["label_error"] = str(exc)[:200]
        return stats

    @staticmethod
    def _product_labels(pairs: List[Tuple[int, str]]) -> Dict[str, Dict[str, str]]:
        """批量取订单管理页已用大模型识别出的中文商品标识。

        履约订单与 miaoshou_orders 通过 source_row_id 对应 (兜底用 order_sn),
        直接复用订单侧结果, 避免重复调用模型。
        返回 {"id:<来源行id>": {"label": 完整标识, "short": 简版}, "sn:<订单号>": ...}
        """
        src_ids = sorted({int(s) for s, _ in pairs if s})
        sns = sorted({str(sn).strip() for _, sn in pairs if str(sn or "").strip()})
        if not src_ids and not sns:
            return {}
        rows = []
        conn = get_db_connection()
        try:
            for i in range(0, len(src_ids), 400):
                chunk = src_ids[i:i + 400]
                marks = ",".join("?" * len(chunk))
                rows += conn.execute(
                    f"SELECT id, order_sn, product_label, product_label_short "
                    f"FROM miaoshou_orders WHERE id IN ({marks})", chunk).fetchall()
            hit = {(r["order_sn"] or "") for r in rows}
            rest = [s for s in sns if s not in hit]
            for i in range(0, len(rest), 400):
                chunk = rest[i:i + 400]
                marks = ",".join("?" * len(chunk))
                rows += conn.execute(
                    f"SELECT id, order_sn, product_label, product_label_short "
                    f"FROM miaoshou_orders WHERE order_sn IN ({marks})", chunk).fetchall()
        finally:
            conn.close()
        out: Dict[str, Dict[str, str]] = {}
        for r in rows:
            label = (r["product_label"] or "").strip()
            if not label:
                continue
            item = {"label": label,
                    "short": (r["product_label_short"] or "").strip() or label[:5]}
            out[f"id:{int(r['id'])}"] = item
            if r["order_sn"]:
                out.setdefault(f"sn:{r['order_sn']}", item)
        return out

    @staticmethod
    def list_orders(keyword: str = "", page: int = 1, page_size: int = 20,
                    status: str = "", shop: str = "", shop_id: str = "",
                    date_from: str = "", date_to: str = "",
                    include_closed: bool = False) -> Dict[str, Any]:
        where, params = [], []
        if keyword:
            where.append("(order_sn LIKE ? OR shop_name LIKE ? OR dest_country_name LIKE ?)")
            like = f"%{keyword.strip()}%"
            params += [like, like, like]
        if status:
            where.append("order_status = ?")
            params.append(status)
        elif not include_closed:
            # 默认不展示终态订单: 已关闭 / 已退还
            marks = ",".join("?" * len(CLOSED_ORDER_STATUSES))
            where.append(f"IFNULL(order_status, '') NOT IN ({marks})")
            params.extend(CLOSED_ORDER_STATUSES)
        if shop or shop_id:
            where.append("shop_name = ?")
            params.append(shop or shop_id)
        if date_from:
            where.append("gmt_order >= ?")
            params.append(date_from)
        if date_to:
            where.append("gmt_order <= ?")
            params.append(date_to + " 23:59:59")
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        conn = get_db_connection()
        try:
            total = conn.execute(f"SELECT COUNT(1) c FROM fm_orders{clause}", params).fetchone()["c"]
            offset = (max(page, 1) - 1) * page_size
            rows = conn.execute(
                f"SELECT * FROM fm_orders{clause} ORDER BY gmt_order DESC, id DESC LIMIT ? OFFSET ?",
                params + [page_size, offset]).fetchall()
            orders = [dict(r) for r in rows]
            FulfillmentService._enrich_orders(conn, orders)
        finally:
            conn.close()
        for o in orders:
            o["items"] = _safe_json(o.get("items_json"), [])

        # 与订单管理页同构: 包裹 / 运单 / 商品首图 / 素材份数
        ids = [int(o["id"]) for o in orders]
        pkg_map: Dict[int, List[Dict[str, Any]]] = {}
        tail_map: Dict[str, List[str]] = {}
        if ids:
            conn = get_db_connection()
            try:
                marks = ",".join("?" * len(ids))
                for r in conn.execute(f"""
                    SELECT op.order_id AS oid, p.id AS pid, p.app_package_no, p.tracking_no,
                           p.tracking_company, p.package_status, p.package_status_text,
                           p.track_status_name, p.track_desc, p.track_time, p.gmt_delivery,
                           p.dest_country, p.source_package_id
                    FROM fm_order_packages op
                    JOIN fm_packages p ON p.id = op.package_id
                    WHERE op.order_id IN ({marks})
                    ORDER BY p.id
                """, ids):
                    pkg_map.setdefault(int(r["oid"]), []).append(dict(r))
                # 合单: 同运单号的其他履约订单
                tails = sorted({(p.get("tracking_no") or "").strip()
                                for arr in pkg_map.values() for p in arr
                                if (p.get("tracking_no") or "").strip()})
                if tails:
                    for i in range(0, len(tails), 400):
                        chunk = tails[i:i + 400]
                        mk = ",".join("?" * len(chunk))
                        for r in conn.execute(f"""
                            SELECT o.id, o.order_sn, p.tracking_no
                            FROM fm_orders o
                            JOIN fm_order_packages op ON op.order_id = o.id
                            JOIN fm_packages p ON p.id = op.package_id
                            WHERE p.tracking_no IN ({mk})
                        """, chunk):
                            tail_map.setdefault((r["tracking_no"] or "").strip(), []).append(
                                {"id": int(r["id"]), "order_sn": r["order_sn"] or ""})
            finally:
                conn.close()

        mats = FulfillmentService.materials_summary(
            [int(o["source_row_id"] or 0) for o in orders if int(o["source_row_id"] or 0)],
            [o["order_sn"] for o in orders if o.get("order_sn")])
        # 中文商品标识: 复用订单管理页大模型识别结果 (没有时回退英文标题)
        label_map = FulfillmentService._product_labels(
            [(int(o.get("source_row_id") or 0), o.get("order_sn") or "") for o in orders])

        for o in orders:
            src = int(o.get("source_row_id") or 0)
            info = mats.get(str(src)) or mats.get("sn:" + (o.get("order_sn") or "")) or {}
            o["fm_order_id"] = int(o["id"])
            o["src_id"] = src
            o["fm_docs"] = (info.get("counts") or {}) if info else {}
            o["fm_doc_previews"] = (info.get("previews") or {}) if info else {}
            o["docs"] = {}                       # 订单管理同构占位 (履约不使用 order_docs)
            pkgs = pkg_map.get(int(o["id"]), [])
            o["packages"] = pkgs
            first = pkgs[0] if pkgs else {}
            o["tracking_no"] = first.get("tracking_no", "")
            o["tracking_company"] = first.get("tracking_company", "")
            o["track_status_name"] = first.get("track_status_name", "")
            o["track_desc"] = first.get("track_desc", "")
            o["track_time"] = first.get("track_time", "")
            o["package_status"] = first.get("package_status", "")
            o["package_status_text"] = first.get("package_status_text", "")
            o["app_package_no"] = first.get("app_package_no", "")
            o["gmt_delivery"] = first.get("gmt_delivery", "")
            o["track_refreshed_at"] = o.get("sync_time", "")
            # 合单标记
            tail = (o.get("tracking_no") or "").strip()
            others = [g["order_sn"] for g in tail_map.get(tail, [])
                      if g["id"] != int(o["id"]) and g["order_sn"]]
            o["merged_orders"] = others
            o["merged_count"] = len(others)
            # 商品首图 / SKU / 商品标识
            items = o.get("items") or []
            it = items[0] if items else {}
            o["cover_img"] = it.get("picUrl") or it.get("originalPicUrl") or ""
            o["cover_img_big"] = it.get("originalPicUrl") or o["cover_img"]
            o["sku"] = (it.get("platformOuterSkuId") or it.get("platformItemId")
                        or it.get("platformSkuId") or it.get("sku") or "")
            title = it.get("title") or it.get("name") or it.get("productName") or ""
            o["item_title"] = title
            labels = (label_map.get(f"id:{src}")
                      or label_map.get(f"sn:{o.get('order_sn') or ''}") or {})
            if labels:
                o["product_label"] = labels["label"]
                o["product_label_short"] = labels["short"]
            else:
                o["product_label"] = title
                o["product_label_short"] = (title[:20] + "…") if len(title) > 20 else title
            o["purchase_date"] = o.get("purchase_date") or ""
            o["domestic_package_count"] = int(o.get("domestic_package_count") or 0)
            o["domestic_tracking_no"] = o.get("domestic_tracking_no") or ""
            # 原始报文: 复制整行取收货人/备注, 保证不依赖订单模块
            o["raw"] = _safe_json(o.get("raw_json"), {})

        pages = (int(total) + int(page_size) - 1) // int(page_size) if total else 0
        return {"items": orders, "total": total, "page": page,
                "page_size": page_size, "pages": pages}

    @staticmethod
    def get_order_supplement(order_id: int) -> Dict[str, Any]:
        conn = get_db_connection()
        try:
            row = conn.execute("""
                SELECT id, order_sn, purchase_date, domestic_package_count, domestic_tracking_no
                FROM fm_orders WHERE id = ?
            """, (order_id,)).fetchone()
        finally:
            conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="履约订单不存在")
        return dict(row)

    @staticmethod
    def save_order_supplement(order_id: int, purchase_date: str = "",
                              domestic_package_count: int = 0,
                              domestic_tracking_no: str = "") -> Dict[str, Any]:
        conn = get_db_connection()
        try:
            cur = conn.execute("""
                UPDATE fm_orders SET purchase_date = ?, domestic_package_count = ?,
                    domestic_tracking_no = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (_clean(purchase_date, 40), int(domestic_package_count or 0),
                  _clean(domestic_tracking_no, 200), order_id))
            conn.commit()
            if not cur.rowcount:
                raise HTTPException(status_code=404, detail="履约订单不存在")
        finally:
            conn.close()
        return FulfillmentService.get_order_supplement(order_id)

    @staticmethod
    def materials_summary(order_ids: List[int] = None,
                          order_sns: List[str] = None) -> Dict[str, Any]:
        """按妙手订单 id / 订单号汇总履约素材数量, 供工作台列表图标展示。

        返回 {"<miaoshou_order_id>": {"fm_order_id": 12, "counts": {category: n}}}
        """
        ids = [int(i) for i in (order_ids or []) if int(i or 0) > 0]
        sns = [str(s).strip() for s in (order_sns or []) if str(s).strip()]
        if not ids and not sns:
            return {}
        conn = get_db_connection()
        try:
            rows = []
            if ids:
                marks = ",".join("?" * len(ids))
                rows = conn.execute(
                    f"SELECT id, source_row_id, order_sn FROM fm_orders WHERE source_row_id IN ({marks})",
                    ids).fetchall()
            found_sn = {(r["order_sn"] or "") for r in rows}
            rest = [s for s in sns if s not in found_sn]
            if rest:
                for i in range(0, len(rest), 300):
                    chunk = rest[i:i + 300]
                    marks = ",".join("?" * len(chunk))
                    rows += conn.execute(
                        f"SELECT id, source_row_id, order_sn FROM fm_orders WHERE order_sn IN ({marks})",
                        chunk).fetchall()
            if not rows:
                return {}
            by_source = {}
            by_sn = {}
            fm_ids = []
            for r in rows:
                fm_ids.append(int(r["id"]))
                if r["source_row_id"]:
                    by_source[int(r["source_row_id"])] = int(r["id"])
                if r["order_sn"]:
                    by_sn[r["order_sn"]] = int(r["id"])
            counts = {fid: {} for fid in fm_ids}
            previews = {fid: {} for fid in fm_ids}

            def bump(oid, key, n):
                if oid in counts and n:
                    counts[oid][key] = counts[oid].get(key, 0) + int(n)

            def doc_url(r) -> str:
                """文档可预览地址: 图片取原图, 其它取缩略图 (与 FulfillmentDocService 一致)"""
                base = f"/uploads/fulfillment/{r['otype']}/{int(r['oid2'])}"
                if str(r["mime"] or "").lower().startswith("image/"):
                    return f"{base}/{r['sname']}" if r["sname"] else ""
                return f"{base}/{r['tname']}" if r["tname"] else ""

            def add_preview(oid, key, r, limit: int = 2):
                """每单每类最多保留 limit 张快照, 供列表直接展示"""
                bucket = previews.get(oid, {}).setdefault(key, []) if oid in previews else None
                if bucket is None or len(bucket) >= limit:
                    return
                url = doc_url(r)
                if not url:
                    return
                bucket.append({"doc_id": int(r["did"]), "category": key,
                               "file_name": r["fname"] or "", "url": url})

            marks = ",".join("?" * len(fm_ids))
            # 采购单截图 / 转账凭证 (挂在采购单上, 采购单关联订单)
            for r in conn.execute(f"""
                SELECT poo.order_id oid, d.category cat, COUNT(1) c
                FROM fm_documents d
                JOIN fm_purchase_order_orders poo ON poo.purchase_order_id = d.owner_id
                WHERE d.owner_type = 'purchase_order'
                  AND d.category IN ('purchase_order_shot', 'transfer_voucher')
                  AND poo.order_id IN ({marks})
                GROUP BY poo.order_id, d.category
            """, fm_ids):
                bump(r["oid"], r["cat"], r["c"])
            # 发货单 / 签收单 (挂在包裹上)
            for r in conn.execute(f"""
                SELECT op.order_id oid, d.category cat, COUNT(1) c
                FROM fm_documents d
                JOIN fm_order_packages op ON op.package_id = d.owner_id
                WHERE d.owner_type = 'package'
                  AND d.category IN ('delivery_note', 'receipt')
                  AND op.order_id IN ({marks})
                GROUP BY op.order_id, d.category
            """, fm_ids):
                bump(r["oid"], r["cat"], r["c"])
            # 发票: 采购单发票 / 货代(物流)发票, 按发票挂靠对象与发票类型区分
            for r in conn.execute(f"""
                SELECT poo.order_id oid, i.invoice_kind kind, COUNT(DISTINCT d.id) c
                FROM fm_invoice_links l
                JOIN fm_invoices i ON i.id = l.invoice_id
                JOIN fm_documents d ON d.owner_type = 'invoice' AND d.owner_id = l.invoice_id
                JOIN fm_purchase_order_orders poo ON poo.purchase_order_id = l.owner_id
                WHERE l.owner_type = 'purchase_order' AND poo.order_id IN ({marks})
                GROUP BY poo.order_id, i.invoice_kind
            """, fm_ids):
                # 挂在采购单上的发票统一算采购发票 (类型以挂靠对象为准)
                bump(r["oid"], "invoice_purchase", r["c"])
            for r in conn.execute(f"""
                SELECT op.order_id oid, i.invoice_kind kind, COUNT(DISTINCT d.id) c
                FROM fm_invoice_links l
                JOIN fm_invoices i ON i.id = l.invoice_id
                JOIN fm_documents d ON d.owner_type = 'invoice' AND d.owner_id = l.invoice_id
                JOIN fm_order_packages op ON op.package_id = l.owner_id
                WHERE l.owner_type = 'package' AND op.order_id IN ({marks})
                GROUP BY op.order_id, i.invoice_kind
            """, fm_ids):
                # 挂在包裹上的发票统一算货代(物流)发票
                bump(r["oid"], "invoice_forwarder", r["c"])
            # 清关报税
            for r in conn.execute(f"""
                SELECT tc.order_id oid, COUNT(1) c
                FROM fm_documents d
                JOIN fm_tax_certs tc ON tc.id = d.owner_id
                WHERE d.owner_type = 'tax_cert' AND d.category = 'tax_cert'
                  AND tc.order_id IN ({marks})
                GROUP BY tc.order_id
            """, fm_ids):
                bump(r["oid"], "tax_cert", r["c"])

            # ── 列表快照: 每类取最新 3 份可预览的文档 ──
            def sweep(sql: str, key_of):
                for r in conn.execute(sql, fm_ids):
                    add_preview(r["oid"], key_of(r), r)

            # 采购单截图 / 转账凭证 (采购单归属)
            sweep(f"""
                SELECT poo.order_id oid, d.id did, d.category cat, d.file_name fname,
                       d.stored_name sname, d.thumb_name tname, d.mime_type mime,
                       d.owner_type otype, d.owner_id oid2, '' kind
                FROM fm_documents d
                JOIN fm_purchase_order_orders poo ON poo.purchase_order_id = d.owner_id
                WHERE d.owner_type = 'purchase_order'
                  AND d.category IN ('purchase_order_shot', 'transfer_voucher')
                  AND poo.order_id IN ({marks})
                ORDER BY d.id DESC
            """, lambda r: r["cat"])
            # 发货单 / 签收单 (包裹归属)
            sweep(f"""
                SELECT op.order_id oid, d.id did, d.category cat, d.file_name fname,
                       d.stored_name sname, d.thumb_name tname, d.mime_type mime,
                       d.owner_type otype, d.owner_id oid2, '' kind
                FROM fm_documents d
                JOIN fm_order_packages op ON op.package_id = d.owner_id
                WHERE d.owner_type = 'package'
                  AND d.category IN ('delivery_note', 'receipt')
                  AND op.order_id IN ({marks})
                ORDER BY d.id DESC
            """, lambda r: r["cat"])
            # 发票 (挂在采购单上的)
            sweep(f"""
                SELECT poo.order_id oid, d.id did, d.category cat, d.file_name fname,
                       d.stored_name sname, d.thumb_name tname, d.mime_type mime,
                       d.owner_type otype, d.owner_id oid2, COALESCE(i.invoice_kind, '') kind
                FROM fm_invoice_links l
                JOIN fm_invoices i ON i.id = l.invoice_id
                JOIN fm_documents d ON d.owner_type = 'invoice' AND d.owner_id = l.invoice_id
                                   AND d.category = 'invoice'
                JOIN fm_purchase_order_orders poo ON poo.purchase_order_id = l.owner_id
                WHERE l.owner_type = 'purchase_order' AND poo.order_id IN ({marks})
                ORDER BY d.id DESC
            """, lambda r: "invoice_purchase")
            # 发票 (挂在包裹上的)
            sweep(f"""
                SELECT op.order_id oid, d.id did, d.category cat, d.file_name fname,
                       d.stored_name sname, d.thumb_name tname, d.mime_type mime,
                       d.owner_type otype, d.owner_id oid2, COALESCE(i.invoice_kind, '') kind
                FROM fm_invoice_links l
                JOIN fm_invoices i ON i.id = l.invoice_id
                JOIN fm_documents d ON d.owner_type = 'invoice' AND d.owner_id = l.invoice_id
                                   AND d.category = 'invoice'
                JOIN fm_order_packages op ON op.package_id = l.owner_id
                WHERE l.owner_type = 'package' AND op.order_id IN ({marks})
                ORDER BY d.id DESC
            """, lambda r: "invoice_forwarder")
            # 清关报税
            sweep(f"""
                SELECT tc.order_id oid, d.id did, d.category cat, d.file_name fname,
                       d.stored_name sname, d.thumb_name tname, d.mime_type mime,
                       d.owner_type otype, d.owner_id oid2, '' kind
                FROM fm_documents d
                JOIN fm_tax_certs tc ON tc.id = d.owner_id
                WHERE d.owner_type = 'tax_cert' AND d.category = 'tax_cert'
                  AND tc.order_id IN ({marks})
                ORDER BY d.id DESC
            """, lambda r: r["cat"])
        finally:
            conn.close()

        out = {}
        for source_id, fid in by_source.items():
            out[str(source_id)] = {"fm_order_id": fid, "counts": counts.get(fid, {}),
                                   "previews": previews.get(fid, {})}
        for sn, fid in by_sn.items():
            out.setdefault("sn:" + sn, {"fm_order_id": fid, "counts": counts.get(fid, {}),
                                        "previews": previews.get(fid, {})})
        return out

    @staticmethod
    def list_order_filters() -> Dict[str, Any]:
        """工作台筛选下拉选项: 订单状态 + 店铺 (按出现量排序)"""
        conn = get_db_connection()
        try:
            status_rows = conn.execute("""
                SELECT order_status AS code, MAX(order_status_text) AS text, COUNT(1) c
                FROM fm_orders WHERE order_status <> ''
                GROUP BY order_status ORDER BY c DESC
            """).fetchall()
            shop_rows = conn.execute("""
                SELECT shop_name, COUNT(1) c FROM fm_orders WHERE shop_name <> ''
                GROUP BY shop_name ORDER BY c DESC LIMIT 80
            """).fetchall()
        finally:
            conn.close()
        return {
            "statuses": [{"code": r["code"], "text": r["text"] or r["code"],
                          "count": r["c"]} for r in status_rows],
            "shops": [r["shop_name"] for r in shop_rows],
        }

    @staticmethod
    def _enrich_orders(conn, orders: List[Dict[str, Any]]) -> None:
        if not orders:
            return
        ids = [o["id"] for o in orders]
        marks = ",".join("?" * len(ids))
        pkg_rows = conn.execute(f"""
            SELECT op.order_id, p.id, p.app_package_no, p.tracking_no, p.package_status,
                   p.package_status_text, p.track_status_name, p.gmt_delivery
            FROM fm_order_packages op JOIN fm_packages p ON p.id = op.package_id
            WHERE op.order_id IN ({marks}) ORDER BY p.id ASC
        """, ids).fetchall()
        pkg_map: Dict[int, List[Dict[str, Any]]] = {}
        for r in pkg_rows:
            pkg_map.setdefault(r["order_id"], []).append(dict(r))
        po_rows = conn.execute(
            f"SELECT order_id, COUNT(1) c FROM fm_purchase_order_orders WHERE order_id IN ({marks}) "
            f"GROUP BY order_id", ids).fetchall()
        po_map = {r["order_id"]: r["c"] for r in po_rows}
        tax_rows = conn.execute(
            f"SELECT order_id, COUNT(1) c FROM fm_tax_certs WHERE order_id IN ({marks}) "
            f"GROUP BY order_id", ids).fetchall()
        tax_map = {r["order_id"]: r["c"] for r in tax_rows}
        inv_map = FulfillmentService._invoice_ids_by_order(conn, ids)
        for o in orders:
            pkgs = pkg_map.get(o["id"], [])
            o["packages"] = pkgs
            o["package_count"] = len(pkgs)
            o["tracking_numbers"] = [p["tracking_no"] for p in pkgs if p.get("tracking_no")]
            o["purchase_order_count"] = po_map.get(o["id"], 0)
            o["tax_cert_count"] = tax_map.get(o["id"], 0)
            o["invoice_count"] = len(inv_map.get(o["id"], set()))

    @staticmethod
    def _invoice_ids_by_order(conn, order_ids: List[int]) -> Dict[int, set]:
        """订单可见发票: 直接关联 + 通过包裹关联 + 通过采购单关联"""
        if not order_ids:
            return {}
        marks = ",".join("?" * len(order_ids))
        pkg_rows = conn.execute(
            f"SELECT order_id, package_id FROM fm_order_packages WHERE order_id IN ({marks})",
            order_ids).fetchall()
        po_rows = conn.execute(
            f"SELECT order_id, purchase_order_id FROM fm_purchase_order_orders WHERE order_id IN ({marks})",
            order_ids).fetchall()
        order_set = {int(i) for i in order_ids}
        pkg_to_orders: Dict[int, List[int]] = {}
        for r in pkg_rows:
            pkg_to_orders.setdefault(r["package_id"], []).append(r["order_id"])
        po_to_orders: Dict[int, List[int]] = {}
        for r in po_rows:
            po_to_orders.setdefault(r["purchase_order_id"], []).append(r["order_id"])

        result: Dict[int, set] = {int(i): set() for i in order_ids}
        direct = conn.execute(
            f"SELECT invoice_id, owner_id FROM fm_invoice_links WHERE owner_type = 'order' "
            f"AND owner_id IN ({marks})", order_ids).fetchall()
        for r in direct:
            result.setdefault(r["owner_id"], set()).add(r["invoice_id"])
        if pkg_to_orders:
            pm = ",".join("?" * len(pkg_to_orders))
            rows = conn.execute(
                f"SELECT invoice_id, owner_id FROM fm_invoice_links WHERE owner_type = 'package' "
                f"AND owner_id IN ({pm})", list(pkg_to_orders.keys())).fetchall()
            for r in rows:
                for oid in pkg_to_orders.get(r["owner_id"], []):
                    result.setdefault(oid, set()).add(r["invoice_id"])
        if po_to_orders:
            pm = ",".join("?" * len(po_to_orders))
            rows = conn.execute(
                f"SELECT invoice_id, owner_id FROM fm_invoice_links WHERE owner_type = 'purchase_order' "
                f"AND owner_id IN ({pm})", list(po_to_orders.keys())).fetchall()
            for r in rows:
                for oid in po_to_orders.get(r["owner_id"], []):
                    result.setdefault(oid, set()).add(r["invoice_id"])
        return result

    @staticmethod
    def get_order_workspace(order_id: int) -> Dict[str, Any]:
        conn = get_db_connection()
        try:
            row = conn.execute("SELECT * FROM fm_orders WHERE id = ?", (int(order_id),)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="订单不存在")
            order = dict(row)
            order["items"] = _safe_json(order.get("items_json"), [])
            # 中文商品标识: 与列表保持一致, 复用订单管理页大模型识别结果
            src_id = int(order.get("source_row_id") or 0)
            order_sn_val = order.get("order_sn") or ""
            labels = FulfillmentService._product_labels([(src_id, order_sn_val)])
            lab = labels.get(f"id:{src_id}") or labels.get(f"sn:{order_sn_val}") or {}
            first_item = order["items"][0] if order["items"] else {}
            raw_title = (first_item.get("title") or first_item.get("name")
                         or first_item.get("productName") or "")
            order["item_title"] = raw_title
            order["product_label"] = lab.get("label") or raw_title
            order["product_label_short"] = lab.get("short") or (
                (raw_title[:20] + "…") if len(raw_title) > 20 else raw_title)

            pkg_rows = conn.execute("""
                SELECT p.* FROM fm_order_packages op JOIN fm_packages p ON p.id = op.package_id
                WHERE op.order_id = ? ORDER BY p.gmt_delivery DESC, p.id DESC
            """, (int(order_id),)).fetchall()
            packages = [dict(r) for r in pkg_rows]
            pkg_order_map: Dict[int, List[Dict[str, Any]]] = {}
            if packages:
                pids = [p["id"] for p in packages]
                marks = ",".join("?" * len(pids))
                link_rows = conn.execute(f"""
                    SELECT op.package_id, o.id, o.order_sn, o.shop_name
                    FROM fm_order_packages op JOIN fm_orders o ON o.id = op.order_id
                    WHERE op.package_id IN ({marks}) ORDER BY o.id
                """, pids).fetchall()
                for r in link_rows:
                    pkg_order_map.setdefault(r["package_id"], []).append(dict(r))

            po_rows = conn.execute("""
                SELECT po.*, poo.allocated_amount FROM fm_purchase_order_orders poo
                JOIN fm_purchase_orders po ON po.id = poo.purchase_order_id
                WHERE poo.order_id = ? ORDER BY po.id DESC
            """, (int(order_id),)).fetchall()
            purchase_orders = [dict(r) for r in po_rows]

            tax_rows = conn.execute(
                "SELECT * FROM fm_tax_certs WHERE order_id = ? ORDER BY id DESC",
                (int(order_id),)).fetchall()
            tax_certs = [dict(r) for r in tax_rows]

            invoice_ids = sorted(FulfillmentService._invoice_ids_by_order(conn, [int(order_id)])
                                 .get(int(order_id), set()), reverse=True)
            invoices = [FulfillmentService._invoice_full(conn, i, with_items=True) for i in invoice_ids]
        finally:
            conn.close()

        for p in packages:
            p["items"] = _safe_json(p.get("items_json"), [])
            p["orders"] = pkg_order_map.get(p["id"], [])
            p["documents"] = FulfillmentDocService.list_docs("package", p["id"])
            p["doc_counts"] = FulfillmentDocService.count_docs("package", [p["id"]]).get(p["id"], {})
        for po in purchase_orders:
            po["documents"] = FulfillmentDocService.list_docs("purchase_order", po["id"])
            po["doc_counts"] = FulfillmentDocService.count_docs("purchase_order", [po["id"]]).get(po["id"], {})
            po["items"] = FulfillmentService._purchase_items(po["id"])
            po["payments"] = FulfillmentService._purchase_payments(po["id"])
            po["invoices"] = [inv for inv in invoices
                              if any(l["owner_type"] == "purchase_order" and l["owner_id"] == po["id"]
                                     for l in inv.get("links", []))]
        for tc in tax_certs:
            tc["documents"] = FulfillmentDocService.list_docs("tax_cert", tc["id"])

        return {
            "order": order,
            "packages": packages,
            "purchase_orders": purchase_orders,
            "tax_certs": tax_certs,
            "invoices": invoices,
            "summary": {
                "package_count": len(packages),
                "purchase_order_count": len(purchase_orders),
                "invoice_count": len(invoices),
                "tax_cert_count": len(tax_certs),
                "document_count": sum(len(p["documents"]) for p in packages)
                + sum(len(p["documents"]) for p in purchase_orders)
                + sum(len(t["documents"]) for t in tax_certs)
                + sum(len(i.get("documents", [])) for i in invoices),
            },
            "categories": FM_DOC_CATEGORIES,
        }

    # ═══════════════════════ 包裹 ═══════════════════════

    @staticmethod
    def list_packages(keyword: str = "", page: int = 1, page_size: int = 20,
                      include_closed: bool = False) -> Dict[str, Any]:
        where, params = [], []
        if keyword:
            where.append("(p.tracking_no LIKE ? OR p.app_package_no LIKE ? OR p.source_package_id LIKE ?)")
            like = f"%{keyword.strip()}%"
            params += [like, like, like]
        if not include_closed:
            # 包裹列表默认不展示已关闭包裹
            where.append("IFNULL(p.package_status, '') <> 'cancelled'")
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        conn = get_db_connection()
        try:
            total = conn.execute(f"SELECT COUNT(1) c FROM fm_packages p{clause}", params).fetchone()["c"]
            offset = (max(page, 1) - 1) * page_size
            rows = conn.execute(
                f"SELECT p.* FROM fm_packages p{clause} ORDER BY p.id DESC LIMIT ? OFFSET ?",
                params + [page_size, offset]).fetchall()
            packages = [dict(r) for r in rows]
            ids = [p["id"] for p in packages]
            order_map: Dict[int, List[Dict[str, Any]]] = {}
            if ids:
                marks = ",".join("?" * len(ids))
                link_rows = conn.execute(f"""
                    SELECT op.package_id, o.id, o.order_sn, o.shop_name
                    FROM fm_order_packages op JOIN fm_orders o ON o.id = op.order_id
                    WHERE op.package_id IN ({marks}) ORDER BY o.id ASC
                """, ids).fetchall()
                for r in link_rows:
                    order_map.setdefault(r["package_id"], []).append(dict(r))
            doc_counts = FulfillmentDocService.count_docs("package", ids)
            inv_map = {}
            if ids:
                marks = ",".join("?" * len(ids))
                inv_rows = conn.execute(
                    f"SELECT invoice_id, owner_id FROM fm_invoice_links "
                    f"WHERE owner_type = 'package' AND owner_id IN ({marks})", ids).fetchall()
                for r in inv_rows:
                    inv_map.setdefault(r["owner_id"], set()).add(r["invoice_id"])
        finally:
            conn.close()
        for p in packages:
            p["orders"] = order_map.get(p["id"], [])
            p["order_count"] = len(p["orders"])
            p["documents"] = FulfillmentDocService.list_docs("package", p["id"])
            p["doc_counts"] = doc_counts.get(p["id"], {})
            p["invoice_count"] = len(inv_map.get(p["id"], set()))
            p["items"] = _safe_json(p.get("items_json"), [])
        return {"items": packages, "total": total, "page": page, "page_size": page_size}

    @staticmethod
    def link_package_orders(package_id: int, order_ids: List[int]) -> Dict[str, Any]:
        """人工补充包裹与订单的多对多关联 (合单/补关联)"""
        conn = get_db_connection()
        added = 0
        try:
            if not conn.execute("SELECT 1 FROM fm_packages WHERE id = ?", (int(package_id),)).fetchone():
                raise HTTPException(status_code=404, detail="包裹不存在")
            for oid in order_ids:
                if not conn.execute("SELECT 1 FROM fm_orders WHERE id = ?", (int(oid),)).fetchone():
                    continue
                before = conn.total_changes
                conn.execute("""
                    INSERT INTO fm_order_packages (order_id, package_id, link_source)
                    VALUES (?, ?, 'manual') ON CONFLICT(order_id, package_id) DO NOTHING;
                """, (int(oid), int(package_id)))
                if conn.total_changes > before:
                    added += 1
            conn.commit()
        finally:
            conn.close()
        return {"added": added}

    @staticmethod
    def unlink_package_order(package_id: int, order_id: int) -> Dict[str, Any]:
        conn = get_db_connection()
        try:
            conn.execute(
                "DELETE FROM fm_order_packages WHERE package_id = ? AND order_id = ?",
                (int(package_id), int(order_id)))
            conn.commit()
        finally:
            conn.close()
        return {"package_id": int(package_id), "order_id": int(order_id)}

    # ═══════════════════════ 国内采购单 ═══════════════════════

    @staticmethod
    def _purchase_items(po_id: int) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM fm_purchase_order_items WHERE purchase_order_id = ? ORDER BY sort_order, id",
                (int(po_id),)).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def _purchase_payments(po_id: int) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM fm_purchase_payments WHERE purchase_order_id = ? ORDER BY id DESC",
                (int(po_id),)).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def list_purchase_orders(keyword: str = "", page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        where, params = [], []
        if keyword:
            where.append("(po.purchase_no LIKE ? OR po.supplier_name LIKE ? OR po.note LIKE ?)")
            like = f"%{keyword.strip()}%"
            params += [like, like, like]
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        conn = get_db_connection()
        try:
            total = conn.execute(
                f"SELECT COUNT(1) c FROM fm_purchase_orders po{clause}", params).fetchone()["c"]
            offset = (max(page, 1) - 1) * page_size
            rows = conn.execute(
                f"SELECT po.* FROM fm_purchase_orders po{clause} ORDER BY po.id DESC LIMIT ? OFFSET ?",
                params + [page_size, offset]).fetchall()
            orders = [dict(r) for r in rows]
            ids = [o["id"] for o in orders]
            link_map: Dict[int, List[Dict[str, Any]]] = {}
            inv_map: Dict[int, List[Dict[str, Any]]] = {}
            pay_map: Dict[int, float] = {}
            if ids:
                marks = ",".join("?" * len(ids))
                link_rows = conn.execute(f"""
                    SELECT poo.purchase_order_id, o.id, o.order_sn, o.shop_name
                    FROM fm_purchase_order_orders poo JOIN fm_orders o ON o.id = poo.order_id
                    WHERE poo.purchase_order_id IN ({marks})
                """, ids).fetchall()
                for r in link_rows:
                    link_map.setdefault(r["purchase_order_id"], []).append(dict(r))
                inv_rows = conn.execute(f"""
                    SELECT l.owner_id po_id, i.id, i.invoice_kind, i.invoice_number,
                           i.total_amount, i.currency, i.invoice_date
                    FROM fm_invoice_links l
                    JOIN fm_invoices i ON i.id = l.invoice_id
                    WHERE l.owner_type = 'purchase_order' AND l.owner_id IN ({marks})
                    ORDER BY i.id DESC
                """, ids).fetchall()
                for r in inv_rows:
                    inv_map.setdefault(r["po_id"], []).append(dict(r))
                pay_rows = conn.execute(
                    f"SELECT purchase_order_id, SUM(amount) s FROM fm_purchase_payments "
                    f"WHERE purchase_order_id IN ({marks}) GROUP BY purchase_order_id", ids).fetchall()
                pay_map = {r["purchase_order_id"]: float(r["s"] or 0) for r in pay_rows}
        finally:
            conn.close()
        for po in orders:
            po["orders"] = link_map.get(po["id"], [])
            po["invoices"] = inv_map.get(po["id"], [])
            po["invoice_count"] = len(po["invoices"])
            po["paid_amount"] = pay_map.get(po["id"], 0.0)
            po["documents"] = FulfillmentDocService.list_docs("purchase_order", po["id"])
            po["doc_counts"] = FulfillmentDocService.count_docs("purchase_order", [po["id"]]).get(po["id"], {})
            po["items"] = FulfillmentService._purchase_items(po["id"])
            po["payments"] = FulfillmentService._purchase_payments(po["id"])
        return {"items": orders, "total": total, "page": page, "page_size": page_size}

    @staticmethod
    def get_purchase_order(po_id: int) -> Dict[str, Any]:
        conn = get_db_connection()
        try:
            row = conn.execute("SELECT * FROM fm_purchase_orders WHERE id = ?", (int(po_id),)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="采购单不存在")
            po = dict(row)
            link_rows = conn.execute("""
                SELECT o.id, o.order_sn, o.shop_name, poo.allocated_amount
                FROM fm_purchase_order_orders poo JOIN fm_orders o ON o.id = poo.order_id
                WHERE poo.purchase_order_id = ?
            """, (int(po_id),)).fetchall()
            inv_rows = conn.execute("""
                SELECT i.* FROM fm_invoice_links l JOIN fm_invoices i ON i.id = l.invoice_id
                WHERE l.owner_type = 'purchase_order' AND l.owner_id = ?
                ORDER BY i.id DESC
            """, (int(po_id),)).fetchall()
        finally:
            conn.close()
        po["orders"] = [dict(r) for r in link_rows]
        po["items"] = FulfillmentService._purchase_items(po_id)
        po["payments"] = FulfillmentService._purchase_payments(po_id)
        po["documents"] = FulfillmentDocService.list_docs("purchase_order", po_id)
        po["doc_counts"] = FulfillmentDocService.count_docs("purchase_order", [po_id]).get(po_id, {})
        # 该采购单对应的发票 (含发票原件), 与素材一起展示
        po["invoices"] = [dict(r) for r in inv_rows]
        for inv in po["invoices"]:
            inv["documents"] = FulfillmentDocService.list_docs("invoice", inv["id"])
        return po

    @staticmethod
    def create_purchase_order(payload: Dict[str, Any], username: str = "") -> Dict[str, Any]:
        conn = get_db_connection()
        try:
            cur = conn.execute("""
                INSERT INTO fm_purchase_orders (purchase_no, supplier_name, purchase_date, currency,
                    total_amount, status, payment_status, source, note, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                _clean(payload.get("purchase_no"), 80),
                _clean(payload.get("supplier_name"), 120),
                _clean(payload.get("purchase_date"), 40),
                _clean(payload.get("currency"), 12).upper() or "CNY",
                float(payload.get("total_amount") or 0),
                _clean(payload.get("status"), 40) or "待付款",
                _clean(payload.get("payment_status"), 40) or "未付款",
                _clean(payload.get("source"), 20) or "manual",
                _clean(payload.get("note"), 500),
                username or "",
            ))
            po_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        return FulfillmentService.get_purchase_order(po_id)

    @staticmethod
    def update_purchase_order(po_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        allowed = ["purchase_no", "supplier_name", "purchase_date", "currency", "total_amount",
                   "status", "payment_status", "note"]
        sets, params = [], []
        for key in allowed:
            if key not in payload:
                continue
            val = payload.get(key)
            if key == "total_amount":
                val = float(val or 0)
            else:
                val = _clean(val, 500)
            sets.append(f"{key} = ?")
            params.append(val)
        if not sets:
            raise HTTPException(status_code=400, detail="没有需要更新的字段")
        conn = get_db_connection()
        try:
            if not conn.execute("SELECT 1 FROM fm_purchase_orders WHERE id = ?", (int(po_id),)).fetchone():
                raise HTTPException(status_code=404, detail="采购单不存在")
            conn.execute(f"UPDATE fm_purchase_orders SET {', '.join(sets)}, updated_at = ? WHERE id = ?",
                         params + [_now(), int(po_id)])
            conn.commit()
        finally:
            conn.close()
        return FulfillmentService.get_purchase_order(po_id)

    @staticmethod
    def link_purchase_orders(po_id: int, order_ids: List[int]) -> Dict[str, Any]:
        conn = get_db_connection()
        added = 0
        try:
            if not conn.execute("SELECT 1 FROM fm_purchase_orders WHERE id = ?", (int(po_id),)).fetchone():
                raise HTTPException(status_code=404, detail="采购单不存在")
            for oid in order_ids:
                if not conn.execute("SELECT 1 FROM fm_orders WHERE id = ?", (int(oid),)).fetchone():
                    continue
                before = conn.total_changes
                conn.execute("""
                    INSERT INTO fm_purchase_order_orders (purchase_order_id, order_id)
                    VALUES (?, ?) ON CONFLICT(purchase_order_id, order_id) DO NOTHING;
                """, (int(po_id), int(oid)))
                if conn.total_changes > before:
                    added += 1
            conn.commit()
        finally:
            conn.close()
        return {"added": added, "purchase_order": FulfillmentService.get_purchase_order(po_id)}

    @staticmethod
    def unlink_purchase_order(po_id: int, order_id: int) -> Dict[str, Any]:
        conn = get_db_connection()
        try:
            conn.execute(
                "DELETE FROM fm_purchase_order_orders WHERE purchase_order_id = ? AND order_id = ?",
                (int(po_id), int(order_id)))
            conn.commit()
        finally:
            conn.close()
        return {"purchase_order": FulfillmentService.get_purchase_order(po_id)}

    @staticmethod
    def delete_purchase_order(po_id: int) -> Dict[str, Any]:
        conn = get_db_connection()
        try:
            inv = conn.execute(
                "SELECT COUNT(1) c FROM fm_invoice_links WHERE owner_type = 'purchase_order' AND owner_id = ?",
                (int(po_id),)).fetchone()["c"]
            if inv:
                raise HTTPException(status_code=400, detail="该采购单仍有关联发票，请先解除发票关联")
        finally:
            conn.close()
        _remove_doc_files(FulfillmentDocService.list_docs("purchase_order", po_id))
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM fm_documents WHERE owner_type = 'purchase_order' AND owner_id = ?", (int(po_id),))
            conn.execute("DELETE FROM fm_purchase_order_items WHERE purchase_order_id = ?", (int(po_id),))
            conn.execute("DELETE FROM fm_purchase_payments WHERE purchase_order_id = ?", (int(po_id),))
            conn.execute("DELETE FROM fm_purchase_order_orders WHERE purchase_order_id = ?", (int(po_id),))
            conn.execute("DELETE FROM fm_purchase_orders WHERE id = ?", (int(po_id),))
            conn.commit()
        finally:
            conn.close()
        return {"id": int(po_id)}

    # ═══════════════════════ 采购单资料与解析 ═══════════════════════

    @staticmethod
    def _apply_purchase_parsed(po_id: int, data: Dict[str, Any], raw_text: str = "") -> None:
        sets, params = [], []
        mapping = [
            ("purchase_no", _clean(data.get("purchase_no"), 80)),
            ("supplier_name", _clean(data.get("supplier_name"), 120)),
            ("purchase_date", _clean(data.get("purchase_date"), 40)),
            ("currency", _clean(data.get("currency"), 12).upper()),
        ]
        for key, val in mapping:
            if val:
                sets.append(f"{key} = ?")
                params.append(val)
        total = float(data.get("total_amount") or 0)
        if total:
            sets.append("total_amount = ?")
            params.append(total)
        remark = _clean(data.get("remark"), 500)
        if remark:
            sets.append("note = ?")
            params.append(remark)
        sets.append("parse_status = 'success'")
        sets.append("parse_error = ''")
        sets.append("raw_json = ?")
        params.append((raw_text or "")[:20000])
        conn = get_db_connection()
        try:
            conn.execute(f"UPDATE fm_purchase_orders SET {', '.join(sets)}, updated_at = ? WHERE id = ?",
                         params + [_now(), int(po_id)])
            items = data.get("items") or []
            if items:
                conn.execute("DELETE FROM fm_purchase_order_items WHERE purchase_order_id = ?", (int(po_id),))
                for idx, it in enumerate(items):
                    conn.execute("""
                        INSERT INTO fm_purchase_order_items (purchase_order_id, name, spec, unit,
                            quantity, unit_price, amount, sort_order)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (int(po_id), _clean(it.get("name"), 120), _clean(it.get("spec"), 80),
                          _clean(it.get("unit"), 20), float(it.get("quantity") or 0),
                          float(it.get("unit_price") or 0), float(it.get("amount") or 0), idx))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _apply_transfer_parsed(po_id: int, doc_id: int, data: Dict[str, Any], raw_text: str = "") -> None:
        conn = get_db_connection()
        try:
            exists = conn.execute(
                "SELECT id FROM fm_purchase_payments WHERE purchase_order_id = ? AND document_id = ?",
                (int(po_id), int(doc_id))).fetchone()
            values = (
                _clean(data.get("transaction_no"), 80), _clean(data.get("paid_at"), 40),
                float(data.get("amount") or 0), _clean(data.get("currency"), 12).upper(),
                _clean(data.get("payer"), 120), _clean(data.get("payee"), 120),
                _clean(data.get("method"), 40), _clean(data.get("remark"), 200),
                "success", "", (raw_text or "")[:20000], _now(), int(po_id), int(doc_id),
            )
            if exists:
                conn.execute("""
                    UPDATE fm_purchase_payments SET transaction_no = ?, paid_at = ?, amount = ?,
                        currency = ?, payer = ?, payee = ?, method = ?, note = ?, parse_status = ?,
                        parse_error = ?, raw_json = ?, updated_at = ? WHERE purchase_order_id = ? AND document_id = ?
                """, values)
            else:
                conn.execute("""
                    INSERT INTO fm_purchase_payments (transaction_no, paid_at, amount, currency,
                        payer, payee, method, note, parse_status, parse_error, raw_json,
                        updated_at, purchase_order_id, document_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, values)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _shim_upload(content: bytes, filename: str) -> SimpleNamespace:
        return SimpleNamespace(file=io.BytesIO(content), filename=filename,
                               content_type="application/octet-stream")

    @staticmethod
    def add_purchase_document(po_id: int, category: str, file: UploadFile,
                              username: str = "", auto_parse: bool = True) -> Dict[str, Any]:
        if category not in ("purchase_order_shot", "transfer_voucher", "other"):
            raise HTTPException(status_code=400, detail="采购单仅支持采购单截图/转账凭证/其他资料")
        payload = FulfillmentDocService.read_upload(file)
        document = FulfillmentDocService.save_bytes(
            "purchase_order", po_id, category, payload, username=username)
        warnings: List[str] = []
        if auto_parse and category in ("purchase_order_shot", "transfer_voucher"):
            try:
                if category == "purchase_order_shot":
                    parsed = parse_purchase_order(
                        FulfillmentService._shim_upload(payload["content"], payload["file_name"]),
                        username=username)
                    FulfillmentService._apply_purchase_parsed(po_id, parsed["data"], parsed.get("raw_text", ""))
                else:
                    parsed = parse_transfer_voucher(
                        FulfillmentService._shim_upload(payload["content"], payload["file_name"]),
                        username=username)
                    FulfillmentService._apply_transfer_parsed(
                        po_id, document["id"], parsed["data"], parsed.get("raw_text", ""))
            except HTTPException as exc:
                warnings.append(f"附件已保存，但自动解析失败: {exc.detail}")
                conn = get_db_connection()
                try:
                    conn.execute(
                        "UPDATE fm_purchase_orders SET parse_status = 'failed', parse_error = ?, updated_at = ? WHERE id = ?",
                        (str(exc.detail)[:500], _now(), int(po_id)))
                    conn.commit()
                finally:
                    conn.close()
        return {"document": document, "warnings": warnings,
                "purchase_order": FulfillmentService.get_purchase_order(po_id)}

    @staticmethod
    def import_transfer_voucher(file: UploadFile, order_id: int = 0,
                                purchase_order_id: int = 0, username: str = "") -> Dict[str, Any]:
        """上传转账凭证: 可指定采购单; 未指定时自动创建草稿采购单并关联订单"""
        payload = FulfillmentDocService.read_upload(file)
        po_id = int(purchase_order_id or 0)
        if po_id:
            FulfillmentService.get_purchase_order(po_id)
        else:
            po = FulfillmentService.create_purchase_order({
                "source": "parsed",
                "note": "由转账凭证自动建档，请补充采购单号与供应商",
                "status": "待付款",
                "payment_status": "部分付款",
            }, username=username)
            po_id = po["id"]
            if order_id:
                FulfillmentService.link_purchase_orders(po_id, [int(order_id)])
        document = FulfillmentDocService.save_bytes(
            "purchase_order", po_id, "transfer_voucher", payload, username=username)
        warnings: List[str] = []
        try:
            parsed = parse_transfer_voucher(
                FulfillmentService._shim_upload(payload["content"], payload["file_name"]),
                username=username)
            FulfillmentService._apply_transfer_parsed(
                po_id, document["id"], parsed["data"], parsed.get("raw_text", ""))
            # 有金额即视为已发生付款, 默认标记为部分付款, 由人工核对后改已付款
            if float(parsed["data"].get("amount") or 0) > 0:
                conn = get_db_connection()
                try:
                    conn.execute(
                        "UPDATE fm_purchase_orders SET payment_status = '部分付款', updated_at = ? WHERE id = ?",
                        (_now(), int(po_id)))
                    conn.commit()
                finally:
                    conn.close()
        except HTTPException as exc:
            warnings.append(f"转账凭证已保存，但自动解析失败: {exc.detail}")
            conn = get_db_connection()
            try:
                conn.execute(
                    "UPDATE fm_purchase_orders SET parse_status = 'failed', parse_error = ?, updated_at = ? WHERE id = ?",
                    (str(exc.detail)[:500], _now(), int(po_id)))
                conn.commit()
            finally:
                conn.close()
        return {"document": document, "warnings": warnings,
                "purchase_order": FulfillmentService.get_purchase_order(po_id)}

    @staticmethod
    def import_tax_cert(file: UploadFile, order_id: int = 0, username: str = "") -> Dict[str, Any]:
        """上传清关报税文件: 自动建档并归档到指定订单"""
        payload = FulfillmentDocService.read_upload(file)
        title = os.path.splitext(payload["file_name"])[0] or "清关报税"
        cert = FulfillmentService.create_tax_cert({
            "order_id": int(order_id or 0),
            "title": title,
            "cert_type": "清关报税",
            "note": "由统一上传创建",
        }, username=username)
        document = FulfillmentDocService.save_bytes(
            "tax_cert", cert["id"], "tax_cert", payload, username=username)
        return {"tax_cert": FulfillmentService.get_tax_cert(cert["id"]), "document": document}

    @staticmethod
    def _package_belongs_to_order(order_id: int, package_id: int) -> bool:
        conn = get_db_connection()
        try:
            return bool(conn.execute(
                "SELECT 1 FROM fm_order_packages WHERE order_id = ? AND package_id = ?",
                (int(order_id), int(package_id))).fetchone())
        finally:
            conn.close()

    @staticmethod
    def _purchase_belongs_to_order(order_id: int, po_id: int) -> bool:
        conn = get_db_connection()
        try:
            return bool(conn.execute(
                "SELECT 1 FROM fm_purchase_order_orders WHERE order_id = ? AND purchase_order_id = ?",
                (int(order_id), int(po_id))).fetchone())
        finally:
            conn.close()

    @staticmethod
    def batch_upload_materials(order_id: int, manifest: List[Dict[str, Any]],
                               files: List[UploadFile], username: str = "") -> Dict[str, Any]:
        """统一上传: 前端仅暂存文件, 提交后按清单逐项落库并解析

        manifest 每项: {file_index, category, target_type, target_id, invoice_kind}
        - purchase_order_shot: 每个文件自动创建一张采购单
        - transfer_voucher: 可指定 target_id=采购单; 为空则自动创建草稿采购单
        - invoice: target_type=order/package/purchase_order
        - delivery_note/receipt: target_type=package, 必须属于当前订单
        - tax_cert: 每个文件自动建档并归档到当前订单
        逐项处理, 单项失败不影响其他文件; 返回逐项结果供页面展示。
        """
        if not files:
            raise HTTPException(status_code=400, detail="未选择任何素材文件")
        if not manifest:
            raise HTTPException(status_code=400, detail="提交清单为空")
        conn = get_db_connection()
        try:
            if not conn.execute("SELECT 1 FROM fm_orders WHERE id = ?", (int(order_id),)).fetchone():
                raise HTTPException(status_code=404, detail="订单不存在")
        finally:
            conn.close()

        used_files = set()
        results: List[Dict[str, Any]] = []
        shot_po_id = 0        # 本批次采购单截图合并到同一张采购单
        voucher_po_id = 0     # 本批次无归属的转账凭证也合并到同一张采购单
        for idx, item in enumerate(manifest):
            file_index = int(item.get("file_index", -1))
            category = _clean(item.get("category"), 40)
            target_type = _clean(item.get("target_type"), 20)
            target_id = int(item.get("target_id") or 0)
            invoice_kind = _clean(item.get("invoice_kind"), 40)
            file_name = ""
            try:
                if file_index < 0 or file_index >= len(files):
                    raise HTTPException(status_code=400, detail="文件索引无效")
                if file_index in used_files:
                    raise HTTPException(status_code=400, detail="同一文件不能重复提交")
                used_files.add(file_index)
                upload = files[file_index]
                file_name = os.path.basename(upload.filename or "file")

                if category == "purchase_order_shot":
                    # 同一次提交的多张截图 = 同一张采购单: 第一张建单, 其余追加为附件
                    share_po = 0
                    if target_id:
                        if not FulfillmentService._purchase_belongs_to_order(order_id, target_id):
                            raise HTTPException(status_code=400, detail="所选采购单不属于当前订单")
                        share_po = target_id
                    else:
                        share_po = shot_po_id
                    res = FulfillmentService.import_purchase_order(
                        upload, order_id=order_id, username=username, po_id=share_po)
                    po = res["purchase_order"]
                    if not share_po:
                        shot_po_id = po["id"]
                    results.append({
                        "index": idx, "status": "success", "category": category,
                        "file_name": file_name, "target_type": "purchase_order",
                        "target_id": po["id"],
                        "message": ("已自动建档采购单 #%s" % po["id"]) if res.get("created")
                        else ("已合并为采购单 #%s 的截图" % po["id"]),
                    })
                    if res.get("warnings"):
                        results[-1]["message"] += "；" + "；".join(res["warnings"])
                    continue

                if category == "transfer_voucher":
                    # 归属优先级: 手动选择 > 本批次截图建的采购单 > 本批次首张凭证建的采购单
                    share_po = 0
                    if target_id:
                        if not FulfillmentService._purchase_belongs_to_order(order_id, target_id):
                            raise HTTPException(status_code=400, detail="所选采购单不属于当前订单")
                        share_po = target_id
                    else:
                        share_po = shot_po_id or voucher_po_id
                    if share_po:
                        res = FulfillmentService.add_purchase_document(
                            share_po, "transfer_voucher", upload,
                            username=username, auto_parse=True)
                        po = res["purchase_order"]
                    else:
                        res = FulfillmentService.import_transfer_voucher(
                            upload, order_id=order_id, username=username)
                        po = res["purchase_order"]
                        voucher_po_id = po["id"]
                    results.append({
                        "index": idx, "status": "success", "category": category,
                        "file_name": file_name, "target_type": "purchase_order",
                        "target_id": po["id"],
                        "message": "转账凭证已归档并解析" + ("；" + "；".join(res["warnings"]) if res.get("warnings") else ""),
                    })
                    continue

                if category == "invoice":
                    if target_type == "package":
                        if not FulfillmentService._package_belongs_to_order(order_id, target_id):
                            raise HTTPException(status_code=400, detail="所选包裹不属于当前订单")
                    elif target_type == "purchase_order":
                        if not target_id:
                            # 未录入采购单: 复用本批次已建的单, 否则自动生成一张
                            target_id = shot_po_id or voucher_po_id
                            if not target_id:
                                target_id = FulfillmentService._create_draft_purchase_order(
                                    order_id, username, "由补录发票自动建档")
                                voucher_po_id = target_id
                        elif not FulfillmentService._purchase_belongs_to_order(order_id, target_id):
                            raise HTTPException(status_code=400, detail="所选采购单不属于当前订单")
                    elif target_type != "order" or not target_id:
                        target_type, target_id = "order", order_id
                    res = FulfillmentService.create_invoice(
                        upload, owner_type=target_type, owner_id=target_id,
                        invoice_kind=invoice_kind, username=username, auto_parse=True)
                    inv = res["invoice"]
                    # 关联对象默认补上当前亚马逊订单, 订单维度也能直接看到这张发票
                    if target_type != "order":
                        try:
                            FulfillmentService._link_invoice(inv["id"], "order", order_id)
                        except HTTPException:
                            pass
                    results.append({
                        "index": idx, "status": "success", "category": category,
                        "file_name": file_name, "target_type": target_type,
                        "target_id": target_id, "target_id2": inv["id"],
                        "message": ("发票已保存并解析" if inv.get("parse_status") == "success" else "发票已保存，解析失败待人工修正")
                        + ("；" + "；".join(res["warnings"]) if res.get("warnings") else ""),
                    })
                    continue

                if category in ("delivery_note", "receipt"):
                    if target_type != "package" or not target_id:
                        raise HTTPException(status_code=400, detail="请选择要归档的包裹")
                    if not FulfillmentService._package_belongs_to_order(order_id, target_id):
                        raise HTTPException(status_code=400, detail="所选包裹不属于当前订单")
                    doc = FulfillmentDocService.save_upload(
                        "package", target_id, category, upload, username=username)
                    results.append({
                        "index": idx, "status": "success", "category": category,
                        "file_name": file_name, "target_type": "package",
                        "target_id": target_id,
                        "message": ("发货单" if category == "delivery_note" else "签收单") + "已归档",
                    })
                    continue

                if category == "tax_cert":
                    res = FulfillmentService.import_tax_cert(upload, order_id=order_id, username=username)
                    cert = res["tax_cert"]
                    results.append({
                        "index": idx, "status": "success", "category": category,
                        "file_name": file_name, "target_type": "tax_cert",
                        "target_id": cert["id"], "message": "清关报税已建档并归档",
                    })
                    continue

                raise HTTPException(status_code=400, detail=f"不支持的素材分类: {category}")
            except HTTPException as exc:
                results.append({
                    "index": idx, "status": "failed", "category": category,
                    "file_name": file_name, "message": str(exc.detail),
                })
            except Exception as exc:  # 单文件异常不影响其余素材
                results.append({
                    "index": idx, "status": "failed", "category": category,
                    "file_name": file_name, "message": str(exc),
                })

        success = len([r for r in results if r["status"] == "success"])
        return {
            "order_id": int(order_id),
            "total": len(results),
            "success": success,
            "failed": len(results) - success,
            "items": results,
        }

    @staticmethod
    def _create_draft_purchase_order(order_id: int = 0, username: str = "",
                                     note: str = "由补录素材自动建档") -> int:
        """未录入采购单时的兜底: 建一张草稿采购单并关联订单, 返回采购单 id"""
        conn = get_db_connection()
        try:
            cur = conn.execute("""
                INSERT INTO fm_purchase_orders (purchase_no, supplier_name, purchase_date, currency,
                    total_amount, status, payment_status, source, note, parse_status, created_by)
                VALUES ('', '', '', 'CNY', 0, '待付款', '未付款', 'parsed', ?, 'pending', ?)
            """, (note, username or ""))
            po_id = int(cur.lastrowid)
            if order_id:
                conn.execute("""
                    INSERT INTO fm_purchase_order_orders (purchase_order_id, order_id)
                    VALUES (?, ?) ON CONFLICT(purchase_order_id, order_id) DO NOTHING;
                """, (po_id, int(order_id)))
            conn.commit()
        finally:
            conn.close()
        return po_id

    @staticmethod
    def cleanup_purchase_order_if_empty(po_id: int) -> bool:
        """采购单下已无任何素材/明细/付款/发票关联时, 连同空壳采购单一并删除"""
        conn = get_db_connection()
        try:
            po_id = int(po_id)
            if not conn.execute("SELECT 1 FROM fm_purchase_orders WHERE id = ?", (po_id,)).fetchone():
                return False
            left = conn.execute(
                "SELECT (SELECT COUNT(1) FROM fm_documents WHERE owner_type = 'purchase_order' AND owner_id = ?)"
                " + (SELECT COUNT(1) FROM fm_purchase_order_items WHERE purchase_order_id = ?)"
                " + (SELECT COUNT(1) FROM fm_purchase_payments WHERE purchase_order_id = ?)"
                " + (SELECT COUNT(1) FROM fm_invoice_links WHERE owner_type = 'purchase_order' AND owner_id = ?)"
                " AS c", (po_id, po_id, po_id, po_id)).fetchone()["c"]
            if left:
                return False
            conn.execute("DELETE FROM fm_purchase_payments WHERE purchase_order_id = ?", (po_id,))
            conn.execute("DELETE FROM fm_purchase_order_items WHERE purchase_order_id = ?", (po_id,))
            conn.execute("DELETE FROM fm_purchase_order_orders WHERE purchase_order_id = ?", (po_id,))
            conn.execute("DELETE FROM fm_purchase_orders WHERE id = ?", (po_id,))
            conn.commit()
            return True
        finally:
            conn.close()

    @staticmethod
    def import_purchase_order(file: UploadFile, order_id: int = 0, username: str = "",
                              po_id: int = 0) -> Dict[str, Any]:
        """上传采购单截图 → 自动建档 (草稿) → 结构化解析 → 关联订单

        po_id > 0 时复用已有采购单 (同一批次的后续截图作为附件追加, 不重复建单)。
        """
        payload = FulfillmentDocService.read_upload(file)
        created = False
        if po_id:
            conn = get_db_connection()
            try:
                if not conn.execute("SELECT 1 FROM fm_purchase_orders WHERE id = ?",
                                    (int(po_id),)).fetchone():
                    raise HTTPException(status_code=404, detail="采购单不存在")
            finally:
                conn.close()
        else:
            po_id = FulfillmentService._create_draft_purchase_order(
                order_id, username, "由采购单截图自动建档")
            created = True

        document = FulfillmentDocService.save_bytes(
            "purchase_order", po_id, "purchase_order_shot", payload, username=username)
        warnings: List[str] = []
        try:
            parsed = parse_purchase_order(
                FulfillmentService._shim_upload(payload["content"], payload["file_name"]),
                username=username)
            FulfillmentService._apply_purchase_parsed(po_id, parsed["data"], parsed.get("raw_text", ""))
        except HTTPException as exc:
            warnings.append(f"采购单已建档并保留截图，但自动解析失败: {exc.detail}")
            conn = get_db_connection()
            try:
                conn.execute(
                    "UPDATE fm_purchase_orders SET parse_status = 'failed', parse_error = ?, updated_at = ? WHERE id = ?",
                    (str(exc.detail)[:500], _now(), int(po_id)))
                conn.commit()
            finally:
                conn.close()
        return {"document": document, "warnings": warnings, "created": created,
                "purchase_order": FulfillmentService.get_purchase_order(po_id)}

    # ═══════════════════════ 清关报税 ═══════════════════════

    @staticmethod
    def list_tax_certs(keyword: str = "", page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        where, params = [], []
        if keyword:
            where.append("(tc.title LIKE ? OR tc.cert_no LIKE ? OR tc.note LIKE ?)")
            like = f"%{keyword.strip()}%"
            params += [like, like, like]
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        conn = get_db_connection()
        try:
            total = conn.execute(f"SELECT COUNT(1) c FROM fm_tax_certs tc{clause}", params).fetchone()["c"]
            offset = (max(page, 1) - 1) * page_size
            rows = conn.execute(f"""
                SELECT tc.*, o.order_sn FROM fm_tax_certs tc
                LEFT JOIN fm_orders o ON o.id = tc.order_id
                {clause} ORDER BY tc.id DESC LIMIT ? OFFSET ?
            """, params + [page_size, offset]).fetchall()
            certs = [dict(r) for r in rows]
            # 默认带出亚马逊订单对应的包裹运单号
            track_map = FulfillmentService._tax_cert_tracking(
                conn, [int(c["order_id"]) for c in certs if int(c.get("order_id") or 0) > 0])
        finally:
            conn.close()
        for c in certs:
            c["tracking_nos"] = track_map.get(int(c.get("order_id") or 0), "")
            c["documents"] = FulfillmentDocService.list_docs("tax_cert", c["id"])
            c["doc_counts"] = FulfillmentDocService.count_docs("tax_cert", [c["id"]]).get(c["id"], {})
        return {"items": certs, "total": total, "page": page, "page_size": page_size}

    @staticmethod
    def _tax_cert_tracking(conn, order_ids: List[int]) -> Dict[int, str]:
        """订单 → 包裹运单号 (多个用英文逗号拼接), 供清关报税展示"""
        ids = sorted({int(i) for i in order_ids if int(i or 0) > 0})
        if not ids:
            return {}
        out: Dict[int, str] = {}
        marks = ",".join("?" * len(ids))
        for r in conn.execute(f"""
            SELECT op.order_id oid, GROUP_CONCAT(DISTINCT p.tracking_no) nos
            FROM fm_order_packages op
            JOIN fm_packages p ON p.id = op.package_id
            WHERE op.order_id IN ({marks}) AND IFNULL(p.tracking_no, '') <> ''
            GROUP BY op.order_id
        """, ids):
            out[int(r["oid"])] = r["nos"] or ""
        return out

    @staticmethod
    def get_tax_cert(cert_id: int) -> Dict[str, Any]:
        conn = get_db_connection()
        try:
            row = conn.execute("""
                SELECT tc.*, o.order_sn FROM fm_tax_certs tc
                LEFT JOIN fm_orders o ON o.id = tc.order_id WHERE tc.id = ?
            """, (int(cert_id),)).fetchone()
        finally:
            conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="清关报税不存在")
        cert = dict(row)
        cert["tracking_nos"] = ""
        if int(cert.get("order_id") or 0):
            conn = get_db_connection()
            try:
                cert["tracking_nos"] = FulfillmentService._tax_cert_tracking(
                    conn, [int(cert["order_id"])]).get(int(cert["order_id"]), "")
            finally:
                conn.close()
        cert["documents"] = FulfillmentDocService.list_docs("tax_cert", cert_id)
        return cert

    @staticmethod
    def create_tax_cert(payload: Dict[str, Any], username: str = "") -> Dict[str, Any]:
        conn = get_db_connection()
        try:
            cur = conn.execute("""
                INSERT INTO fm_tax_certs (order_id, title, cert_no, cert_type, tax_period, country,
                    amount, currency, issued_date, note, status, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                int(payload.get("order_id") or 0),
                _clean(payload.get("title"), 160) or "清关报税",
                _clean(payload.get("cert_no"), 80),
                _clean(payload.get("cert_type"), 80),
                _clean(payload.get("tax_period"), 80),
                _clean(payload.get("country"), 60),
                float(payload.get("amount") or 0),
                _clean(payload.get("currency"), 12).upper() or "CNY",
                _clean(payload.get("issued_date"), 40),
                _clean(payload.get("note"), 500),
                _clean(payload.get("status"), 40) or "已归档",
                username or "",
            ))
            cert_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        return FulfillmentService.get_tax_cert(cert_id)

    @staticmethod
    def update_tax_cert(cert_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        allowed = ["order_id", "title", "cert_no", "cert_type", "tax_period", "country",
                   "amount", "currency", "issued_date", "note", "status"]
        sets, params = [], []
        for key in allowed:
            if key not in payload:
                continue
            val = payload[key]
            if key == "order_id":
                val = int(val or 0)
            elif key == "amount":
                val = float(val or 0)
            else:
                val = _clean(val, 500)
            sets.append(f"{key} = ?")
            params.append(val)
        if not sets:
            raise HTTPException(status_code=400, detail="没有需要更新的字段")
        conn = get_db_connection()
        try:
            conn.execute(f"UPDATE fm_tax_certs SET {', '.join(sets)}, updated_at = ? WHERE id = ?",
                         params + [_now(), int(cert_id)])
            conn.commit()
        finally:
            conn.close()
        return FulfillmentService.get_tax_cert(cert_id)

    @staticmethod
    def delete_tax_cert(cert_id: int) -> Dict[str, Any]:
        _remove_doc_files(FulfillmentDocService.list_docs("tax_cert", cert_id))
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM fm_documents WHERE owner_type = 'tax_cert' AND owner_id = ?", (int(cert_id),))
            conn.execute("DELETE FROM fm_tax_certs WHERE id = ?", (int(cert_id),))
            conn.commit()
        finally:
            conn.close()
        return {"id": int(cert_id)}

    # ═══════════════════════ 发票 ═══════════════════════

    @staticmethod
    def _invoice_links(conn, invoice_id: int) -> List[Dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM fm_invoice_links WHERE invoice_id = ? ORDER BY id", (int(invoice_id),)).fetchall()
        links = [dict(r) for r in rows]
        for link in links:
            label = ""
            if link["owner_type"] == "order":
                r = conn.execute("SELECT order_sn FROM fm_orders WHERE id = ?", (link["owner_id"],)).fetchone()
                label = f"订单 {r['order_sn']}" if r else "订单已删除"
            elif link["owner_type"] == "package":
                r = conn.execute(
                    "SELECT app_package_no, tracking_no FROM fm_packages WHERE id = ?",
                    (link["owner_id"],)).fetchone()
                label = f"包裹 {r['app_package_no'] or r['tracking_no'] or link['owner_id']}" if r else "包裹已删除"
            elif link["owner_type"] == "purchase_order":
                r = conn.execute(
                    "SELECT purchase_no, supplier_name FROM fm_purchase_orders WHERE id = ?",
                    (link["owner_id"],)).fetchone()
                label = f"采购单 {r['purchase_no'] or r['supplier_name'] or link['owner_id']}" if r else "采购单已删除"
            link["owner_label"] = label
        return links

    @staticmethod
    def _invoice_full(conn, invoice_id: int, with_items: bool = True) -> Dict[str, Any]:
        row = conn.execute("SELECT * FROM fm_invoices WHERE id = ?", (int(invoice_id),)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="发票不存在")
        inv = dict(row)
        inv["verified"] = bool(inv.get("verified"))
        inv["links"] = FulfillmentService._invoice_links(conn, invoice_id)
        if with_items:
            items = conn.execute(
                "SELECT * FROM fm_invoice_items WHERE invoice_id = ? ORDER BY sort_order, id",
                (int(invoice_id),)).fetchall()
            inv["items"] = [dict(i) for i in items]
        inv["documents"] = FulfillmentDocService.list_docs("invoice", invoice_id)
        return inv

    @staticmethod
    def list_invoices(keyword: str = "", parse_status: str = "", page: int = 1,
                      page_size: int = 20) -> Dict[str, Any]:
        where, params = [], []
        if keyword:
            where.append("(invoice_number LIKE ? OR invoice_code LIKE ? OR seller_name LIKE ? "
                         "OR buyer_name LIKE ? OR remark LIKE ?)")
            like = f"%{keyword.strip()}%"
            params += [like, like, like, like, like]
        if parse_status:
            where.append("parse_status = ?")
            params.append(parse_status)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        conn = get_db_connection()
        try:
            total = conn.execute(f"SELECT COUNT(1) c FROM fm_invoices{clause}", params).fetchone()["c"]
            offset = (max(page, 1) - 1) * page_size
            rows = conn.execute(
                f"SELECT * FROM fm_invoices{clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [page_size, offset]).fetchall()
            invoices = [FulfillmentService._invoice_full(conn, r["id"]) for r in rows]
        finally:
            conn.close()
        return {"items": invoices, "total": total, "page": page, "page_size": page_size}

    @staticmethod
    def get_invoice(invoice_id: int) -> Dict[str, Any]:
        conn = get_db_connection()
        try:
            return FulfillmentService._invoice_full(conn, invoice_id)
        finally:
            conn.close()

    @staticmethod
    def _link_invoice(invoice_id: int, owner_type: str, owner_id: int,
                      allocated_amount: float = 0) -> None:
        if owner_type not in ("order", "package", "purchase_order"):
            raise HTTPException(status_code=400, detail="发票只能关联订单/包裹/采购单")
        if not FulfillmentDocService.owner_exists(owner_type, owner_id):
            raise HTTPException(status_code=404, detail="发票关联对象不存在")
        conn = get_db_connection()
        try:
            conn.execute("""
                INSERT INTO fm_invoice_links (invoice_id, owner_type, owner_id, allocated_amount)
                VALUES (?, ?, ?, ?) ON CONFLICT(invoice_id, owner_type, owner_id) DO NOTHING;
            """, (int(invoice_id), owner_type, int(owner_id), float(allocated_amount or 0)))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _apply_invoice_parsed(invoice_id: int, parsed: Dict[str, Any],
                              keep_kind: bool = False) -> None:
        inv = parsed.get("invoice") or {}
        conn = get_db_connection()
        try:
            conn.execute("""
                UPDATE fm_invoices SET invoice_kind = CASE WHEN ? = 1 THEN invoice_kind
                        ELSE COALESCE(NULLIF(?, ''), invoice_kind, '其他发票') END,
                    invoice_code = ?, invoice_number = ?, invoice_date = ?, seller_name = ?,
                    seller_tax_id = ?, buyer_name = ?, buyer_tax_id = ?, currency = ?,
                    amount_excl_tax = ?, tax_amount = ?, total_amount = ?, total_in_words = ?,
                    remark = ?, parse_status = 'success', parse_error = '', raw_json = ?, model = ?,
                    updated_at = ? WHERE id = ?
            """, (
                1 if keep_kind else 0, _clean(inv.get("doc_type"), 40),
                _clean(inv.get("invoice_code"), 60), _clean(inv.get("invoice_number"), 60),
                _clean(inv.get("invoice_date"), 40), _clean(inv.get("seller_name"), 120),
                _clean(inv.get("seller_tax_id"), 60), _clean(inv.get("buyer_name"), 120),
                _clean(inv.get("buyer_tax_id"), 60), _clean(inv.get("currency"), 12).upper(),
                float(inv.get("amount_excl_tax") or 0), float(inv.get("tax_amount") or 0),
                float(inv.get("total_amount") or 0), _clean(inv.get("total_in_words"), 120),
                _clean(inv.get("remark"), 500),
                (parsed.get("raw_text") or "")[:20000], _clean(parsed.get("model"), 80),
                _now(), int(invoice_id)))
            conn.execute("DELETE FROM fm_invoice_items WHERE invoice_id = ?", (int(invoice_id),))
            for idx, it in enumerate(parsed.get("items") or []):
                conn.execute("""
                    INSERT INTO fm_invoice_items (invoice_id, name, spec, unit, quantity,
                        unit_price, amount, tax_rate, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (int(invoice_id), _clean(it.get("name"), 120), _clean(it.get("spec"), 80),
                      _clean(it.get("unit"), 20), float(it.get("quantity") or 0),
                      float(it.get("unit_price") or 0), float(it.get("amount") or 0),
                      _clean(it.get("tax_rate"), 20), idx))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def create_invoice(file: UploadFile, owner_type: str = "", owner_id: int = 0,
                       invoice_kind: str = "", username: str = "", auto_parse: bool = True) -> Dict[str, Any]:
        """上传发票: 先落文件 + 发票记录 + 关联, 再自动解析; 解析失败发票与文件仍保留"""
        payload = FulfillmentDocService.read_upload(file)
        if owner_type and owner_type not in ("order", "package", "purchase_order"):
            raise HTTPException(status_code=400, detail="发票只能关联订单/包裹/采购单")
        if owner_type and not FulfillmentDocService.owner_exists(owner_type, int(owner_id)):
            raise HTTPException(status_code=404, detail="发票关联对象不存在")

        # 文件级去重: 同一文件已登记过发票 → 只补关联
        conn = get_db_connection()
        try:
            dup = conn.execute("""
                SELECT i.id FROM fm_documents d JOIN fm_invoices i ON i.id = d.owner_id
                WHERE d.owner_type = 'invoice' AND d.category = 'invoice' AND d.sha256 = ?
                LIMIT 1
            """, (payload["sha256"],)).fetchone()
        finally:
            conn.close()
        if dup:
            if owner_type:
                FulfillmentService._link_invoice(dup["id"], owner_type, int(owner_id))
            return {"invoice": FulfillmentService.get_invoice(dup["id"]), "duplicate": True,
                    "warnings": ["该发票文件已存在，已直接复用并新增关联"]}

        conn = get_db_connection()
        try:
            cur = conn.execute("""
                INSERT INTO fm_invoices (invoice_kind, parse_status, created_by)
                VALUES (?, 'pending', ?)
            """, (_clean(invoice_kind, 40) or "其他发票", username or ""))
            invoice_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()

        FulfillmentDocService.save_bytes("invoice", invoice_id, "invoice", payload, username=username)
        if owner_type:
            FulfillmentService._link_invoice(invoice_id, owner_type, int(owner_id))

        warnings: List[str] = []
        if auto_parse:
            try:
                parsed = parse_invoice_bytes(payload["content"], payload["file_name"], username=username)
                # 上传时已人工指定发票类型 (采购发票/物流发票等) 则不被解析结果覆盖
                FulfillmentService._apply_invoice_parsed(
                    invoice_id, parsed, keep_kind=bool(_clean(invoice_kind, 40)))
            except HTTPException as exc:
                warnings.append(f"发票已保存，但自动解析失败: {exc.detail}")
                conn = get_db_connection()
                try:
                    conn.execute(
                        "UPDATE fm_invoices SET parse_status = 'failed', parse_error = ?, updated_at = ? WHERE id = ?",
                        (str(exc.detail)[:500], _now(), int(invoice_id)))
                    conn.commit()
                finally:
                    conn.close()
        return {"invoice": FulfillmentService.get_invoice(invoice_id),
                "duplicate": False, "warnings": warnings}

    @staticmethod
    def reparse_invoice(invoice_id: int, username: str = "") -> Dict[str, Any]:
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT * FROM fm_documents WHERE owner_type = 'invoice' AND owner_id = ? "
                "AND category = 'invoice' ORDER BY id DESC LIMIT 1", (int(invoice_id),)).fetchone()
        finally:
            conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="该发票没有可解析的原始文件")
        path = FulfillmentDocService.get_doc_path(dict(row))
        if not os.path.isfile(path):
            raise HTTPException(status_code=404, detail="发票原始文件已丢失")
        with open(path, "rb") as buf:
            content = buf.read()
        try:
            parsed = parse_invoice_bytes(content, row["file_name"], username=username)
            # 保留已有的发票类型: 类型由上传槽位决定, 不让解析结果覆盖
            FulfillmentService._apply_invoice_parsed(invoice_id, parsed, keep_kind=True)
        except HTTPException as exc:
            conn = get_db_connection()
            try:
                conn.execute(
                    "UPDATE fm_invoices SET parse_status = 'failed', parse_error = ?, updated_at = ? WHERE id = ?",
                    (str(exc.detail)[:500], _now(), int(invoice_id)))
                conn.commit()
            finally:
                conn.close()
            raise
        return {"invoice": FulfillmentService.get_invoice(invoice_id)}

    @staticmethod
    def update_invoice(invoice_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        allowed = ["invoice_kind", "invoice_code", "invoice_number", "invoice_date", "seller_name",
                   "seller_tax_id", "buyer_name", "buyer_tax_id", "currency", "amount_excl_tax",
                   "tax_amount", "total_amount", "total_in_words", "remark", "verified"]
        sets, params = [], []
        for key in allowed:
            if key not in payload:
                continue
            val = payload[key]
            if key in ("amount_excl_tax", "tax_amount", "total_amount"):
                val = float(val or 0)
            elif key == "verified":
                val = 1 if val else 0
            else:
                val = _clean(val, 500)
            sets.append(f"{key} = ?")
            params.append(val)
        if not sets:
            raise HTTPException(status_code=400, detail="没有需要更新的字段")
        conn = get_db_connection()
        try:
            conn.execute(f"UPDATE fm_invoices SET {', '.join(sets)}, updated_at = ? WHERE id = ?",
                         params + [_now(), int(invoice_id)])
            conn.commit()
        finally:
            conn.close()
        return FulfillmentService.get_invoice(invoice_id)

    @staticmethod
    def add_invoice_link(invoice_id: int, owner_type: str, owner_id: int,
                         allocated_amount: float = 0) -> Dict[str, Any]:
        FulfillmentService._link_invoice(invoice_id, owner_type, owner_id, allocated_amount)
        return FulfillmentService.get_invoice(invoice_id)

    @staticmethod
    def remove_invoice_link(invoice_id: int, owner_type: str, owner_id: int) -> Dict[str, Any]:
        conn = get_db_connection()
        try:
            conn.execute("""
                DELETE FROM fm_invoice_links WHERE invoice_id = ? AND owner_type = ? AND owner_id = ?
            """, (int(invoice_id), owner_type, int(owner_id)))
            conn.commit()
        finally:
            conn.close()
        return FulfillmentService.get_invoice(invoice_id)

    @staticmethod
    def delete_invoice(invoice_id: int) -> Dict[str, Any]:
        _remove_doc_files(FulfillmentDocService.list_docs("invoice", invoice_id))
        conn = get_db_connection()
        try:
            # 记下关联的采购单: 发票删掉后采购单可能已无任何素材
            po_ids = [int(r["owner_id"]) for r in conn.execute(
                "SELECT owner_id FROM fm_invoice_links WHERE invoice_id = ? AND owner_type = 'purchase_order'",
                (int(invoice_id),)).fetchall()]
            conn.execute("DELETE FROM fm_documents WHERE owner_type = 'invoice' AND owner_id = ?", (int(invoice_id),))
            conn.execute("DELETE FROM fm_invoice_items WHERE invoice_id = ?", (int(invoice_id),))
            conn.execute("DELETE FROM fm_invoice_links WHERE invoice_id = ?", (int(invoice_id),))
            conn.execute("DELETE FROM fm_invoices WHERE id = ?", (int(invoice_id),))
            conn.commit()
        finally:
            conn.close()
        for pid in po_ids:
            FulfillmentService.cleanup_purchase_order_if_empty(pid)
        return {"id": int(invoice_id)}
