"""在线产品查询 (跨库只读 adsAutoAna 的 ads.db)

表 online_products:
  is_variation = '1' 父体 (asin = 父 ASIN, sku = 父 SKU)
  is_variation = '2' 子体 (sku = MSKU, parent_asin = 父 ASIN)
  raw_json     = 原站整行 (~85 字段: title/mainImage/standardPrice/parentSku ...)

用途: 订单管理列表按订单 SKU 反查父体与兄弟 SKU。
"""
import json
import os
import sqlite3
from typing import Any, Dict, List, Optional

from server.config import BASE_DIR
from server.database import get_setting

# 默认取仓库内 adsauto/data/ads.db (与主仓库同机部署); 系统设置 ads_autoana_db 可覆盖
DEFAULT_ADS_DB = os.path.join(BASE_DIR, "adsauto", "data", "ads.db")


class OnlineProductService:

    @staticmethod
    def db_path() -> str:
        """在线产品库路径 (可在系统设置里用 ads_autoana_db 覆盖)"""
        path = (get_setting("ads_autoana_db") or "").strip() or DEFAULT_ADS_DB
        return os.path.expanduser(path)

    @staticmethod
    def _conn() -> Optional[sqlite3.Connection]:
        path = OnlineProductService.db_path()
        if not os.path.exists(path):
            return None
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception:
            return None

    @staticmethod
    def _raw(row) -> Dict[str, Any]:
        try:
            return json.loads(row["raw_json"] or "{}")
        except Exception:
            return {}

    @staticmethod
    def _brief(row, is_self: bool = False) -> Dict[str, Any]:
        raw = OnlineProductService._raw(row)
        return {
            "asin": row["asin"] or raw.get("asin") or "",
            "sku": row["sku"] or raw.get("sku") or "",
            "parent_asin": row["parent_asin"] or raw.get("parentAsin") or "",
            "parent_sku": raw.get("parentSku") or "",
            "title": (row["title"] or raw.get("title") or "").strip(),
            # 缩略图用小图(快), 点击放大用原图 mainBigImage(清晰)
            "image": raw.get("mainImage") or row["main_image"] or "",
            "image_big": raw.get("mainBigImage") or raw.get("mainImage") or row["main_image"] or "",
            "price": raw.get("standardPrice") or raw.get("landedPrice") or "",
            "landed_price": raw.get("landedPrice") or "",
            "currency": raw.get("standardPriceCurrency") or "JPY",
            "status": raw.get("onlineStatus") or row["online_status"] or "",
            "attr": raw.get("variationAttrZh") or raw.get("variationChildStr") or "",
            "attr_raw": raw.get("variationChildStr") or "",
            "attr_zh": "",
            "fnsku": raw.get("fnsku") or "",
            "shop": raw.get("shopName") or "",
            "is_self": is_self,
        }

    @staticmethod
    def labels_for_skus(skus: List[str]) -> Dict[str, Dict[str, str]]:
        """批量取商品标识: SKU → {zh 中文标识, en 英文标识, asin, parent_asin}

        链路: sku → online_products → parent_asin
              → translations(kind='product_name', source=父ASIN) → 中文标识
              → translations(kind='product_name_en', source=中文标识) → 英文标识
        """
        want = sorted({str(s or "").strip() for s in (skus or []) if str(s or "").strip()})
        out: Dict[str, Dict[str, str]] = {}
        if not want:
            return out
        conn = OnlineProductService._conn()
        if conn is None:
            return out
        try:
            marks = ",".join("?" * len(want))
            rows = conn.execute(
                f"SELECT LOWER(sku) AS sk, asin, parent_asin, raw_json FROM online_products "
                f"WHERE LOWER(sku) IN ({marks})", [s.lower() for s in want]).fetchall()
            asin_map = {r["sk"]: ((r["asin"] or ""), (r["parent_asin"] or "")) for r in rows}
            # 售价 (standardPrice): 复制单价列要用子 SKU 的售价
            price_map: Dict[str, float] = {}
            for r in rows:
                try:
                    raw = json.loads(r["raw_json"] or "{}")
                    p = raw.get("standardPrice") or raw.get("landedPrice")
                    if p not in (None, ""):
                        price_map[r["sk"]] = float(p)
                except Exception:
                    pass

            zh_map: Dict[str, str] = {}
            parents = sorted({p for _, p in asin_map.values() if p})
            if parents:
                pm = ",".join("?" * len(parents))
                for r in conn.execute(
                        f"SELECT source, zh FROM translations WHERE kind = 'product_name' "
                        f"AND source IN ({pm})", parents):
                    zh_map[r["source"]] = r["zh"] or ""

            en_map: Dict[str, str] = {}
            labels = sorted({v for v in zh_map.values() if v})
            if labels:
                lm = ",".join("?" * len(labels))
                for r in conn.execute(
                        f"SELECT source, zh FROM translations WHERE kind = 'product_name_en' "
                        f"AND source IN ({lm})", labels):
                    en_map[r["source"]] = r["zh"] or ""

            for sku in want:
                asin, parent = asin_map.get(sku.lower(), ("", ""))
                zh = zh_map.get(parent, "")
                out[sku] = {"zh": zh, "en": en_map.get(zh, ""), "asin": asin,
                            "parent_asin": parent, "price": price_map.get(sku.lower(), "")}
            return out
        finally:
            conn.close()

    @staticmethod
    def lookup(sku: str) -> Dict[str, Any]:
        """按 SKU 查: 当前子体 + 父体 + 兄弟子体"""
        sku = (sku or "").strip()
        out: Dict[str, Any] = {"sku": sku, "found": False, "self": None,
                               "parent": None, "siblings": [], "error": ""}
        if not sku:
            return out
        conn = OnlineProductService._conn()
        if conn is None:
            out["error"] = "在线产品库不可用（未找到 ads.db）"
            return out
        try:
            # 1) 定位子体: 大小写不敏感精确匹配 sku, 兜底匹配 raw_json.sku
            row = conn.execute(
                "SELECT * FROM online_products WHERE LOWER(sku) = LOWER(?) LIMIT 1",
                (sku,)).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT * FROM online_products WHERE is_variation = '2' "
                    "AND LOWER(json_extract(raw_json, '$.sku')) = LOWER(?) LIMIT 1",
                    (sku,)).fetchone()
            if not row:
                return out

            parent_asin = (row["parent_asin"] or "").strip()
            # 2) 父体行
            parent = None
            if parent_asin:
                parent = conn.execute(
                    "SELECT * FROM online_products WHERE is_variation = '1' AND asin = ? LIMIT 1",
                    (parent_asin,)).fetchone()
            # 3) 兄弟子体
            siblings: List[Dict[str, Any]] = []
            if parent_asin:
                for s in conn.execute(
                        "SELECT * FROM online_products WHERE is_variation = '2' AND parent_asin = ? "
                        "ORDER BY sku", (parent_asin,)).fetchall():
                    if (s["asin"] or "") == (row["asin"] or ""):
                        continue
                    siblings.append(OnlineProductService._brief(s))

            out["found"] = True
            out["self"] = OnlineProductService._brief(row, True)
            out["parent"] = OnlineProductService._brief(parent) if parent else None
            out["siblings"] = siblings
            out["parent_asin"] = parent_asin

            # 商品标识: 父 ASIN → 中文标识 → 英文标识
            out["label_zh"] = ""
            out["label_en"] = ""
            if parent_asin:
                try:
                    r = conn.execute(
                        "SELECT zh FROM translations WHERE kind = 'product_name' AND source = ? "
                        "LIMIT 1", (parent_asin,)).fetchone()
                    zh = (r["zh"] or "") if r else ""
                    out["label_zh"] = zh
                    if zh:
                        r2 = conn.execute(
                            "SELECT zh FROM translations WHERE kind = 'product_name_en' AND source = ? "
                            "LIMIT 1", (zh,)).fetchone()
                        out["label_en"] = (r2["zh"] or "") if r2 else ""
                except Exception:
                    pass

            # 属性中文翻译: variationChildStr → translations(kind='variation_attr_zh')
            nodes = [out["self"]] + siblings
            raws = sorted({n["attr_raw"] for n in nodes if n.get("attr_raw")})
            if raws:
                try:
                    marks = ",".join("?" * len(raws))
                    zh_map = {r["source"]: r["zh"] for r in conn.execute(
                        f"SELECT source, zh FROM translations WHERE kind = 'variation_attr_zh' "
                        f"AND source IN ({marks})", raws).fetchall()}
                    for n in nodes:
                        n["attr_zh"] = zh_map.get(n.get("attr_raw") or "", "") or ""
                except Exception:
                    pass
            return out
        finally:
            conn.close()
