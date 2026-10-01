# -*- coding: utf-8 -*-
"""广告分析(复刻版)后端全流程验证 — 使用临时DB, 不影响正式库"""
import os, sys, tempfile, glob
sys.path.insert(0, '/Users/gx/Desktop/mypro/browser_toolkit')

import server.database as appdb
_tmp = tempfile.mkdtemp(prefix="ads_test_")
appdb.DB_PATH = os.path.join(_tmp, "test.db")
appdb.init_db()

from server.services.ads_service import AdsService

SRC = "/Users/gx/Desktop/mypro/adsAnalysis/广告分析"
files = glob.glob(os.path.join(SRC, "*.xlsx"))
prod = next(f for f in files if "productListing" in f)
camp = next(f for f in files if "广告活动" in f)
grp = next(f for f in files if "广告组" in f)


def read(p):
    with open(p, "rb") as fh:
        return fh.read()


print("[1] 导入")
print("  在线产品:", AdsService.import_products(read(prod))["count"])
print("  广告活动:", AdsService.import_campaigns(read(camp))["count"])
print("  广告组:", AdsService.import_groups(read(grp))["count"])
print("[2] 关联:", {k: v for k, v in AdsService.link_data().items() if k != "unmatched_asins"})
st = AdsService.get_status()
print("[3] 状态:", {k: st[k] for k in ("products", "campaigns", "groups")}, st["link"])

p = AdsService.get_products(keyword="B0H", page=1, page_size=5)
print(f"[4] 产品-子: total={p['total']} fields={len(p['fields'])} defaults={len(p['defaults'])}")
par = AdsService.get_parents()
print(f"[5] 产品-父: total={par['total']} latest_date={par['latest_date']} 在投={sum(1 for x in par['rows'] if x['是否在投']=='是')}")

r1 = AdsService.get_research(days="1", page=1, page_size=20)
print(f"[6] 研判(近1天): total={r1['total']} 本页={len(r1['rows'])} 列={len(r1['fields'])} range={r1['range']}")
row = r1["rows"][0]
print("    样例行键:", [k for k in ("广告组名","图片","子ASIN","数据日期","打广天数","活动开始日期","新每日预算","是否标记","广告花费") if k in row])
r2 = AdsService.get_research(days="", sort="广告花费", order="desc", page=2, page_size=10)
print(f"[7] 研判(全部/按花费排序/第2页): total={r2['total']} 本页={len(r2['rows'])}")

print("[8] 标记: 单条")
name = row["广告组名"]
print("   ", AdsService.save_group_mark(name, "500", "18"))
print("    批量:", AdsService.save_group_marks([x["广告组名"] for x in r1["rows"][:3]], new_budget="800", new_bid=""))
mk = AdsService.get_research(days="1", marked="1", page=1, page_size=50)
print(f"    已标记筛选: total={mk['total']} marked_total={mk['marked_total']}")
s = AdsService.get_stats()
print(f"[9] 统计: 组合={s['combo_total']} 组覆盖={s['group_total']} 未投广={s['unadvertised']['count']} 重复ASIN={len(s['duplicates'])}")
print("    组合示例:", s["combos"][0] if s["combos"] else None)
print("[10] 清除标记:", AdsService.clear_group_marks())
print("[11] 清空全部:", AdsService.clear_all())
print("[12] 清空后状态:", {k: AdsService.get_status()[k]["count"] for k in ("products", "campaigns", "groups")})
print("\nOK 全流程通过, 临时库:", appdb.DB_PATH)
