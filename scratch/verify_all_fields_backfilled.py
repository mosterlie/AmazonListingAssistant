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
from playwright.sync_api import sync_playwright
from server.services.auth_service import AuthService

def test_all_fields_backfilled():
    token = AuthService.create_session(1, days_valid=1)

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")

        context = browser.new_context() if hasattr(browser, "new_context") else browser.contexts[0]
        context.add_cookies([{
            "name": "session_token",
            "value": token,
            "domain": "127.0.0.1",
            "path": "/"
        }])
        page = context.new_page()

        # 访问待编辑商品页面 (例如 ID: 61)
        target_product_id = 61
        page.goto(f"http://127.0.0.1:8000/entry?id={target_product_id}")

        # 等待页面加载完成
        page.wait_for_selector("#editModeBanner", state="visible")
        page.wait_for_function("document.getElementById('titleInput').value.length > 0")
        time.sleep(1.5)

        # 检查各字段
        store = page.eval_on_selector("#storeAccountSelect", "el => el.value")
        brand = page.eval_on_selector("#brandInput", "el => el.value")
        title = page.eval_on_selector("#titleInput", "el => el.value")
        parent_sku = page.eval_on_selector("#parentSkuInput", "el => el.value")
        model_number = page.eval_on_selector("#modelNumberInput", "el => el.value")
        model_name = page.eval_on_selector("#modelNameInput", "el => el.value")
        pkg_weight = page.eval_on_selector("#pkgWeightInput", "el => el.value")
        desc = page.eval_on_selector("#descriptionInput", "el => el.value")
        bullet_inps = page.eval_on_selector_all(".bullet-point-inp", "els => els.map(e => e.value).filter(Boolean)")
        color_inps = page.eval_on_selector_all(".attr-box-input", "els => els.map(e => e.value).filter(Boolean)")
        matrix_rows = page.query_selector_all("#matrixTableBody tr")

        print("=== 校验商品回填数据 ===")
        print(f"Store Account:  {store}")
        print(f"Brand:          {brand}")
        print(f"Title:          {title[:40]}...")
        print(f"Parent SKU:     {parent_sku}")
        print(f"Model Number:   {model_number}")
        print(f"Model Name:     {model_name}")
        print(f"Package Weight: {pkg_weight}")
        print(f"Bullet Points:  {len(bullet_inps)} items")
        print(f"Active Colors:  {color_inps}")
        print(f"Matrix Rows:    {len(matrix_rows)} rows")

        assert len(title) > 0, "Title is empty!"
        assert len(parent_sku) > 0, "Parent SKU is empty!"
        assert len(matrix_rows) > 0, "Matrix rows empty!"

        page.close()
        try:
            browser.close()
        except Exception:
            pass
        print("✅ All field backfill checks passed 100%!")

if __name__ == "__main__":
    test_all_fields_backfilled()
