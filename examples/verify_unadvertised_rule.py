# -*- coding: utf-8 -*-
"""校验「当前未投广」新口径 (活动维度) — 只读真实库"""
import sys, json, sqlite3
sys.path.insert(0, '/Users/gx/Desktop/mypro/browser_toolkit')
from server.services.ads_service import AdsService, _cell_num, _norm_date
from server.database import DB_PATH

active, base = AdsService.active_asins_by_campaign()
print(f"判定基准日期: {base}")
print(f"正在投广的子ASIN: {len(active)}")

# 旧口径(当天实际投放)对比
conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("SELECT MAX(date) d FROM ads_groups;")
latest = c.fetchone()["d"]
old = set()
c.execute("SELECT product_asin, data FROM ads_groups WHERE date = ?;", (latest,))
for r in c.fetchall():
    a = r["product_asin"] or ""
    if a and any(_cell_num(json.loads(r["data"] or "{}").get(k)) for k in ("广告曝光量", "广告点击量", "广告花费")):
        old.add(a)
c.execute("SELECT COUNT(*) n FROM ads_products;")
prod_n = c.fetchone()["n"]
conn.close()
print(f"旧口径(数据最新日 {latest} 实际投放): {len(old)}")
print(f"口径变化: 新增在投 {len(active - old)} 个, 不再算在投 {len(old - active)} 个")

st = AdsService.get_stats()
print(f"\n统计结果: 未投广父SKU {st['unadvertised']['count']} 个 / 父SKU合计 {st['unadvertised']['parent_sku_total']}"
      f" | 组合 {st['combo_total']} | 在投ASIN {st['active_total']} | 重复ASIN {len(st['duplicates'])}")
print("未投广代表ASIN 前8个:", st["unadvertised"]["asin_list"][:8])
print("判定依据(base_date):", st["base_date"])

# 抽检: 在投集合中每个ASIN都能找到「未暂停 且 今天在起止期间内」的活动
conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("SELECT name, date, state, service_state, product_asin, data FROM ads_campaigns ORDER BY date ASC, id ASC;")
info = {}
for r in c.fetchall():
    n = r["name"]
    it = info.setdefault(n, {})
    if r["state"]: it["state"] = r["state"]
    if r["service_state"]: it["svc"] = r["service_state"]
    it["asin"] = r["product_asin"] or it.get("asin", "")
    d = json.loads(r["data"] or "{}")
    for k in ("开始日期", "结束日期"):
        v = _norm_date(d.get(k))
        if v: it[k] = v
    it.setdefault("first", _norm_date(r["date"])); it["last"] = _norm_date(r["date"])
conn.close()
bad = []
for name, it in info.items():
    if it.get("state") and any(w in it["state"] for w in ("已暂停", "已结束", "已关闭", "暂停")):
        continue
    start = it.get("开始日期") or it.get("first")
    end = it.get("结束日期") or ""
    if (start and base < start) or (end and base > end):
        continue
    if it.get("asin") and it["asin"] not in active:
        bad.append((name, it.get("asin")))
print(f"\n抽检: 应判在投但集合中缺失的活动数 = {len(bad)}", bad[:3])

paused = [n for n, it in info.items() if it.get("state") == "已暂停"]
p_asins = {info[n].get("asin") for n in paused}
print(f"暂停活动 {len(paused)} 个, 其ASIN中仍被判在投的: {len(p_asins & active)} (应为0)")
