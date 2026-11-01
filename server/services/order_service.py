"""
妙手订单包裹服务 (订单管理模块)

数据源: 妙手开放平台 `POST /open/v1/order/package/fetch/search_package_list`
    - 分页上限 pageSize=200 (实测 500 报错), 返回 data.total 可判断是否翻完
    - 妙手限频约 1 次/秒 → 页间 sleep 1.1s

落库: miaoshou_orders (package_id = opOrderPackageId 唯一, 同步按它幂等 UPSERT)
商品明细与原始报文以 JSON 存 items_json / raw_json, 详情弹窗直接渲染。
"""
import json
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from server.database import get_db_connection
from server.services.chudao_service import ChudaoService
from server.services.miaoshou_service import MiaoshouService, MiaoshouApiError
from server.services.order_doc_service import DOC_TYPES, OrderDocService
from server.services.waybill_service import WaybillService
from server.services.workbuddy_service import identify_products

PAGE_SIZE = 200          # 妙手单页上限
MAX_PAGES_PER_STATUS = 100   # 单状态翻页保护 (100×200 = 2 万单)
CALL_INTERVAL = 1.1      # 妙手限频: 约 1 次/秒

LABEL_LIMIT_PER_SYNC = 300   # 单次同步最多识别多少单商品标识 (控制耗时与费用)
LABEL_MAX_ATTEMPTS = 3       # 商品标识识别失败重试上限 (超过则跳过, 避免无限重试)

# 订单包裹状态 (妙手 appPackageStatus)
STATUS_OPTIONS = [
    {"value": "unpaid", "label": "未付款"},
    {"value": "wait_confirmed", "label": "待审核"},
    {"value": "wait_seller_send", "label": "待发货"},
    {"value": "wait_receiver_confirm", "label": "已发货"},
    {"value": "finished", "label": "已完成"},
    {"value": "cancelled", "label": "已关闭"},
    {"value": "returned", "label": "已发货退款"},
    {"value": "refunding", "label": "售后中"},
]
DEFAULT_STATUSES = [s["value"] for s in STATUS_OPTIONS]
CLOSED_STATUS = "cancelled"   # 已关闭 (退款/关闭) —— 列表与统计默认排除


