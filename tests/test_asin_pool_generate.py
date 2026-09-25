"""ASIN 生成池 generate() 增强: 输入明细(子SKU→父) / 生成结果父子映射 / 改版截取模式"""
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import server.services.asin_pool_service as svc

# 临时库替换连接工厂
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
# 全部 10 位 ASIN: 父 B0PA000001(5子) / B0PA000002(3子) / 独立 B0SOLO0001
pairs = [("B0PA000001", f"B0C{n:07d}") for n in range(1, 6)] + \
        [("B0PA000002", f"B0K{n:07d}") for n in range(1, 4)] + \
        [("B0SOLO0001", "B0SOLO0001")]
conn0.execute("INSERT INTO asin_import_batches (imported_at, filename, excel_rows, pair_count, parent_count) VALUES ('2026-09-25 10:00:00','t.xlsx',9,9,3)")
conn0.executemany("INSERT INTO asin_parent_child (batch_id, parent, child) VALUES (1,?,?)", pairs)
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


G = svc.AsinPoolService.generate

# 1. 原生版: 输入明细 + 生成结果父子映射
d = G("b0c0000001, B0K0000002, B0XXXX99999", operator="t", mode="native")
check("原生版解析含小写/逗号", d["input_asins"] == ["B0C0000001", "B0K0000002", "B0XXXX99999"], str(d["input_asins"]))
det = {t["asin"]: t for t in d["input_details"]}
check("输入明细: child → 所属父", det["B0C0000001"]["parent"] == "B0PA000001")
check("输入明细: 涉及子SKU=该父全部5个子", det["B0C0000001"]["siblings"] == [f"B0C{n:07d}" for n in range(1, 6)])
check("输入明细: 未在库标记 found=False", det["B0XXXX99999"]["found"] is False and det["B0XXXX99999"]["parent"] is None)
check("命中父体 2 个", d["matched_parents"] == ["B0PA000001", "B0PA000002"])
check("忽略 1 个", d["ignored_asins"] == ["B0XXXX99999"])
rd = {t["asin"]: t["parent"] for t in d["result_details"]}
check("生成结果数 = 未覆盖父体数(仅独立父)", len(d["result_asins"]) == 1)
check("生成结果含 父ASIN 映射", rd.get(d["result_asins"][0]) == "B0SOLO0001", str(rd))
check("生成结果不与输入父体重叠", all(p in ("B0SOLO0001",) for p in rd.values()))

# 2. 改版: 每行截取前10位
text = "B0C0000002-黑色-XXL规格\n  b0k0000001(多行)  \n垃圾行\nB0C0000003\t尾部列,其他"
d2 = G(text, operator="t", mode="variant")
check("改版截取: 每行前10位", d2["input_asins"] == ["B0C0000002", "B0K0000001", "垃圾行", "B0C0000003"], str(d2["input_asins"]))

# 3. 全部父体覆盖: 无生成结果
all_children = ",".join([f"B0C{n:07d}" for n in range(1, 6)] + [f"B0K{n:07d}" for n in range(1, 4)] + ["B0SOLO0001"])
d3 = G(all_children, operator="t", mode="native")
check("父体全覆盖时生成结果为空且 result_details 空", d3["result_asins"] == [] and d3["result_details"] == [], str(d3["result_details"]))

# 4. 非法 mode 回退原生
d4 = G("B0C0000005", operator="t", mode="bogus")
check("非法 mode 回退原生解析", d4["input_asins"] == ["B0C0000005"] and d4["matched_parents"] == ["B0PA000001"])

print(f"\n结果: PASS {len(PASS)} / FAIL {len(FAIL)}")
sys.exit(1 if FAIL else 0)
