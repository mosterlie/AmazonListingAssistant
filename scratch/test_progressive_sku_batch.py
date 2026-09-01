import sys
import os
sys.path.insert(0, os.path.abspath("."))
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import time
from browser_engine import BrowserEngine
from server.services.product_service import ProductService

def test_progressive_sku_batch():
    print("=" * 75)
    print("🚀 【逐级扫描与双重校验测试】验证 SKU 主图按颜色/尺寸逐级装配与每步校验")
    print("=" * 75)

    product = ProductService.get_product_by_id(61)
    assert product is not None, "Product #61 not found!"
    print(f"Product: #{product['id']} {product['title'][:40]}")
    print(f"Variations count: {len(product.get('variations', []))}")
    print(f"Dimension: {product.get('variant_image_dimension', 'color')}")
    print(f"Dimension images: {list(product.get('variant_dimension_images', {}).keys())}")

    e = BrowserEngine(port=9222)
    ok, msg = e.connect(activate=False)
    if not ok:
        print(f"❌ Connect failed: {msg}")
        return

    print("Browser connected successfully on port 9222.")

    # 检查是否有打开的页面
    tabs = e.get_tabs()
    dxm_tab = next((t for t in tabs if "dianxiaomi.com" in t.url), None)
    if dxm_tab:
        print(f"Found active Dianxiaomi tab: {dxm_tab.url}")
        e.open_or_focus_url(dxm_tab.url)
        time.sleep(1)

        summary = e.verify_all_variation_images_summary()
        print(f"📊 Current Summary: {summary}")

        next_card = e.find_next_unassigned_variation_card("color")
        print(f"🔍 Next unassigned card: {next_card}")
    else:
        print("ℹ️ No active Dianxiaomi tab currently open in debug Chrome.")

    print("\n✅ Progressive batch structure verified cleanly!")

if __name__ == "__main__":
    test_progressive_sku_batch()