def _now_local() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class OrderService:
    """妙手订单包裹: 同步入库 / 列表查询 / 详情 / 筛选项"""

    # ─────────────────────────── 同步入库 ───────────────────────────

    @staticmethod
    def _row_from_package(p: Dict[str, Any]) -> Dict[str, Any]:
        """妙手包裹对象 → miaoshou_orders 行"""
        order = p.get("orderInfo") or {}
        cons = p.get("consigneeInfo") or {}
        logi = p.get("logisticsAgentProductInfo") or {}
        items = p.get("items") or []

        def num(v):
            try:
                return float(v or 0)
            except (TypeError, ValueError):
                return 0.0

        return {
            "package_id": str(p.get("opOrderPackageId") or ""),
            "order_sn": (order.get("platformOrderSn") or "").strip(),
            "app_package_no": (p.get("appPackageNo") or "").strip(),
            "platform": (p.get("platform") or order.get("platform") or "").strip(),
            "platform_name": (p.get("platformName") or "").strip(),
            "site": (p.get("site") or order.get("site") or "").strip(),
            "shop_id": str(p.get("shopId") or order.get("shopId") or ""),
            "shop_name": (p.get("shopName") or p.get("shopNick") or "").strip(),
            "order_status": (order.get("appOrderStatus") or "").strip(),
            "order_status_text": (order.get("appOrderStatusText") or "").strip(),
            "platform_status": (order.get("platformOrderStatus") or "").strip(),
            "package_status": (p.get("appPackageStatus") or "").strip(),
            "package_status_text": (p.get("appPackageStatusText") or "").strip(),
            "currency": (order.get("currency") or "").strip(),
            "order_amount": num(order.get("orderAmount")),
            "pay_amount": num(order.get("payAmount")),
            "product_amount": num(order.get("productAmount")),
            "commission_fee": num(order.get("commissionFee")),
            "gmt_order": (order.get("gmtOrderStart") or "").strip(),
            "gmt_pay": (order.get("gmtPay") or "").strip(),
            "gmt_delivery": (order.get("gmtDelivery") or "").strip(),
            "gmt_last_delivery": (order.get("gmtLastDelivery") or "").strip(),
            "dest_country": (cons.get("country") or "").strip(),
            "dest_country_name": (cons.get("countryName") or "").strip(),
            "receiver_state": (cons.get("state") or "").strip(),
            "tracking_no": (p.get("logisticsNo") or logi.get("logisticsNo") or "").strip(),
            "tracking_company": (logi.get("logisticsCompany") or "").strip(),
            "items_count": len(items),
            "items_json": json.dumps(items, ensure_ascii=False),
            "raw_json": json.dumps(p, ensure_ascii=False),
            "sync_time": _now_local(),
            "updated_at": _now_local(),
        }

    @staticmethod
    def _upsert_rows(rows: List[Dict[str, Any]]) -> tuple:
        """批量 UPSERT; 返回 (新增数, 更新数)"""
        rows = [r for r in rows if r.get("package_id")]
        if not rows:
            return 0, 0
        conn = get_db_connection()
        try:
            ids = [r["package_id"] for r in rows]
            marks = ",".join("?" * len(ids))
            exist = {x["package_id"] for x in conn.execute(
                f"SELECT package_id FROM miaoshou_orders WHERE package_id IN ({marks})", ids).fetchall()}
            inserted = len([i for i in ids if i not in exist])
            cols = list(rows[0].keys())
            placeholders = ",".join("?" * len(cols))
            # 人工改过运单号的记录 (tracking_no_manual=1): 同步时保留人工值, 不被妙手覆盖
            updates = ",".join(
                ("tracking_no=CASE WHEN miaoshou_orders.tracking_no_manual=1 "
                 "THEN miaoshou_orders.tracking_no ELSE excluded.tracking_no END"
                 if c == "tracking_no" else f"{c}=excluded.{c}")
                for c in cols if c != "package_id")
            sql = (f"INSERT INTO miaoshou_orders ({','.join(cols)}) VALUES ({placeholders}) "
                   f"ON CONFLICT(package_id) DO UPDATE SET {updates}")
            conn.executemany(sql, [[r.get(c) for c in cols] for r in rows])
            conn.commit()
            return inserted, len(rows) - inserted
        finally:
            conn.close()

    @staticmethod
    def _ids_by_package_ids(package_ids: List[str]) -> List[int]:
        """按 package_id 批量取订单 id (分块查询, 去重保序)"""
        uniq = list(dict.fromkeys([str(p) for p in package_ids if p]))
        if not uniq:
            return []
        out: List[int] = []
        conn = get_db_connection()
        try:
            for i in range(0, len(uniq), 500):
                chunk = uniq[i:i + 500]
                marks = ",".join("?" * len(chunk))
                for row in conn.execute(
                        f"SELECT id FROM miaoshou_orders WHERE package_id IN ({marks})", chunk):
                    out.append(int(row["id"]))
        finally:
            conn.close()
        return out

    # ─────────────────── 运单轨迹 (与运单管理同源, 初道 gettrack) ───────────────────

    @staticmethod
    def _save_track_snapshot(order_id: int, summary: Dict[str, Any]) -> str:
        now = _now_local()
        conn = get_db_connection()
        try:
            conn.execute(
                "UPDATE miaoshou_orders SET track_status_name = ?, track_desc = ?, track_time = ?, "
                "track_refreshed_at = ? WHERE id = ?",
                (summary.get("track_status_name", ""), summary.get("last_track_desc", ""),
                 summary.get("last_track_time", ""), now, int(order_id)))
            conn.commit()
        finally:
            conn.close()
        return now

    @staticmethod
    def _track_candidates(order_sn: str, tail_no: str) -> List[str]:
        """解析可查询的初道单号 (与运单管理页同源)

        妙手订单上的 tracking_no 是尾程承运商单号, 初道 gettrack 首选初道运单号
        (如 XM2GUJ7010011)。解析顺序:
        1) 运单库按平台订单号 (reference_no) 命中 → 初道运单号
        2) 运单库按尾程号/渠道单号/运单号命中 → 初道运单号
        3) 初道批量反查 (gettrackingnumberbatch)
        4) 兜底: 订单尾程号本身 (实测初道对尾程号同样命中)
        """
        tail = (tail_no or "").strip()
        sn = (order_sn or "").strip()
        cands: List[str] = []

        def push(value) -> None:
            v = str(value or "").strip()
            if v and v not in cands:
                cands.append(v)

        conn = get_db_connection()
        try:
            hits: List[Any] = []
            if sn:
                hits = conn.execute(
                    "SELECT tracking_number FROM forwarder_waybills WHERE reference_no = ? "
                    "ORDER BY datetime(updated_at) DESC LIMIT 5", (sn,)).fetchall()
            if tail:
                hits = hits + conn.execute(
                    "SELECT tracking_number FROM forwarder_waybills WHERE tracking_number = ? "
                    "OR server_hawbcode = ? OR channel_hawbcode = ? "
                    "ORDER BY datetime(updated_at) DESC LIMIT 5", (tail, tail, tail)).fetchall()
        except Exception:
            hits = []
        finally:
            conn.close()
        for row in hits:
            push(row["tracking_number"])

        ref = tail or sn
        if ref:
            try:
                info = (ChudaoService.get_tracking_numbers_batch([ref]) or {}).get(ref) or {}
            except Exception:
                info = {}
            push(info.get("shipping_method_no"))
            push(info.get("channel_hawbcode"))
        push(tail)
        return cands

    @staticmethod
    def _query_track(order_sn: str, tail_no: str) -> tuple:
        """按候选单号依次查询轨迹; 返回 (track, 命中单号, 最后一个异常)"""
        track, used, last_err = None, "", None
        for number in OrderService._track_candidates(order_sn, tail_no):
            try:
                track = ChudaoService.get_track(number)
            except Exception as exc:
                last_err = exc
                continue
            if track:
                used = number
                break
        return track, used, last_err

    @staticmethod
    def _track_for_order(order_sn: str, tail_no: str, manual: bool = False) -> tuple:
        """取订单轨迹: 人工修改过运单号时直接按该号查询, 否则走运单库反查"""
        if manual and (tail_no or "").strip():
            try:
                return ChudaoService.get_track(tail_no), tail_no, None
            except Exception as exc:
                return None, "", exc
        return OrderService._query_track(order_sn, tail_no)

    @staticmethod
    def update_supplement(order_id: int, purchase_date: str = "",
                          domestic_package_count: int = 0,
                          domestic_tracking_no: str = "") -> Dict[str, Any]:
        """补录信息: 采购日期 / 国内包裹数量 / 国内单号 (人工录入, 同步不覆盖)"""
        date_str = (purchase_date or "").strip()[:10]
        if not date_str:
            raise ValueError("请填写采购日期")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
            raise ValueError("采购日期格式应为 YYYY-MM-DD")
        try:
            count = int(domestic_package_count or 0)
        except (TypeError, ValueError):
            raise ValueError("国内包裹数量必须是数字")
        if count <= 0:
            raise ValueError("请填写国内包裹数量 (大于 0)")
        if count > 9999:
            raise ValueError("国内包裹数量需在 1 ~ 9999 之间")
        tracking = re.sub(r"[\s]+", "", str(domestic_tracking_no or ""))
        if not tracking:
            raise ValueError("请填写国内单号")
        if len(tracking) > 200:
            raise ValueError("国内单号过长")
        if not re.fullmatch(r"[A-Za-z0-9,\-_/;]+", tracking):
            raise ValueError("国内单号仅支持字母、数字及 , - _ / ;")

        conn = get_db_connection()
        try:
            row = conn.execute("SELECT id FROM miaoshou_orders WHERE id = ?",
                               (int(order_id),)).fetchone()
            if not row:
                raise ValueError("订单不存在")
            conn.execute(
                "UPDATE miaoshou_orders SET purchase_date = ?, domestic_package_count = ?, "
                "domestic_tracking_no = ?, updated_at = ? WHERE id = ?",
                (date_str, count, tracking, _now_local(), int(order_id)))
            conn.commit()
        finally:
            conn.close()
        return {"id": int(order_id), "purchase_date": date_str,
                "domestic_package_count": count, "domestic_tracking_no": tracking}

    @staticmethod
    def update_tracking_no(order_id: int, tracking_no: str,
                           tracking_company: str = "") -> Dict[str, Any]:
        """人工修改运单号

        - 旧单号写入 prev_tracking_no (仅保留上一次, 多次修改会被覆盖)
        - 单号变更后旧的轨迹快照作废, 立即按新单号重查一次并回写
        """
        new_no = re.sub(r"\s+", "", str(tracking_no or ""))
        if not new_no:
            raise ValueError("运单号不能为空")
        if len(new_no) > 64 or not re.fullmatch(r"[A-Za-z0-9\-_/]+", new_no):
            raise ValueError("运单号格式不正确 (仅支持字母、数字及 - _ /)")

        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT id, tracking_no, tracking_company FROM miaoshou_orders WHERE id = ?",
                (int(order_id),)).fetchone()
            if not row:
                raise ValueError("订单不存在")
            old_no = (row["tracking_no"] or "").strip()
            old_company = (row["tracking_company"] or "").strip()
            company = (tracking_company or "").strip() or old_company
            if old_no == new_no and company == old_company:
                raise ValueError("运单号未发生变化")
            conn.execute(
                "UPDATE miaoshou_orders SET prev_tracking_no = ?, tracking_no = ?, tracking_company = ?, "
                "tracking_no_manual = 1, "
                "track_status_name = '', track_desc = '', track_time = '', track_refreshed_at = '', "
                "updated_at = ? WHERE id = ?",
                (old_no, new_no, company, _now_local(), int(order_id)))
            conn.commit()
        finally:
            conn.close()

        # 按新单号立刻查一次轨迹 (查询失败不影响单号修改本身)
        found = False
        summary: Dict[str, Any] = {}
        refreshed_at = ""
        try:
            track = ChudaoService.get_track(new_no)
            if track:
                summary = WaybillService._track_summary(track)
                refreshed_at = OrderService._save_track_snapshot(order_id, summary)
                found = True
        except Exception:
            found = False

        return {
            "id": int(order_id), "tracking_no": new_no,
            "prev_tracking_no": old_no, "tracking_company": company,
            "found": found,
            "track_status_name": summary.get("track_status_name", ""),
            "track_desc": summary.get("last_track_desc", ""),
            "track_time": summary.get("last_track_time", ""),
            "track_refreshed_at": refreshed_at,
        }

    @staticmethod
    def refresh_track(order_id: int) -> Dict[str, Any]:
        """刷新单个订单的运单轨迹 (失败抛 ValueError, 供路由转 400)"""
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT id, order_sn, tracking_no, tracking_no_manual, tracking_company "
                "FROM miaoshou_orders WHERE id = ?",
                (int(order_id),)).fetchone()
        finally:
            conn.close()
        if not row:
            raise ValueError("订单不存在")
        number = (row["tracking_no"] or "").strip()
        if not number and not (row["order_sn"] or "").strip():
            raise ValueError("该订单没有运单号，无法查询轨迹")
        track, used, last_err = OrderService._track_for_order(
            row["order_sn"], number, int(row["tracking_no_manual"] or 0) == 1)
        if track is None and last_err is not None:
            raise ValueError(f"轨迹查询失败: {last_err}")
        summary = WaybillService._track_summary(track)
        now = OrderService._save_track_snapshot(order_id, summary)
        return {
            "id": int(order_id), "tracking_no": number, "chudao_no": used,
            "track_status_name": summary.get("track_status_name", ""),
            "track_desc": summary.get("last_track_desc", ""),
            "track_time": summary.get("last_track_time", ""),
            "track_refreshed_at": now, "found": bool(track),
        }

    @staticmethod
    def refresh_tracks(order_ids: List[int]) -> Dict[str, Any]:
        """批量刷新运单轨迹 (逐单查询, 单个失败不影响其余)"""
        refreshed: List[Dict[str, Any]] = []
        failed: List[Dict[str, str]] = []
        for oid in order_ids or []:
            try:
                refreshed.append(OrderService.refresh_track(int(oid)))
            except Exception as exc:
                failed.append({"id": str(oid), "reason": str(exc)})
            time.sleep(0.2)  # 轻微限速, 避免初道接口频控
        return {"refreshed": refreshed, "failed": failed, "total": len(order_ids or [])}

    @staticmethod
    def _waybill_channel_no(tail_no: str, order_sn: str = "") -> str:
        """从运单库取跨境运单号 (channel_hawbcode): 按尾程号/初岛号/渠道号或参考号命中, 无则空串"""
        tail = (tail_no or "").strip()
        sn = (order_sn or "").strip()
        if not tail and not sn:
            return ""
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT channel_hawbcode FROM forwarder_waybills WHERE "
                "IFNULL(channel_hawbcode, '') != '' AND ("
                "  (? != '' AND (tracking_number = ? OR server_hawbcode = ? OR channel_hawbcode = ?))"
                "  OR (? != '' AND reference_no = ?)) "
                "ORDER BY datetime(updated_at) DESC, id DESC LIMIT 1",
                (tail, tail, tail, tail, sn, sn)).fetchone()
        except Exception:
            row = None
        finally:
            conn.close()
        return (row["channel_hawbcode"] or "").strip() if row else ""

    @staticmethod
    def get_track_detail(order_id: int) -> Dict[str, Any]:
        """轨迹详情: 实时查询并回写快照; 接口无数据时回退库中快照"""
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT id, order_sn, tracking_no, tracking_no_manual, tracking_company, "
                "track_status_name, track_desc, "
                "track_time, track_refreshed_at FROM miaoshou_orders WHERE id = ?",
                (int(order_id),)).fetchone()
        finally:
            conn.close()
        if not row:
            raise ValueError("订单不存在")
        number = (row["tracking_no"] or "").strip()
        if not number and not (row["order_sn"] or "").strip():
            raise ValueError("该订单没有运单号，无法查询轨迹")
        track, used, _ = OrderService._track_for_order(
            row["order_sn"], number, int(row["tracking_no_manual"] or 0) == 1)
        channel_no = ""
        if track:
            summary = WaybillService._track_summary(track)
            channel_no = (summary.get("channel_hawbcode") or "").strip()
            refreshed_at = OrderService._save_track_snapshot(order_id, summary)
        else:
            summary = {
                "track_status_name": row["track_status_name"] or "",
                "last_track_desc": row["track_desc"] or "",
                "last_track_time": row["track_time"] or "",
            }
            refreshed_at = row["track_refreshed_at"] or ""
        # 跨境运单号: 优先用轨迹返回, 缺失时从运单库补齐 (无则不展示)
        if not channel_no:
            channel_no = OrderService._waybill_channel_no(number, row["order_sn"])
        return {
            "id": int(order_id),
            "tracking_no": number,
            "chudao_no": used,
            "channel_hawbcode": channel_no,
            "tracking_company": row["tracking_company"] or "",
            "track_status_name": summary.get("track_status_name", ""),
            "last_track_desc": summary.get("last_track_desc", ""),
            "last_track_time": summary.get("last_track_time", ""),
            "track_refreshed_at": refreshed_at,
            "details": (track or {}).get("details") or [],
        }

    # ─────────────────── 商品标识识别 (WorkBuddy 大模型) ───────────────────

    @staticmethod
    def _title_of(items_json: str, raw_json: str = "") -> str:
        """取该包裹的商品标题 (首个非空 item title; 兜底妙手原始报文字段)"""
        titles: List[str] = []
        try:
            for it in json.loads(items_json or "[]") or []:
                t = str(it.get("title") or "").strip()
                if t:
                    titles.append(t)
        except (ValueError, TypeError):
            pass
        if titles:
            return titles[0][:500]
        try:
            raw = json.loads(raw_json or "{}") or {}
            order = raw.get("orderInfo") or {}
            return str(order.get("itemTitle") or raw.get("packageName") or "").strip()[:500]
        except (ValueError, TypeError):
            return ""

    @staticmethod
    def tag_missing_product_labels(limit: int = LABEL_LIMIT_PER_SYNC) -> Dict[str, Any]:
        """为尚无商品标识的订单批量调用 WorkBuddy 识别"这是什么商品"并落库

        - 只处理 product_label 为空且尝试次数 < LABEL_MAX_ATTEMPTS 的订单
        - 同一标题只识别一次 (去重), 单批失败仅跳过该批
        返回 {"tagged": 成功单数, "failed": 失败单数, "titles": 参与识别的标题数}
        """
        stats = {"tagged": 0, "failed": 0, "titles": 0}
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT id, product_label, product_label_short, items_json, raw_json FROM miaoshou_orders "
                "WHERE (IFNULL(product_label,'') = '' OR IFNULL(product_label_short,'') = '') "
                "AND IFNULL(label_attempts,0) < ? "
                "ORDER BY datetime(IFNULL(gmt_order,'')) DESC, id DESC LIMIT ?",
                (LABEL_MAX_ATTEMPTS, max(1, int(limit)))).fetchall()
            if not rows:
                return stats

            title_to_ids: Dict[str, List[int]] = {}
            no_title_ids: List[int] = []
            for r in rows:
                title = OrderService._title_of(r["items_json"], r["raw_json"])
                if title:
                    title_to_ids.setdefault(title, []).append(r["id"])
                else:
                    no_title_ids.append(r["id"])

            # 无标题的包裹无法识别, 直接计一次尝试避免反复扫描
            if no_title_ids:
                marks = ",".join("?" * len(no_title_ids))
                conn.execute(
                    f"UPDATE miaoshou_orders SET label_attempts = IFNULL(label_attempts,0) + 1 "
                    f"WHERE id IN ({marks})", no_title_ids)
                conn.commit()

            if not title_to_ids:
                return stats

            stats["titles"] = len(title_to_ids)
            mapping = identify_products(list(title_to_ids.keys()))
            now = _now_local()
            for title, ids in title_to_ids.items():
                item = mapping.get(title) or {}
                label = item.get("product") or ""
                short = item.get("short") or (label[:5] if label else "")
                marks = ",".join("?" * len(ids))
                if label:
                    conn.execute(
                        f"UPDATE miaoshou_orders SET product_label = ?, product_label_short = ?, "
                        f"label_attempts = IFNULL(label_attempts,0) + 1, updated_at = ? "
                        f"WHERE id IN ({marks})", [label, short, now, *ids])
                    stats["tagged"] += len(ids)
                else:
                    conn.execute(
                        f"UPDATE miaoshou_orders SET label_attempts = IFNULL(label_attempts,0) + 1 "
                        f"WHERE id IN ({marks})", ids)
                    stats["failed"] += len(ids)
            conn.commit()
        finally:
            conn.close()
        return stats

    @staticmethod
    def sync_orders(statuses: Optional[List[str]] = None, days: int = 0,
                    max_packages: int = 20000,
                    on_progress=None) -> Dict[str, Any]:
        """从妙手分状态翻页拉取订单包裹并入库

        - statuses: 状态列表, 默认全部 8 种
        - days: >0 时按妙手创建时间取最近 N 天 (gmtCreateFrom)
        - on_progress: 可选回调 (msg) 用于同步过程日志
        返回 {fetched, inserted, updated, pages, by_status, failed}
        """
        statuses = statuses or DEFAULT_STATUSES
        gmt_from = ""
        if days and days > 0:
            gmt_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d 00:00:00")

        fetched = inserted = updated = pages = 0
        by_status: Dict[str, int] = {}
        failed: List[Dict[str, str]] = []
        first_call = True
        synced_pkg_ids: List[str] = []   # 本次同步涉及的包裹 (供批量更新轨迹用)

        for status in statuses:
            if fetched >= max_packages:
                break
            page = 1
            while page <= MAX_PAGES_PER_STATUS and fetched < max_packages:
                if not first_call:
                    time.sleep(CALL_INTERVAL)  # 妙手限频
                first_call = False
                body = {"page": page, "pageSize": PAGE_SIZE, "appPackageStatus": status}
                if gmt_from:
                    body["gmtCreateFrom"] = gmt_from
                try:
                    resp = MiaoshouService.call(
                        "/open/v1/order/package/fetch/search_package_list", body)
                except MiaoshouApiError as exc:
                    msg = str(exc)
                    if "没有符合条件" in msg:
                        break  # 该状态下无数据
                    failed.append({"status": status, "page": str(page), "reason": msg})
                    break
                data = resp.get("data") or {}
                packages = data.get("orderPackageList") or []
                if not packages:
                    break
                rows = [OrderService._row_from_package(p) for p in packages]
                synced_pkg_ids += [r["package_id"] for r in rows if r.get("package_id")]
                ins, upd = OrderService._upsert_rows(rows)
                inserted += ins
                updated += upd
                fetched += len(rows)
                pages += 1
                by_status[status] = by_status.get(status, 0) + len(rows)
                if on_progress:
                    on_progress(f"{status} 第{page}页: {len(rows)} 条 (新增{ins}/更新{upd})")
                total = int(data.get("total") or 0)
                if total and page * PAGE_SIZE >= total:
                    break
                if len(packages) < PAGE_SIZE and not total:
                    break
                page += 1

        # 首次同步进来的订单 (以及历史缺漏) 自动识别商品标识; 大模型异常不影响同步结果
        try:
            label_stats = OrderService.tag_missing_product_labels()
        except Exception as exc:  # 兜底: 识别失败只记录, 不中断同步
            label_stats = {"tagged": 0, "failed": 0, "titles": 0, "error": str(exc)}
        if on_progress and (label_stats.get("tagged") or label_stats.get("failed")):
            on_progress(f"商品识别: 成功 {label_stats['tagged']} 单 / 失败 {label_stats['failed']} 单")

        # 本次同步涉及的订单 id (前端据此批量更新运单轨迹)
        try:
            ids = OrderService._ids_by_package_ids(synced_pkg_ids)
        except Exception:
            ids = []

        return {"fetched": fetched, "inserted": inserted, "updated": updated,
                "pages": pages, "by_status": by_status, "failed": failed,
                "product": label_stats, "ids": ids}

    # ─────────────────────────── 查询 ───────────────────────────

    @staticmethod
    def list_orders(keyword: str = "", status: str = "", shop_id: str = "",
                    platform: str = "", date_from: str = "", date_to: str = "",
                    page: int = 1, page_size: int = 20,
                    include_closed: bool = False) -> Dict[str, Any]:
        """分页查询 (keyword 匹配订单号/妙手包裹号/运单号/店铺名)

        默认排除「已关闭」(cancelled) 的订单; 显式筛选该状态时正常返回。
        """
        where, params = [], []
        if keyword:
            kw = f"%{keyword.strip()}%"
            where.append("(IFNULL(order_sn,'') LIKE ? OR IFNULL(app_package_no,'') LIKE ? "
                         "OR IFNULL(tracking_no,'') LIKE ? OR IFNULL(shop_name,'') LIKE ? "
                         "OR IFNULL(product_label,'') LIKE ?)")
            params += [kw, kw, kw, kw, kw]
        if status:
            where.append("package_status = ?")
            params.append(status)
        elif not include_closed:
            where.append("IFNULL(package_status,'') <> ?")
            params.append(CLOSED_STATUS)
        if shop_id:
            where.append("shop_id = ?")
            params.append(shop_id)
        if platform:
            where.append("platform = ?")
            params.append(platform)
        if date_from:
            where.append("gmt_order >= ?")
            params.append(date_from)
        if date_to:
            where.append("gmt_order <= ?")
            params.append(f"{date_to} 23:59:59")
        clause = (" WHERE " + " AND ".join(where)) if where else ""

        page = max(1, int(page or 1))
        page_size = max(1, min(int(page_size or 20), 200))
        conn = get_db_connection()
        try:
            total = conn.execute(f"SELECT COUNT(*) AS c FROM miaoshou_orders{clause}", params).fetchone()["c"]
            rows = conn.execute(
                "SELECT id, package_id, order_sn, app_package_no, platform, platform_name, site, "
                "shop_id, shop_name, order_status_text, package_status, package_status_text, currency, "
                "order_amount, pay_amount, gmt_order, gmt_delivery, dest_country, dest_country_name, "
                "receiver_state, tracking_no, prev_tracking_no, tracking_company, "
                "purchase_date, domestic_package_count, domestic_tracking_no, items_count, product_label, "
                "product_label_short, track_status_name, track_desc, track_time, track_refreshed_at, "
                "sync_time, items_json "
                f"FROM miaoshou_orders{clause} ORDER BY datetime(gmt_order) DESC, id DESC LIMIT ? OFFSET ?",
                params + [page_size, (page - 1) * page_size]).fetchall()
        finally:
            conn.close()
        # 列表首图: items[0] 的 picUrl (缩略) / originalPicUrl (放大)
        out = []
        for r in rows:
            d = dict(r)
            items_raw = d.pop("items_json", None)
            thumb = big = sku = ""
            try:
                arr = json.loads(items_raw or "[]")
                if arr:
                    it = arr[0]
                    thumb = it.get("picUrl") or it.get("originalPicUrl") or ""
                    big = it.get("originalPicUrl") or it.get("picUrl") or ""
                    sku = (it.get("platformOuterSkuId") or it.get("platformItemId")
                           or it.get("platformSkuId") or "")
            except (ValueError, TypeError):
                pass
            d["cover_img"] = thumb
            d["cover_img_big"] = big or thumb
            d["sku"] = sku
            out.append(d)
        # 合单标记: 共用同一运单号的其他订单 (按当前运单号比较, 人工修改后即用新值)
        tails = sorted({(d.get("tracking_no") or "").strip() for d in out
                        if (d.get("tracking_no") or "").strip()})
        groups: Dict[str, List[Dict[str, Any]]] = {}
        if tails:
            conn = get_db_connection()
            try:
                for i in range(0, len(tails), 400):
                    chunk = tails[i:i + 400]
                    marks = ",".join("?" * len(chunk))
                    for r in conn.execute(
                            f"SELECT id, tracking_no, order_sn FROM miaoshou_orders "
                            f"WHERE tracking_no IN ({marks})", chunk):
                        groups.setdefault((r["tracking_no"] or "").strip(), []).append(
                            {"id": int(r["id"]), "order_sn": r["order_sn"] or ""})
            finally:
                conn.close()
        for d in out:
            tail = (d.get("tracking_no") or "").strip()
            others = [g["order_sn"] for g in groups.get(tail, [])
                      if g["id"] != d["id"] and g["order_sn"]]
            d["merged_orders"] = others
            d["merged_count"] = len(others)

        # 单据附件份数 (采购单/采购发票/发货单/签收单/物流发票/清关证明)
        counts = OrderDocService.doc_counts([d["id"] for d in out])
        for d in out:
            d["docs"] = counts.get(d["id"], {})
        return {"rows": out, "total": total,
                "page": page, "page_size": page_size,
                "pages": (total + page_size - 1) // page_size,
                "doc_types": DOC_TYPES}

    @staticmethod
    def get_order(order_id: int) -> Optional[Dict[str, Any]]:
        """订单详情 (含商品明细/原始报文)"""
        conn = get_db_connection()
        try:
            row = conn.execute("SELECT * FROM miaoshou_orders WHERE id = ?", (order_id,)).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        d = dict(row)
        for key in ("items_json", "raw_json"):
            try:
                d[key.replace("_json", "")] = json.loads(d.pop(key) or "[]")
            except (ValueError, TypeError):
                d[key.replace("_json", "")] = [] if key == "items_json" else {}
        d["docs"] = OrderDocService.list_docs(order_id)
        d["doc_types"] = DOC_TYPES
        return d

    @staticmethod
    def filter_options(include_closed: bool = False) -> Dict[str, Any]:
        """筛选项: 店铺 / 平台 / 状态 (按库中已有数据生成)

        计数默认排除「已关闭」订单, 与列表默认视图保持一致。
        """
        stat_where = "" if include_closed else f" WHERE IFNULL(package_status,'') <> '{CLOSED_STATUS}'"
        conn = get_db_connection()
        try:
            shops = [dict(r) for r in conn.execute(
                "SELECT DISTINCT shop_id, shop_name FROM miaoshou_orders "
                "WHERE IFNULL(shop_id,'') <> '' ORDER BY shop_name").fetchall()]
            platforms = [r["platform"] for r in conn.execute(
                "SELECT DISTINCT platform FROM miaoshou_orders "
                "WHERE IFNULL(platform,'') <> '' ORDER BY platform").fetchall()]
            stats = {r["package_status"]: r["c"] for r in conn.execute(
                f"SELECT package_status, COUNT(*) AS c FROM miaoshou_orders{stat_where} "
                "GROUP BY package_status").fetchall()}
            total = conn.execute(f"SELECT COUNT(*) AS c FROM miaoshou_orders{stat_where}").fetchone()["c"]
            last = conn.execute("SELECT MAX(sync_time) AS t FROM miaoshou_orders").fetchone()["t"] or ""
        finally:
            conn.close()
        return {"shops": shops, "platforms": platforms, "stats": stats,
                "total": total, "last_sync": last, "status_options": STATUS_OPTIONS,
                "doc_types": DOC_TYPES}
