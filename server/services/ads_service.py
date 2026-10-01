# -*- coding: utf-8 -*-
"""广告分析业务层: 三份 Excel (在线产品/广告活动/广告组) 导入、数据关联、三视图查询
- 在线产品: 全量替换导入 (ASIN 唯一快照)
- 广告活动/广告组: 按唯一键 (日期+名称[+所属活动]) 幂等 upsert
- 数据关联: 广告活动名提取 ASIN → 匹配产品子ASIN → 反推父ASIN/父SKU → 标记"是否开通自动广告"
- 视图: 产品(子) 分页筛选 / 产品(父) 聚合 / 广告研判 广告组汇总

- 人工标记: 广告研判「新每日预算/新默认竞价」按广告组名持久化 (ads_group_marks)
- 统计结果: 参数组合(预算+竞价)聚合 + 未投广父SKU代表ASIN + 重复ASIN
"""
import io
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import openpyxl

from server.database import get_db_connection

# 广告活动/广告组名称中的 ASIN 提取 (亚马逊标准格式 B0XXXXXXXX)
ASIN_RE = re.compile(r"B0[A-Z0-9]{8}")

# 广告研判: 非累加字段 (取最新一天值, 不跨日期累加); 其余数值字段累加
_RESEARCH_NON_ADDITIVE_PAT = re.compile(r"率$|占比$|费用$|单价$")
_RESEARCH_NON_ADDITIVE_EXACT = {"每笔订单花费", "平均点击费用", "单次加购花费", "VCPM", "CPM",
                                "搜索结果首页首位IS", "广告产品"}


def _is_non_additive(field: str) -> bool:
    if field in _RESEARCH_NON_ADDITIVE_EXACT:
        return True
    if any(w in field for w in ("率", "占比", "竞价", "ACoS", "ROAS", "ACoTS", "ASoTS", "VCPM", "CPM", "IS")):
        return True
    return bool(_RESEARCH_NON_ADDITIVE_PAT.search(field))


# 在线产品-子 默认展示列 (其余列可通过列设置勾选)
PRODUCT_DEFAULT_COLS = ["图片", "状态", "父ASIN", "ASIN", "MSKU", "FNSKU", "父SKU", "SKU", "标题",
                        "价格", "是否开通自动广告", "销量", "销售额", "7天销量", "星级评分",
                        "评分数", "小类目排名", "可售"]

# 广告组模板中 "广告花费" 及其之后的列 (按模板原有顺序)
GROUP_TAIL_COLS = ["广告花费", "竞价优化类型", "广告花费占比", "广告曝光量", "广告点击量", "每笔订单花费",
                   "平均点击费用", "广告点击率", "广告转化率", "ACoS", "ROAS", "ACoTS", "ASoTS",
                   "广告笔单价", "广告订单量", "广告订单量占比", "广告销量", "其他产品广告订单量",
                   "广告销售额", "广告销售额占比", "本广告产品销售额", "其他产品广告销售额",
                   "广告销量占比", "本广告产品订单量", "本广告产品销量", "其他产品广告销量",
                   "单次加购花费", "创建者", "标签", "广告策略标签", "业务员", "广告曝光量占比",
                   "广告点击占比", "本广告产品订单占比", "本广告产品销量占比", "本广告产品销售额占比",
                   "本广告产品笔单价", "其他广告产品订单占比", "其他广告产品销量占比",
                   "其他广告产品销售额占比", "其他产品广告笔单价"]

# 广告研判 默认展示列 (按用户指定顺序): 关联产品/活动信息 + 模板列(自 "广告花费" 起顺序追加, 已展示列自动跳过)
RESEARCH_HEAD_COLS = ["图片", "子ASIN", "父ASIN", "父SKU", "变体数量", "广告产品",
                      "活动开始日期", "活动结束日期", "标题", "产品价格", "数据日期", "打广天数",
                      "每日总预算", "默认竞价", "广告曝光量", "广告点击量", "广告点击率", "广告花费"]
RESEARCH_DEFAULT_COLS = RESEARCH_HEAD_COLS + [c for c in GROUP_TAIL_COLS if c not in RESEARCH_HEAD_COLS]


def _cell_str(v: Any) -> str:
    """单元格转字符串 (None/空 → '')"""
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v).strip()


def _cell_num(v: Any) -> Optional[float]:
    """单元格转数值 (失败返回 None)"""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# 金额前缀币种符号 (如 "JP￥30.00" / "US$1.00" / "￥12.5")
_CURRENCY_PREFIX_RE = re.compile(r"^\s*(?:[A-Za-z]{0,3}\s*)?[¥￥$€£]\s*")


def _strip_currency(v: Any) -> str:
    """去掉金额前缀币种符号: 'JP￥30.00' → '30.00'"""
    return _CURRENCY_PREFIX_RE.sub("", _cell_str(v))


def _norm_num(v: Any) -> str:
    """数值文本归一化: '30.00' → '30' (便于同值合并展示)"""
    s = _cell_str(v)
    if not s:
        return ""
    try:
        f = float(s)
    except (TypeError, ValueError):
        return s
    return str(int(f)) if f == int(f) else str(f)


def _rows_from_xlsx(content: bytes) -> List[Dict[str, Any]]:
    """解析 xlsx 为 [{表头: 值}, ...]
    注意: 这些报表文件 dimension 元数据常损坏, 不能用 read_only 模式"""
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    try:
        ws = wb.worksheets[0]
        rows_iter = ws.iter_rows(values_only=True)
        header = None
        out: List[Dict[str, Any]] = []
        for row in rows_iter:
            cells = list(row)
            if header is None:
                if any(c is not None and str(c).strip() for c in cells):
                    header = [_cell_str(c) for c in cells]
                continue
            if not any(c is not None and str(c).strip() for c in cells):
                continue
            rec = {}
            for i, h in enumerate(header):
                if h and i < len(cells):
                    rec[h] = cells[i]
            out.append(rec)
        return out
    finally:
        wb.close()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# 活动「无结束日期」的各种写法 (视为长期有效, 只校验开始日期)
