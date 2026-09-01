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

def verify_ui_edit():
    # 创建一个有效的 session token
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

        # 1. 访问商品列表
        page.goto("http://127.0.0.1:8000/list")
        page.wait_for_selector("#productListTableBody tr")
        print("[1] List page loaded successfully.")

        # 检查是否包含编辑按钮
        edit_links = page.query_selector_all("#productListTableBody a:has-text('编辑')")
        print(f"[2] Found {len(edit_links)} edit buttons on list page.")
        assert len(edit_links) > 0, "No edit button found in product rows!"

        # 点击第一个编辑按钮
        first_edit_btn = edit_links[0]
        href = first_edit_btn.get_attribute("href")
        print(f"[3] Clicking first edit button with href: {href}")
        first_edit_btn.click()

        # 等待跳转至 /entry 页面
        page.wait_for_url("**/entry?id=*")
        print(f"[4] Navigated to edit page: {page.url}")

        # 等待表单数据回填
        page.wait_for_selector("#editModeBanner", state="visible")
        page.wait_for_function("document.getElementById('titleInput').value.length > 0")
        time.sleep(1)

        title_val = page.eval_on_selector("#titleInput", "el => el.value")
        parent_sku_val = page.eval_on_selector("#parentSkuInput", "el => el.value")
        var_rows = page.query_selector_all("#matrixTableBody tr")

        print(f"[5] Edit page populated successfully:")
        print(f"    - Title: {title_val[:35]}...")
        print(f"    - Parent SKU: {parent_sku_val}")
        print(f"    - Matrix Rows: {len(var_rows)}")

        assert len(var_rows) > 0, "Variation matrix rows not populated!"

        # 修改标题并保存
        test_suffix = f" (UI校验 {int(time.time()) % 1000})"
        page.fill("#titleInput", title_val + test_suffix)

        save_btn = page.query_selector("#saveProductBtn")
        assert save_btn is not None
        print(f"[6] Clicking '{save_btn.text_content().strip()}' button...")
        save_btn.click()

        # 等待保存完成并跳转回 /list
        page.wait_for_url("**/list", timeout=10000)
        page.wait_for_selector("#productListTableBody tr")
        print(f"[7] Successfully redirected back to /list after saving edit!")

        page.close()
        try:
            browser.close()
        except Exception:
            pass
        print("[SUCCESS] All UI edit flow verifications passed cleanly!")

if __name__ == "__main__":
    verify_ui_edit()
