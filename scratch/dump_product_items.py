import sys
import os
import json

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from server.database import get_db_connection

def main():
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM product_items").fetchall()
    
    data = []
    target_str = "犬 トイレ トレー 囲い付き人工芝足上げ ガード お飛び散り防止 手入れ簡単洗える はみ出し防止 壁掛け 消臭 小型犬"
    for r in rows:
        d = dict(r)
        d["exact_match"] = (d.get("title") or "").strip() == target_str
        data.append(d)
        
    with open(os.path.join(CURRENT_DIR, "product_items_dump.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Dumped {len(data)} product_items to scratch/product_items_dump.json")

if __name__ == "__main__":
    main()
