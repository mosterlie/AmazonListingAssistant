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

def test_batch_pipeline():
    print("=" * 70)
    print("🚀 测试 SKU 图片上传与批量复用深度校验流程")
    print("=" * 70)

    e = BrowserEngine(port=9222)
    ok, msg = e.connect(activate=False)
    if not ok:
        print(f"❌ 浏览器连接失败: {msg}")
        return

    # 检查是否有打开的店小秘页面
    tabs = e.get_tabs()
    dxm_tab = next((t for t in tabs if "dianxiaomi.com" in t.url), None)
    if not dxm_tab:
        print("ℹ️ 当前未发现已打开的店小秘刊登页面，正在加载商品数据准备验证逻辑...")
        # 验证服务层与数据解析
        product = ProductService.get_product_by_id(61)
        assert product is not None, "商品 #61 不存在"
        print(f"✅ 商品 #61 加载成功: {product['title'][:40]}")
        print(f"   变体数量: {len(product.get('variations', []))}")
        print(f"   维度设定: {product.get('variant_image_dimension', 'color')}")
        print(f"   维度图片字典: {product.get('variant_dimension_images', {})}")
        return

    print(f"✅ 找到店小秘页面: {dxm_tab.url}")
    e.open_or_focus_url(dxm_tab.url)
    time.sleep(1)

    summary = e.verify_all_variation_images_summary()
    print(f"📊 初始变体图片概况: {summary}")

if __name__ == "__main__":
    test_batch_pipeline()
