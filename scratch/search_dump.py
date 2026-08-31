import json

def main():
    with open("scratch/product_items_dump.json", "r", encoding="utf-8") as f:
        items = json.load(f)

    for x in items:
        t = x.get("title") or ""
        sku = x.get("parent_sku") or ""
        v_count = len(json.loads(x.get("variations_json") or "[]"))
        print(f"ID: {x.get('id')} | SKU: {sku} | Variations: {v_count} | Title: {t}")

if __name__ == "__main__":
    main()