_NO_END_VALUES = ("", "-", "无", "无结束日期", "长期", "不限", "null", "None")

# 未在投的活动状态 (有效状态/服务状态命中即视为已停止投放)
_PAUSED_VALUES = ("已暂停", "已结束", "已归档", "已关闭", "暂停")


def _norm_date(v: Any) -> str:
    """日期归一化为 YYYY-MM-DD (支持 datetime / 2026/9/8 / 2026-09-08 09:00:00), 失败返回 ''"""
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    s = _cell_str(v).replace("/", "-").replace(".", "-")
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if not m:
        return ""
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def _date_minus(date_str: str, days: int) -> str:
    """ISO 日期往前推 N 天 (解析失败返回 '')"""
    try:
        return (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    except ValueError:
        return ""


class AdsService:
    """广告分析: 导入 / 关联 / 查询"""

    # ─────────────────────────── 导入 ───────────────────────────

    @staticmethod
    def import_products(content: bytes) -> Dict[str, Any]:
        """在线产品导入 (全量替换快照), 返回 {count, fields}"""
        rows = _rows_from_xlsx(content)
        if not rows:
            raise ValueError("文件中没有可识别的数据行")
        fields = list(rows[0].keys())
        now = _now()
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM ads_products;")
            inserted = 0
            for r in rows:
                asin = _cell_str(r.get("ASIN"))
                if not asin:
                    continue
                data = {k: (v if isinstance(v, (int, float)) and v is not None else _cell_str(v))
                        for k, v in r.items() if k}
                cursor.execute("""
                    INSERT INTO ads_products
                        (asin, parent_asin, msku, sku, parent_sku, price, status, title, image, auto_ad, data, import_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?);
                """, (
                    asin,
                    _cell_str(r.get("父ASIN")),
                    _cell_str(r.get("MSKU")),
                    _cell_str(r.get("SKU")),
                    _cell_str(r.get("父SKU")),
                    _cell_num(r.get("价格")) or 0.0,
                    _cell_str(r.get("状态")),
                    _cell_str(r.get("标题")),
                    _cell_str(r.get("图片")),
                    json.dumps(data, ensure_ascii=False),
                    now,
                ))
                inserted += 1
            conn.commit()
            return {"count": inserted, "fields": fields}
        finally:
            conn.close()

    @staticmethod
    def import_campaigns(content: bytes) -> Dict[str, Any]:
        """广告活动导入 (日期+活动名 幂等 upsert)"""
        rows = _rows_from_xlsx(content)
        if not rows:
            raise ValueError("文件中没有可识别的数据行")
        now = _now()
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            upserted = 0
            for r in rows:
                name = _cell_str(r.get("广告活动"))
                if not name:
                    continue
                data = {k: (v if isinstance(v, (int, float)) and v is not None else _cell_str(v))
                        for k, v in r.items() if k}
                cursor.execute("""
                    INSERT INTO ads_campaigns
                        (date, name, shop, state, service_state, bid_strategy, daily_budget,
                         ad_type, targeting, data, import_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(date, name) DO UPDATE SET
                        shop=excluded.shop, state=excluded.state, service_state=excluded.service_state,
                        bid_strategy=excluded.bid_strategy, daily_budget=excluded.daily_budget,
                        ad_type=excluded.ad_type, targeting=excluded.targeting, data=excluded.data,
                        import_time=excluded.import_time;
                """, (
                    _cell_str(r.get("日期")), name,
                    _cell_str(r.get("店铺名称")), _cell_str(r.get("有效状态")),
                    _cell_str(r.get("服务状态")), _cell_str(r.get("广告活动竞价策略")),
                    _cell_str(r.get("每日预算")), _cell_str(r.get("广告类型")),
                    _cell_str(r.get("投放类型")),
                    json.dumps(data, ensure_ascii=False), now,
                ))
                upserted += 1
            conn.commit()
            return {"count": upserted}
        finally:
            conn.close()

    @staticmethod
    def import_groups(content: bytes) -> Dict[str, Any]:
        """广告组导入 (日期+组名+所属活动 幂等 upsert)"""
        rows = _rows_from_xlsx(content)
        if not rows:
            raise ValueError("文件中没有可识别的数据行")
        now = _now()
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            upserted = 0
            for r in rows:
                name = _cell_str(r.get("广告组名称"))
                if not name:
                    continue
                data = {k: (v if isinstance(v, (int, float)) and v is not None else _cell_str(v))
                        for k, v in r.items() if k}
                # 默认竞价去掉币种前缀 (JP￥30.00 → 30.00)
                if "默认竞价" in data:
                    data["默认竞价"] = _strip_currency(data["默认竞价"])
                cursor.execute("""
                    INSERT INTO ads_groups
                        (date, name, campaign_name, shop, state, service_state, targeting,
                         default_bid, products_count, data, import_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(date, name, campaign_name) DO UPDATE SET
                        shop=excluded.shop, state=excluded.state, service_state=excluded.service_state,
                        targeting=excluded.targeting, default_bid=excluded.default_bid,
                        products_count=excluded.products_count, data=excluded.data,
                        import_time=excluded.import_time;
                """, (
                    _cell_str(r.get("日期")), name, _cell_str(r.get("所属广告活动")),
                    _cell_str(r.get("店铺名称")), _cell_str(r.get("有效状态")),
                    _cell_str(r.get("服务状态")), _cell_str(r.get("投放类型")),
                    _strip_currency(r.get("默认竞价")), _cell_str(r.get("广告产品")),
                    json.dumps(data, ensure_ascii=False), now,
                ))
                upserted += 1
            conn.commit()
            return {"count": upserted}
        finally:
            conn.close()

    # ─────────────────────────── 数据关联 ───────────────────────────

    @staticmethod
    def link_data() -> Dict[str, Any]:
        """
        三表关联 (点击「数据关联」按钮触发, 全量重算):
        1. 广告活动名提取 ASIN → 匹配产品子ASIN → 反推父ASIN
        2. 产品 auto_ad = 该子ASIN 存在 投放类型=自动 的广告活动
        3. 广告组经 所属广告活动 → 广告活动 → 产品 (查询时动态联表)
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT asin, parent_asin FROM ads_products;")
            asin2parent = {r["asin"]: (r["parent_asin"] or "") for r in cursor.fetchall()}

            # 1. 广告活动: 提取产品ASIN并回填父ASIN
            cursor.execute("SELECT id, name FROM ads_campaigns;")
            camp_rows = cursor.fetchall()
            camp_product_asins = set()
            unmatched = set()
            for r in camp_rows:
                m = ASIN_RE.search(r["name"] or "")
                pasin = m.group(0) if m else ""
                parent = asin2parent.get(pasin, "")
                if pasin:
                    camp_product_asins.add(pasin)
                    if not parent:
                        unmatched.add(pasin)
                cursor.execute(
                    "UPDATE ads_campaigns SET product_asin = ?, parent_asin = ? WHERE id = ?;",
                    (pasin, parent, r["id"]))

            # 2. 产品: 是否开通自动广告 (投放类型=自动 的活动覆盖到的子ASIN)
            cursor.execute("UPDATE ads_products SET auto_ad = 0;")
            cursor.execute(
                "SELECT DISTINCT product_asin FROM ads_campaigns WHERE targeting = '自动' AND product_asin != '';")
            auto_asins = [r["product_asin"] for r in cursor.fetchall()]
            for a in auto_asins:
                cursor.execute("UPDATE ads_products SET auto_ad = 1 WHERE asin = ?;", (a,))

            # 3. 广告组冗余存产品ASIN/父ASIN (经所属广告活动名匹配), 查询提速
            cursor.execute("SELECT DISTINCT name, product_asin, parent_asin FROM ads_campaigns WHERE product_asin != '';")
            camp_map = {r["name"]: (r["product_asin"], r["parent_asin"]) for r in cursor.fetchall()}
            cursor.execute("SELECT id, campaign_name FROM ads_groups;")
            for r in cursor.fetchall():
                pa, ppa = camp_map.get(r["campaign_name"] or "", ("", ""))
                cursor.execute("UPDATE ads_groups SET product_asin = ?, parent_asin = ? WHERE id = ?;", (pa, ppa, r["id"]))
            conn.commit()

            cursor.execute("SELECT COUNT(*) c FROM ads_products WHERE auto_ad = 1;")
            with_ad = cursor.fetchone()["c"]
            return {
                "campaigns_total": len(camp_rows),
                "campaigns_linked": len(camp_product_asins),
                "products_with_ad": with_ad,
                "auto_asins": len(set(auto_asins)),
                "unmatched_asins": sorted(unmatched),
            }
        finally:
            conn.close()

    @staticmethod
    def clear_all() -> Dict[str, Any]:
        """清空全部已导入及已处理的数据 (在线产品/广告活动/广告组 + 人工标记, 含关联结果)"""
        tables = (("products", "ads_products"), ("campaigns", "ads_campaigns"), ("groups", "ads_groups"),
                  ("marks", "ads_group_marks"))
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_sequence';")
            has_seq = cursor.fetchone() is not None
            cleared: Dict[str, int] = {}
            for key, table in tables:
                cursor.execute(f"SELECT COUNT(*) c FROM {table};")
                cleared[key] = cursor.fetchone()["c"] or 0
                cursor.execute(f"DELETE FROM {table};")
                if has_seq:
                    cursor.execute("DELETE FROM sqlite_sequence WHERE name = ?;", (table,))
            conn.commit()
            cleared["total"] = sum(cleared.values())
            return cleared
        finally:
            conn.close()

    # ─────────────────────────── 在投判定 ───────────────────────────

    @staticmethod
    def active_asins_by_campaign(today: str = "") -> Tuple[set, str]:
        """当前「正在投广」的子ASIN集合 (未投广判定的唯一依据)。

        判定口径: 存在**正在投的广告活动** —— 同时满足
          ① 活动状态未停止: 最新一天的「有效状态」不是 已暂停/已结束/已关闭 等
             (有效状态为空时退回看「服务状态」)
          ② 当前日期落在活动的「开始日期 ~ 结束日期」闭区间内
             - 结束日期为 "无结束日期"/空 → 视为长期有效, 只校验开始日期
             - 起止日期缺失 → 退回该活动报表覆盖的日期范围 (最早~最晚报表日期)
        返回 (在投子ASIN集合, 判定基准日期)
        """
        base = _norm_date(today) or _today()
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name, date, state, service_state, product_asin, data "
                           "FROM ads_campaigns ORDER BY date ASC, id ASC;")
            rows = cursor.fetchall()
        finally:
            conn.close()

        info: Dict[str, Dict[str, str]] = {}
        for c in rows:                                  # 日期升序 → 后面的覆盖前面的(取最新快照)
            name = _cell_str(c["name"])
            if not name:
                continue
            it = info.setdefault(name, {})
            for key, col in (("state", "state"), ("service", "service_state")):
                v = _cell_str(c[col])
                if v:
                    it[key] = v
            pasin = _cell_str(c["product_asin"])
            if pasin:
                it["asin"] = pasin
            else:
                m = ASIN_RE.search(name)                 # 未关联时从活动名兜底提取
                if m and not it.get("asin"):
                    it["asin"] = m.group(0)
            try:
                cdata = json.loads(c["data"] or "{}")
            except Exception:
                cdata = {}
            for key in ("开始日期", "结束日期"):
                v = _norm_date(cdata.get(key))
                if v:
                    it[key] = v
            d = _norm_date(c["date"])
            if d:
                it.setdefault("first_date", d)           # 报表覆盖范围兜底
                it["last_date"] = d

        out: set = set()
        for it in info.values():
            state, service = it.get("state", ""), it.get("service", "")
            # ① 活动已停止 → 不算在投 (状态缺失时退回看服务状态)
            if state:
                if any(w in state for w in _PAUSED_VALUES):
                    continue
            elif service and any(w in service for w in _PAUSED_VALUES):
                continue
            # ② 当前日期需落在活动起止期间内
            start = it.get("开始日期") or it.get("first_date") or ""
            end = it.get("结束日期") or ""
            if start and base < start:
                continue
            if end and end not in _NO_END_VALUES and base > end:
                continue
            if it.get("asin"):
                out.add(it["asin"])
        return out, base

    @staticmethod
    def get_status() -> Dict[str, Any]:
        """导入状态概览 (三表行数+最近导入时间+是否已关联)"""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            out: Dict[str, Any] = {}
            for key, table in (("products", "ads_products"), ("campaigns", "ads_campaigns"), ("groups", "ads_groups")):
                cursor.execute(f"SELECT COUNT(*) c, MAX(import_time) t FROM {table};")
                r = cursor.fetchone()
                out[key] = {"count": r["c"] or 0, "last_import": r["t"] or ""}
            cursor.execute("SELECT COUNT(*) c FROM ads_campaigns;")
            total = cursor.fetchone()["c"]
            cursor.execute("SELECT COUNT(*) c FROM ads_campaigns WHERE product_asin != '';")
            linked = cursor.fetchone()["c"]
            out["link"] = {"campaigns_total": total, "campaigns_linked": linked, "linked": total > 0 and linked > 0}
            cursor.execute("SELECT COUNT(*) c FROM ads_products WHERE auto_ad = 1;")
            out["link"]["products_with_ad"] = cursor.fetchone()["c"]
            return out
        finally:
            conn.close()

    # ─────────────────────────── 在线产品-子 ───────────────────────────

    @staticmethod
    def get_products(auto_ad: str = "", keyword: str = "", sort: str = "", order: str = "desc",
                     page: int = 1, page_size: int = 50) -> Dict[str, Any]:
        """产品(子)列表: 服务端筛选/排序/分页; fields 为原始Excel列序 (前端列配置用)"""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ads_products ORDER BY id ASC;")
            rows = cursor.fetchall()
            fields: List[str] = []
            items: List[Dict[str, Any]] = []
            for r in rows:
                try:
                    data = json.loads(r["data"] or "{}")
                except Exception:
                    data = {}
                if not fields and data:
                    fields = list(data.keys())
                item = dict(data)
                item["是否开通自动广告"] = "是" if r["auto_ad"] else "否"
                items.append(item)
        finally:
            conn.close()

        # 筛选
        if auto_ad in ("1", "0"):
            want = "是" if auto_ad == "1" else "否"
            items = [x for x in items if x.get("是否开通自动广告") == want]
        kw = (keyword or "").strip().lower()
        if kw:
            def _hit(x):
                return any(kw in str(v).lower() for v in (
                    x.get("ASIN"), x.get("父ASIN"), x.get("MSKU"), x.get("SKU"),
                    x.get("父SKU"), x.get("标题")))
            items = [x for x in items if _hit(x)]

        # 排序 (数值优先)
        if sort:
            reverse = (order or "desc").lower() != "asc"

            def _sv(x):
                v = x.get(sort)
                n = _cell_num(v)
                return (0, n) if n is not None else (1, str(v or ""))
            items.sort(key=_sv, reverse=reverse)

        total = len(items)
        page = max(1, page)
        page_size = max(1, min(200, page_size))
        start = (page - 1) * page_size
        return {"fields": fields, "defaults": PRODUCT_DEFAULT_COLS,
                "rows": items[start:start + page_size],
                "total": total, "page": page, "page_size": page_size}

    # ─────────────────────────── 在线产品-父 ───────────────────────────

    @staticmethod
    def get_parents(keyword: str = "", has_ad: str = "", sort: str = "", order: str = "desc") -> Dict[str, Any]:
        """
        产品(父)列表: 以父ASIN聚合一条;
        是否在投 = 该父下任一子ASIN存在**正在投的广告活动** (活动未停止 且 当前日期在活动起止期间内);
        无父ASIN的独立品视作自身为一组
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ads_products ORDER BY id ASC;")
            rows = cursor.fetchall()
            cursor.execute("SELECT MAX(date) AS d FROM ads_groups;")
            latest_row = cursor.fetchone()
            latest_date = (latest_row["d"] if latest_row else "") or ""
        finally:
            conn.close()

        # 当前正在投广的子ASIN集合 (判定基准: 系统当前日期 + 活动起止期间)
        active_asins, base_date = AdsService.active_asins_by_campaign()

        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        meta: Dict[str, Dict[str, str]] = {}
        for r in rows:
            parent_asin = r["parent_asin"] or r["asin"]   # 无父ASIN → 自成一组
            g = groups[parent_asin]
            g.append({"asin": r["asin"], "price": r["price"] or 0.0, "auto": bool(r["auto_ad"]),
                      "sku": r["sku"] or "", "parent_sku": r["parent_sku"] or ""})
            if parent_asin not in meta:
                p_sku = r["parent_sku"] or (r["sku"] if not r["parent_asin"] else "")
                # 代表子品(第一个子ASIN)的图片/标题, 供列表展示
                meta[parent_asin] = {"parent_sku": p_sku, "first_child_asin": r["asin"],
                                     "image": r["image"] or "", "title": r["title"] or ""}
            elif not meta[parent_asin]["parent_sku"] and r["parent_sku"]:
                meta[parent_asin]["parent_sku"] = r["parent_sku"]

        items = []
        for parent_asin, children in groups.items():
            m = meta.get(parent_asin, {})
            prices = [c["price"] for c in children if c["price"]]
            # 最新日期当天该父下是否有子品在投放
            group_has_ad = any(c["asin"] in active_asins for c in children)   # 有正在投的活动
            items.append({
                "图片": m.get("image", ""),
                "父ASIN": parent_asin,
                "父SKU": m.get("parent_sku", ""),
                "子ASIN": m.get("first_child_asin", ""),
                "标题": m.get("title", ""),
                "产品价格": round(sum(prices) / len(prices)) if prices else 0,
                "变体数量": len(children),
                "是否在投": "是" if group_has_ad else "否",
            })

        kw = (keyword or "").strip().lower()
        if kw:
            items = [x for x in items if kw in str(x.get("父SKU", "")).lower()
                     or kw in str(x.get("父ASIN", "")).lower()]
        if has_ad in ("1", "0"):
            want = "是" if has_ad == "1" else "否"
            items = [x for x in items if x.get("是否在投") == want]
        if sort in ("产品价格", "变体数量"):
            items.sort(key=lambda x: x[sort], reverse=(order or "desc").lower() != "asc")
        else:
            items.sort(key=lambda x: x.get("父SKU", ""))
        return {"rows": items, "total": len(items), "latest_date": latest_date,
                "base_date": base_date, "active_total": len(active_asins),
                "defaults": ["图片", "父ASIN", "父SKU", "子ASIN", "标题", "产品价格", "变体数量", "是否在投"]}

    # ─────────────────────────── 广告研判 ───────────────────────────

    @staticmethod
    def get_research(keyword: str = "", days: str = "", marked: str = "",
                     sort: str = "", order: str = "desc",
                     page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """
        广告研判: 一条 = 一个广告组 (跨日期汇总, 率类字段按总量重算, 其余非累加取最新)
        days: 时间范围 (以数据中最新日期为基准往前推, 1/3/7 天; 空 = 全部)
        marked: 1/0 按是否人工标记筛选; 空 = 全部
        sort/order/page/page_size: 服务端排序 + 分页 (默认每页 20)
        首列关联产品图片, 其余列取自广告组原始字段 (列可配置)
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ads_groups ORDER BY date ASC, id ASC;")
            grows = cursor.fetchall()
            cursor.execute("SELECT * FROM ads_campaigns ORDER BY date ASC, id ASC;")
            crows = cursor.fetchall()
            cursor.execute("SELECT asin, parent_asin, parent_sku, price, auto_ad, image, title "
                           "FROM ads_products;")
            prows = cursor.fetchall()
            # 人工录入的新值 / 标记状态
            marks: Dict[str, Dict[str, Any]] = {}
            try:
                cursor.execute("SELECT group_name, new_budget, new_bid, marked FROM ads_group_marks;")
                marks = {m["group_name"]: m for m in cursor.fetchall()}
            except Exception:   # 旧库可能还没建该表
                marks = {}
        finally:
            conn.close()

        # 时间范围筛选: 近 N 天 = [最新日期-(N-1), 最新日期]
        span = int(days) if str(days).strip().isdigit() and int(days) > 0 else 0
        all_dates = sorted({_cell_str(r["date"]) for r in grows if _cell_str(r["date"])})
        range_start = range_end = ""
        if all_dates:
            range_start, range_end = all_dates[0], all_dates[-1]
            if span:
                back = _date_minus(range_end, span - 1)
                if back:
                    range_start = back
                    grows = [r for r in grows if back <= _cell_str(r["date"]) <= range_end]

        # 父ASIN → 子品聚合 (价格均价/变体数量); 子ASIN → 产品图片
        parent_children: Dict[str, List[float]] = defaultdict(list)
        child2parent: Dict[str, str] = {}
        parent_sku: Dict[str, str] = {}
        asin_image: Dict[str, str] = {}
        asin_title: Dict[str, str] = {}
        for p in prows:
            pa = p["parent_asin"] or ""
            asin_image[p["asin"]] = p["image"] or ""
            asin_title[p["asin"]] = p["title"] or ""
            if pa:
                parent_children[pa].append(p["price"] or 0.0)
                child2parent[p["asin"]] = pa
                if pa not in parent_sku and p["parent_sku"]:
                    parent_sku[pa] = p["parent_sku"]

        # 广告活动: 组名 → 最新非空属性 (每日预算/竞价策略/投放类型/状态/起止日期)
        camp_map: Dict[str, Dict[str, str]] = {}
        for c in crows:
            info = camp_map.setdefault(c["name"] or "", {})
            for key, col in (("每日总预算", "daily_budget"), ("竞价策略", "bid_strategy"),
                             ("投放类型", "targeting"), ("活动状态", "state")):
                v = _cell_str(c[col])
                if v:
                    info[key] = v
            # 活动起止日期取自活动报表的 "开始日期/结束日期" (缺失时用报表覆盖日期兜底)
            try:
                cdata = json.loads(c["data"] or "{}")
            except Exception:
                cdata = {}
            for key in ("开始日期", "结束日期"):
                v = _cell_str(cdata.get(key))
                if v:
                    info[key] = v
            d = _cell_str(c["date"])
            if d:
                info.setdefault("_first_date", d)   # crows 按日期升序
                info["_last_date"] = d
        for info in camp_map.values():
            if not info.get("开始日期"):
                info["开始日期"] = info.get("_first_date", "")
            if not info.get("结束日期"):
                info["结束日期"] = info.get("_last_date", "")

        # 广告组按组名聚合
        agg: Dict[str, Dict[str, Any]] = {}
        name_order: List[str] = []
        gfields: List[str] = []
        for r in grows:
            try:
                data = json.loads(r["data"] or "{}")
            except Exception:
                data = {}
            if not gfields and data:
                gfields = list(data.keys())
            name = r["name"] or ""
            if name not in agg:
                agg[name] = {"_name": name, "_camp": r["campaign_name"] or "",
                             "_pasin": r["product_asin"] or "",
                             "_nums": defaultdict(float), "_latest": {}, "_dates": [],
                             "_active_dates": set()}
                name_order.append(name)
            a = agg[name]
            for k, v in data.items():
                if k in ("日期", "店铺名称", "创建时间"):
                    continue
                n = _cell_num(v)
                sv = _cell_str(v)
                if n is not None and not _is_non_additive(k):
                    a["_nums"][k] += n
                elif sv and sv != "-":
                    a["_latest"][k] = sv
            d_str = _cell_str(r["date"])
            if d_str:
                a["_dates"].append(d_str)
                # 打广天数: 当天有实际投放 (曝光/点击/花费任一 > 0) 才计入
                if any(a["_nums"].get(k, 0) for k in ("广告曝光量", "广告点击量", "广告花费")):
                    a["_active_dates"].add(d_str)

        # 组装行
        items = []
        for name in name_order:
            a = agg[name]
            camp = camp_map.get(a["_camp"], {})
            # 产品关联: 优先用关联时冗余的 product_asin, 否则从活动名提取
            child_asin = a["_pasin"] or (ASIN_RE.search(a["_camp"] or "").group(0)
                                         if ASIN_RE.search(a["_camp"] or "") else "")
            pa = child2parent.get(child_asin, "")
            row: Dict[str, Any] = {}
            row["广告组名"] = a["_name"]
            row["图片"] = asin_image.get(child_asin, "")
            row["标题"] = asin_title.get(child_asin, "")
            row["父ASIN"] = pa
            row["父SKU"] = parent_sku.get(pa, "")
            row["子ASIN"] = child_asin
            prices = parent_children.get(pa, [])
            prices = [x for x in prices if x]
            row["产品价格"] = round(sum(prices) / len(prices)) if prices else ""
            row["变体数量"] = len(parent_children.get(pa, [])) if pa else ""
            row["广告活动名"] = a["_camp"]
            # 数据日期: 该广告组在当前统计窗口内最新一天的数据
            row["数据日期"] = max(a["_dates"]) if a["_dates"] else ""
            # 打广天数: 当前统计窗口内该广告组有实际投放的天数 (打广日期供前端 tooltip 展示)
            row["打广天数"] = len(a["_active_dates"])
            row["打广日期"] = sorted(a["_active_dates"])
            row["每日总预算"] = camp.get("每日总预算", "")
            row["竞价策略"] = camp.get("竞价策略", "")
            # 所属广告活动的起止日期
            row["活动开始日期"] = camp.get("开始日期", "")
            row["活动结束日期"] = camp.get("结束日期", "")
            # 广告组属性
            row["默认竞价"] = _strip_currency(a["_latest"].get("默认竞价", ""))
            # 人工录入的新值 (操作列) 与标记状态
            mk = marks.get(name)
            row["新每日预算"] = _cell_str(mk["new_budget"]) if mk else ""
            row["新默认竞价"] = _cell_str(mk["new_bid"]) if mk else ""
            row["是否标记"] = "是" if (mk and mk["marked"]) else "否"
            row["广告产品"] = a["_latest"].get("广告产品", "")
            row["有效状态"] = a["_latest"].get("有效状态", "")
            row["服务状态"] = a["_latest"].get("服务状态", "")
            row["投放类型"] = a["_latest"].get("投放类型", "")
            # 累加指标 + 率类重算
            nums = a["_nums"]
            row["广告曝光量"] = nums.get("广告曝光量", 0)
            row["广告点击量"] = nums.get("广告点击量", 0)
            row["广告点击率"] = (round(nums["广告点击量"] / nums["广告曝光量"] * 100, 2)
                              if nums.get("广告曝光量") else "")
            row["广告花费"] = round(nums.get("广告花费", 0), 2)
            # 其余广告组原始字段 (排除已展示/日期类)
            shown = {"默认竞价", "广告产品", "有效状态", "服务状态", "投放类型", "广告曝光量", "广告点击量",
                     "广告点击率", "广告花费", "标题", "打广天数", "日期", "店铺名称", "创建时间",
                     "所属广告活动", "广告组名称"}
            for k in gfields:
                if k in shown:
                    continue
                if k not in nums or _RESEARCH_NON_ADDITIVE_PAT.search(k):
                    # 文本类/非累加字段 (创建者/标签/业务员/竞价优化类型/率类等): 取最新值
                    row[k] = a["_latest"].get(k, "")
                else:
                    v = nums.get(k, 0)
                    row[k] = round(v, 2) if isinstance(v, float) else v
            row["日期范围"] = f"{min(a['_dates'])} ~ {max(a['_dates'])}" if a["_dates"] else ""
            items.append(row)

        kw = (keyword or "").strip().lower()
        if kw:
            items = [x for x in items if any(kw in str(v).lower() for v in
                     (x.get("广告组名"), x.get("父ASIN"), x.get("父SKU"), x.get("子ASIN"), x.get("广告活动名")))]
        marked_total = sum(1 for x in items if x.get("是否标记") == "是")
        if marked in ("1", "0"):
            want = "是" if marked == "1" else "否"
            items = [x for x in items if x.get("是否标记") == want]

        # 排序 (数值优先, 再按字符串比较)
        if sort:
            reverse = (order or "desc").lower() != "asc"

            def _sort_key(x):
                n = _cell_num(x.get(sort))
                return (0, n) if n is not None else (1, str(x.get(sort) or ""))

            items.sort(key=_sort_key, reverse=reverse)

        # 分页 (默认每页 20, 上限 200)
        total = len(items)
        page = max(1, int(page or 1))
        page_size = max(1, min(200, int(page_size or 20)))
        start = (page - 1) * page_size
        rows = items[start:start + page_size]

        # 广告组原始字段列表 (列配置用, 排除已展示/日期类)
        extra_fields = [k for k in gfields if k not in
                        ("日期", "店铺名称", "创建时间", "所属广告活动", "广告组名称", "广告曝光量",
                         "广告点击量", "广告点击率", "广告花费", "默认竞价", "广告产品", "有效状态",
                         "服务状态", "投放类型")]
        base_fields = ["广告组名", "图片", "子ASIN", "父ASIN", "父SKU", "变体数量", "广告产品",
                       "活动开始日期", "活动结束日期", "标题", "产品价格", "数据日期", "打广天数",
                       "广告活动名", "每日总预算", "竞价策略", "默认竞价", "有效状态",
                       "投放类型", "广告曝光量", "广告点击量", "广告点击率", "广告花费", "日期范围"]
        return {"fields": base_fields + extra_fields, "defaults": RESEARCH_DEFAULT_COLS,
                "rows": rows, "total": total, "marked_total": marked_total,
                "page": page, "page_size": page_size,
                "range": {"start": range_start, "end": range_end, "days": span}}

    # ─────────────────────────── 统计结果 ───────────────────────────

    @staticmethod
    def get_stats() -> Dict[str, Any]:
        """
        统计结果:
        ① 参数组合统计: 覆盖全部广告组, 已录入新值(含品级标记)的按新值计算, 其余按当前值
        ② 当前未投广的父SKU: 该父SKU下所有子ASIN均**没有正在投的广告活动**
           (活动未停止 且 当前日期在活动起止期间内), 每个父SKU取一个代表子ASIN
        前端附加能力(均为会话内存态, 不落库):
        - 未投广栏目统一一对"每日预算/默认竞价"输入框, 适配该栏目下所有代表ASIN
        - 自定义分组 (每日预算 + 默认竞价 + ASIN列表) 可自行增删改
        - 各区域可"清除重复项"并一键恢复
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT group_name, new_budget, new_bid FROM ads_group_marks;")
            marks = {m["group_name"]: m for m in cursor.fetchall()}
            cursor.execute("SELECT name, campaign_name, date, data, product_asin FROM ads_groups "
                           "ORDER BY date ASC, id ASC;")
            grows = cursor.fetchall()
            cursor.execute("SELECT name, daily_budget FROM ads_campaigns ORDER BY date ASC, id ASC;")
            crows = cursor.fetchall()
            cursor.execute("SELECT asin, parent_asin, parent_sku FROM ads_products ORDER BY id ASC;")
            prows = cursor.fetchall()
            cursor.execute("SELECT MAX(date) AS d FROM ads_groups;")
            latest_row = cursor.fetchone()
            latest_date = (latest_row["d"] if latest_row else "") or ""
        finally:
            conn.close()

        # 当前正在投广的子ASIN集合 (判定基准: 系统当前日期 + 活动起止期间)
        active_asins, base_date = AdsService.active_asins_by_campaign()

        # 广告活动 → 最新非空每日预算
        camp_budget: Dict[str, str] = {}
        for c in crows:
            v = _cell_str(c["daily_budget"])
            if v:
                camp_budget[c["name"] or ""] = v

        # 广告组 → 所属活动 / 最新默认竞价 / 子ASIN
        group_camp: Dict[str, str] = {}
        group_bid: Dict[str, str] = {}
        group_asin: Dict[str, str] = {}
        for g in grows:
            name = g["name"] or ""
            if name not in group_camp:
                group_camp[name] = g["campaign_name"] or ""
            a = _cell_str(g["product_asin"])
            if not a:
                m = ASIN_RE.search(g["campaign_name"] or "")
                a = m.group(0) if m else ""
            if a and name not in group_asin:
                group_asin[name] = a
            try:
                gd = json.loads(g["data"] or "{}")
            except Exception:
                gd = {}
            bid = _strip_currency(gd.get("默认竞价"))
            if bid:
                group_bid[name] = bid

        # 品级标记: 同一子ASIN只要有任一广告组被标记, 该ASIN的所有广告组都按标记值统计
        # (否则同一品会因"一条组已标记、一条未标记"被拆进两个组合 → 误报重复ASIN)
        asin_mark: Dict[str, Tuple[str, str]] = {}
        for name in group_camp:
            mk = marks.get(name)
            if not mk:
                continue
            nb, nbid = _cell_str(mk["new_budget"]), _cell_str(mk["new_bid"])
            if not (nb or nbid):
                continue
            a = group_asin.get(name, "")
            if not a:
                continue
            cur = asin_mark.get(a)
            # 多条标记并存时取"更完整"的一条 (两个字段都填优于只填一个)
            if cur is None or (sum(1 for x in (nb, nbid) if x) > sum(1 for x in cur if x)):
                asin_mark[a] = (nb, nbid)

        # 参数组合 = (生效每日预算, 生效默认竞价); 已录入新值优先, 否则用当前值
        combos: Dict[Tuple[str, str], List[Dict[str, str]]] = defaultdict(list)
        for name, camp in group_camp.items():
            mk = marks.get(name)
            new_budget = _cell_str(mk["new_budget"]) if mk else ""
            new_bid = _cell_str(mk["new_bid"]) if mk else ""
            a = group_asin.get(name, "")
            if a and not (new_budget or new_bid):
                # 该组自身未标记, 但同品的其它广告组已标记 → 按品级标记值统计
                new_budget, new_bid = asin_mark.get(a, ("", ""))
            budget = _norm_num(new_budget or camp_budget.get(camp, ""))
            bid = _norm_num(new_bid or group_bid.get(name, ""))
            combos[(budget, bid)].append({"asin": a, "name": name})

        combo_rows = []
        for (budget, bid), items in sorted(combos.items(), key=lambda kv: -len(kv[1])):
            clean = list(dict.fromkeys(it["asin"] for it in items if it["asin"]))   # 同品去重
            combo_rows.append({
                "new_budget": budget,
                "new_bid": bid,
                "count": len(items),
                "asin_list": clean,
                "asins": ",".join(clean),
            })

        # 父SKU层级: 该父SKU下所有子ASIN都没有正在投的广告活动 => 该父SKU未投广, 取其中一个子ASIN作代表
        parent_groups: Dict[str, List[str]] = defaultdict(list)
        for p in prows:
            asin = _cell_str(p["asin"])
            if not asin:
                continue
            key = _cell_str(p["parent_sku"]) or asin      # 无父SKU的独立品自成一组
            parent_groups[key].append(asin)
        un_items: List[Dict[str, Any]] = []           # 未投广父SKU: 每个父SKU一个代表ASIN
        for key, asins in parent_groups.items():
            if any(a in active_asins for a in asins):
                continue
            rep = asins[0]
            un_items.append({
                "asin": rep,
                "parent_sku": "" if key == rep else key,
                "children": len(set(asins)),
            })
        un_items.sort(key=lambda x: x["asin"])
        un_asins = [x["asin"] for x in un_items]

        # 重复项: 在「各组合 + 未投广代表ASIN」中出现次数 > 1 的 ASIN
        # (前端会把自定义分组与已清除项一并纳入重算)
        counter: Dict[str, int] = defaultdict(int)
        for c in combo_rows:
            for a in c["asin_list"]:
                counter[a] += 1
        for a in un_asins:
            counter[a] += 1
        duplicates = sorted(a for a, n in counter.items() if n > 1)

        # ── 覆盖检查: 分组(组合+未投广)覆盖到的父ASIN 与「在线产品-父」总量比对 ──
        # 父ASIN 口径与「在线产品-父」一致: parent_asin 为空则自成一组
        asin_parent: Dict[str, str] = {}
        parent_children: Dict[str, List[str]] = defaultdict(list)
        parent_sku_of: Dict[str, str] = {}
        for p in prows:
            a = _cell_str(p["asin"])
            if not a:
                continue
            pa = _cell_str(p["parent_asin"]) or a
            asin_parent[a] = pa
            parent_children[pa].append(a)
            if pa not in parent_sku_of and _cell_str(p["parent_sku"]):
                parent_sku_of[pa] = _cell_str(p["parent_sku"])
        covered_parents = set()
        for c in combo_rows:
            for a in c["asin_list"]:
                if a in asin_parent:
                    covered_parents.add(asin_parent[a])
        for a in un_asins:
            if a in asin_parent:
                covered_parents.add(asin_parent[a])
        missing = []
        for pa in sorted(set(parent_children) - covered_parents):
            kids = parent_children[pa]
            in_active = [k for k in kids if k in active_asins]
            if in_active:
                reason = "有正在投的广告活动，但广告组报表里没有该ASIN的数据"
            else:
                reason = "广告组报表与广告活动报表均未覆盖该ASIN"
            missing.append({
                "parent_asin": pa,
                "parent_sku": parent_sku_of.get(pa, ""),
                "rep_asin": kids[0],
                "children": kids,
                "children_count": len(kids),
                "active_children": in_active,
                "reason": reason,
            })

        return {
            "latest_date": latest_date,
            "base_date": base_date,
            "active_total": len(active_asins),
            "group_total": sum(len(v) for v in combos.values()),
            "combo_total": len(combo_rows),
            "marked_total": sum(1 for m in marks.values() if m["new_budget"] or m["new_bid"]),
            "duplicates": duplicates,
            "combos": combo_rows,
            "coverage": {
                "parent_total": len(parent_children),          # 在线产品-父 的父ASIN总数
                "auto_covered": len(covered_parents),          # 组合+未投广 已覆盖的父ASIN数
                "missing": missing,                            # 未覆盖的父ASIN明细与原因
                "asin_parent": asin_parent,                    # asin → 父ASIN (前端按自定义分组/清除项复核)
            },
            "unadvertised": {
                "count": len(un_items),
                "parent_sku_total": len(parent_groups),
                "asin_list": un_asins,
                "asins": ",".join(un_asins),
                "items": un_items,
            },
        }

    # ─────────────────────────── 广告研判: 人工标记 ───────────────────────────

    @staticmethod
    def clear_group_marks() -> Dict[str, Any]:
        """清除全部人工标记 (所有行的新每日预算/新默认竞价一并清空)"""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) c FROM ads_group_marks WHERE marked = 1;")
            n = cursor.fetchone()["c"] or 0
            cursor.execute("DELETE FROM ads_group_marks;")
            conn.commit()
            return {"cleared": n}
        finally:
            conn.close()

    @staticmethod
    def save_group_marks(group_names: List[str], new_budget: str = "", new_bid: str = "") -> Dict[str, Any]:
        """批量设置多条广告组的新每日预算/新默认竞价; 某项留空则保留该行原值"""
        names = [_cell_str(n) for n in (group_names or []) if _cell_str(n)]
        if not names:
            raise ValueError("未选择任何广告组")
        budget = _cell_str(new_budget)
        bid = _cell_str(new_bid)
        if not budget and not bid:
            raise ValueError("新每日预算与新默认竞价至少填写一项")
        now = _now()
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            for name in names:
                cursor.execute("SELECT new_budget, new_bid FROM ads_group_marks WHERE group_name = ?;", (name,))
                old = cursor.fetchone()
                nb = budget or (_cell_str(old["new_budget"]) if old else "")
                nbid = bid or (_cell_str(old["new_bid"]) if old else "")
                cursor.execute("""
                    INSERT INTO ads_group_marks (group_name, new_budget, new_bid, marked, update_time)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(group_name) DO UPDATE SET
                        new_budget=excluded.new_budget, new_bid=excluded.new_bid,
                        marked=excluded.marked, update_time=excluded.update_time;
                """, (name, nb, nbid, 1 if (nb or nbid) else 0, now))
            conn.commit()
            return {"updated": len(names), "new_budget": budget, "new_bid": bid}
        finally:
            conn.close()

    @staticmethod
    def save_group_mark(group_name: str, new_budget: str = "", new_bid: str = "") -> Dict[str, Any]:
        """保存某广告组的"新每日预算/新默认竞价"; 任一有值即为已标记"""
        name = _cell_str(group_name)
        if not name:
            raise ValueError("广告组名不能为空")
        budget = _cell_str(new_budget)
        bid = _cell_str(new_bid)
        is_marked = 1 if (budget or bid) else 0
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO ads_group_marks (group_name, new_budget, new_bid, marked, update_time)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(group_name) DO UPDATE SET
                    new_budget=excluded.new_budget, new_bid=excluded.new_bid,
                    marked=excluded.marked, update_time=excluded.update_time;
            """, (name, budget, bid, is_marked, _now()))
            conn.commit()
            return {"group_name": name, "new_budget": budget, "new_bid": bid, "marked": bool(is_marked)}
        finally:
            conn.close()
