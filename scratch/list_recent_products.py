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
    rows = conn.execute("SELECT id, parent_sku, brand, title FROM products ORDER BY id DESC LIMIT 50").fetchall()
    print(f"Latest {len(rows)} products in DB:")
    for r in rows:
        p = ProductService.get_product_by_id(r["id"])
        var_count = len(p.get("variations", []))
        print(f"ID: {r['id']} | Parent SKU: {r['parent_sku']} | Brand: {r['brand']} | Variations: {var_count} | Title: {r['title'][:60]}")

if __name__ == "__main__":
    main()
