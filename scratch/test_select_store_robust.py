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

e = BrowserEngine(port=9222)
ok, _ = e.connect(activate=False)

def select_store_native(store_account="飞奔的高压锅", expected_site="日本"):
    def _action():
        page = e.manager._get_active_page_impl()
        
        # 1. 检查是否已经选中
        cur_store = page.locator(".ant-form-item-row:has(label:has-text('店铺账号')) .ant-select-selection-item").inner_text() if page.locator(".ant-form-item-row:has(label:has-text('店铺账号')) .ant-select-selection-item").count() > 0 else ""
        print(f"Initial store: {cur_store}")
        if store_account in cur_store:
            print("Already selected!")
            return True

        # 2. 点击店铺下拉框
        store_trigger = page.locator(".ant-form-item-row:has(label:has-text('店铺账号')) .ant-select-selector").first
        store_trigger.click()
        page.wait_for_timeout(500)

        # 3. 点击选项
        opt = page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option").filter(has_text=store_account).first
        if opt.count() == 0:
            # 兜底选择第一个非空店铺选项
            opt = page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option").first
        
        print(f"Clicking option: {opt.inner_text()}")
        opt.click()
        page.wait_for_timeout(1000)

        # 4. 检查站点选择（若有独立站点下拉框需选择）
        site_sel = page.locator(".ant-form-item-row:has(label:has-text('站点选择')) .ant-select-selection-item")
        site_text = site_sel.inner_text() if site_sel.count() > 0 else ""
        print(f"Site text after store select: {site_text}")

        if expected_site and expected_site not in site_text:
            # 尝试点击站点下拉框
            site_trigger = page.locator(".ant-form-item-row:has(label:has-text('站点选择')) .ant-select-selector").first
            if site_trigger.count() > 0:
                site_trigger.click()
                page.wait_for_timeout(500)
                site_opt = page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option").filter(has_text=expected_site).first
                if site_opt.count() > 0:
                    site_opt.click()
                    page.wait_for_timeout(500)

        final_store = page.locator(".ant-form-item-row:has(label:has-text('店铺账号')) .ant-select-selection-item").inner_text() if page.locator(".ant-form-item-row:has(label:has-text('店铺账号')) .ant-select-selection-item").count() > 0 else ""
        print(f"Final store: {final_store}")
        return bool(store_account in final_store or len(final_store) > 0)

    return e.manager.run_on_browser_thread(_action)

select_store_native("飞奔的高压锅", "日本")
