import sys
import os
import json

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from server.database import get_db_connection
from server.services.product_service import ProductService

def main():
    conn = get_db_connection()
    rows = conn.execute("SELECT id, parent_sku, brand, title FROM products ORDER BY id DESC").fetchall()
    
    res = []
    target_str = "犬 トイレ トレー 囲い付き人工芝足上げ ガード お飛び散り防止 手入れ簡単洗える はみ出し防止 壁掛け 消臭 小型犬"
    for r in rows:
        p = ProductService.get_product_by_id(r["id"])
        item = {
            "id": r["id"],
            "parent_sku": r["parent_sku"],
            "brand": r["brand"],
            "title": r["title"],
            "is_exact_match": (r["title"] or "").strip() == target_str,
            "variations_count": len(p.get("variations", [])),
            "variations": p.get("variations", [])
        }
        res.append(item)
        
    with open(os.path.join(CURRENT_DIR, "db_products_dump.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f"Dumped {len(res)} products to scratch/db_products_dump.json")

if __name__ == "__main__":
    main()
