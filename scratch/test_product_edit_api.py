import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import requests
import json

BASE_URL = "http://127.0.0.1:8000"

def test_product_edit():
    # 1. 获取商品列表
    res = requests.get(f"{BASE_URL}/api/products?limit=5")
    assert res.status_code == 200, f"List failed: {res.text}"
    data = res.json()
    assert data["code"] == 0
    products = data["data"]
    if not products:
        print("No products in DB to test edit.")
        return

    target = products[0]
    target_id = target["id"]
    print(f"Testing edit on Product #{target_id}, title: {target.get('title')}")

    # 2. 获取商品详情
    res_detail = requests.get(f"{BASE_URL}/api/products/{target_id}")
    assert res_detail.status_code == 200, f"Detail failed: {res_detail.text}"
    detail = res_detail.json()["data"]
    old_title = detail["title"]

    # 3. 构造更新 Payload
    new_title = old_title if " [已编辑]" in old_title else f"{old_title} [已编辑]"
    detail["title"] = new_title
    detail["item_length"] = 28.5

    res_put = requests.put(f"{BASE_URL}/api/products/{target_id}", json=detail)
    assert res_put.status_code == 200, f"PUT failed: {res_put.text}"
    put_data = res_put.json()
    assert put_data["code"] == 0, f"PUT error: {put_data}"
    updated = put_data["data"]
    assert updated["id"] == target_id, f"ID changed! {updated['id']} != {target_id}"
    assert updated["title"] == new_title, f"Title not updated! {updated['title']}"
    assert updated["item_length"] == 28.5

    print(f"[SUCCESS] Product #{target_id} successfully updated via PUT /api/products/{target_id}!")
    print(f"   Updated title: {updated['title']}")
    print(f"   Updated item_length: {updated['item_length']}")
    print(f"   Variation count: {len(updated.get('variations', []))}")

if __name__ == "__main__":
    test_product_edit()
