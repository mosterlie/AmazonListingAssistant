"""ASIN 池重复检查: 同父重复行 / 子ASIN多父冲突 / 父体嵌套 / 跨批次重复"""
import io
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from openpyxl import Workbook

import server.services.asin_pool_service as svc

tmp = tempfile.mkdtemp()
db_path = Path(tmp) / "test.db"
conn0 = sqlite3.connect(db_path)
conn0.row_factory = sqlite3.Row
conn0.executescript("""
CREATE TABLE asin_import_batches (id INTEGER PRIMARY KEY AUTOINCREMENT, imported_at TEXT,
  filename TEXT, excel_rows INTEGER, pair_count INTEGER, parent_count INTEGER, imported_by TEXT);
CREATE TABLE asin_parent_child (id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER,
  parent TEXT, child TEXT, UNIQUE(batch_id, parent, child));
CREATE TABLE asin_query_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, queried_at TEXT, batch_id INTEGER,
  input_count INTEGER, result_count INTEGER, input_asins_json TEXT, result_asins_json TEXT,
  ignored_asins_json TEXT, created_by TEXT);
""")
conn0.commit()
conn0.close()


def _tmp_conn():
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    return c


svc.get_db_connection = _tmp_conn
sys.modules["server.services.asin_pool_service"].get_db_connection = _tmp_conn

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS  " if cond else "FAIL  ") + name + (f"  <- {detail}" if detail and not cond else ""))


def make_xlsx(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(["父ASIN", "ASIN"])
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# 批次1: 正常 + 同父重复行(出现2次) + 子归多父 + 父体嵌套
rows1 = [
    ("B0PA000001", "B0C0000001"),
    ("B0PA000001", "B0C0000002"),
    ("B0PA000001", "B0C0000001"),          # 同父重复行 ×2
    ("B0PA000002", "B0C0000002"),          # B0C0000002 归属两个父体
    ("B0PA000003", "B0PA000001"),          # 父体 B0PA000001 同时是本父的子 (嵌套)
    ("B0PA000003", "B0C0000003"),
]
d1 = svc.AsinPoolService.import_excel("b1.xlsx", make_xlsx(rows1), operator="t")
dc1 = d1["duplicate_check"]
check("批次1 同父重复行 1 项 ×2", dc1["same_parent_dup"]["count"] == 1 and
      dc1["same_parent_dup"]["items"][0][1] == 2, str(dc1["same_parent_dup"]))
check("批次1 子ASIN归多父 1 项 (B0C0000002→两父)", dc1["child_multi_parent"]["count"] == 1 and
      sorted(dc1["child_multi_parent"]["items"][0][1]) == ["B0PA000001", "B0PA000002"], str(dc1["child_multi_parent"]))
check("批次1 父体嵌套 1 项 (B0PA000001)", dc1["parents_also_child"]["count"] == 1 and
      dc1["parents_also_child"]["items"] == ["B0PA000001"], str(dc1["parents_also_child"]))
check("批次1 跨批次重复 0 项", dc1["cross_batch_dup_children"]["count"] == 0)
check("批次1 入库对数去重 = 5", d1["pair_count"] == 5, str(d1["pair_count"]))

# 批次2: 含批次1已有的子ASIN → 跨批次重复
rows2 = [("B0PA000009", "B0C0000001"), ("B0PA000009", "B0X0000001")]
d2 = svc.AsinPoolService.import_excel("b2.xlsx", make_xlsx(rows2), operator="t")
dc2 = d2["duplicate_check"]
check("批次2 跨批次重复 1 项 (B0C0000001)", dc2["cross_batch_dup_children"]["count"] == 1 and
      dc2["cross_batch_dup_children"]["items"] == ["B0C0000001"], str(dc2["cross_batch_dup_children"]))
check("批次2 本批内无其他异常", dc2["same_parent_dup"]["count"] == 0 and
      dc2["child_multi_parent"]["count"] == 0 and dc2["parents_also_child"]["count"] == 0)

# check_duplicates: 默认最新批次(2), 指定批次(1)
cd = svc.AsinPoolService.check_duplicates()
check("check_duplicates 默认最新批次 #2 跨批重复 1 项", cd["batch_id"] == 2 and
      cd["duplicate_check"]["cross_batch_dup_children"]["count"] == 1)
cd1b = svc.AsinPoolService.check_duplicates(batch_id=1)
check("check_duplicates 指定批次 #1 同父重复行在库内不再计 (库已去重)", cd1b["duplicate_check"]["same_parent_dup"]["count"] == 0)
check("批次1 库内查重仍检出多父+嵌套", cd1b["duplicate_check"]["child_multi_parent"]["count"] == 1 and
      cd1b["duplicate_check"]["parents_also_child"]["count"] == 1)

print(f"\n结果: PASS {len(PASS)} / FAIL {len(FAIL)}")
sys.exit(1 if FAIL else 0)
