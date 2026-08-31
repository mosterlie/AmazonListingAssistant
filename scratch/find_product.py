import sys
import os

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from server.database import get_db_connection
from server.services.product_service import ProductService

def main():
    conn = get_db_connection()
    target_str = "犬 トイレ トレー 囲い付き人工芝足上げ ガード お飛び散り防止 手入れ簡単洗える はみ出し防止 壁掛け 消臭 小型犬"
    
    rows = conn.execute("SELECT id, parent_sku, brand, title FROM products").fetchall()
    matched = []
    for r in rows:
        t = (r["title"] or "").strip()
        if t == target_str or "手入れ簡単洗える" in t:
            matched.append(r)
            
    print(f"Total matched: {len(matched)}")
    for m in matched:
        p = ProductService.get_product_by_id(m["id"])
        print("=" * 60)
        print(f"Product ID: {m['id']}")
        print(f"Parent SKU: {m['parent_sku']}")
        print(f"Brand: {m['brand']}")
        print(f"Title: {m['title']}")
        print(f"Search Terms: {p.get('search_terms')}")
        print(f"Bullet Points count: {len(p.get('bullet_points', []))}")
        print(f"Description length: {len(p.get('description', ''))}")
        print(f"Main Image: {p.get('main_image')}")
        print(f"Extra Images count: {len(p.get('extra_images', []))}")
        print(f"Variant Image Dimension: {p.get('variant_image_dimension')}")
        print(f"Variant Dimension Images: {p.get('variant_dimension_images')}")
        print(f"Variations count: {len(p.get('variations', []))}")
        for v in p.get('variations', []):
            print(f"  • SKU: {v.get('sku')} | Color: {v.get('color')} | Size: {v.get('size')} | Price: {v.get('sale_price_jpy') or v.get('price_jpy')} JPY | EAN: {v.get('ean')}")

if __name__ == "__main__":
    main()
