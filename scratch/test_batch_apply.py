import sys
import os
import time

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

from browser_engine import BrowserEngine

def main():
    engine = BrowserEngine(port=9222)
    engine.connect(activate=False)
    page = engine.manager._get_active_page_impl()
    
    def run_test():
        headers = page.locator("#variationImage .item-header")
        print(f"Found {headers.count()} variation image headers")
        
        # 测试点击第 1 个卡片的 '图片应用到'
        btn_apply = headers.first.locator("span.link, a").filter(has_text="图片应用到").first
        if btn_apply.count() > 0:
            btn_apply.scroll_into_view_if_needed()
            btn_apply.click()
            page.wait_for_timeout(400)
            
            opts = page.locator(".ant-dropdown:not([style*='display: none']) .ant-dropdown-menu-item")
            print("Dropdown options found:", opts.count())
            for i in range(opts.count()):
                print(f"  [{i}]:", opts.nth(i).inner_text())
            
            # 点击 '所有变种'
            all_opt = opts.filter(has_text="所有变种").first
            if all_opt.count() > 0:
                all_opt.click()
                print("✅ Successfully applied to all variations!")
                return True
        return False

    res = engine.manager.run_on_browser_thread(run_test)
    print("Result:", res)

if __name__ == "__main__":
    main()
