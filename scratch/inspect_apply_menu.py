import sys
import os
sys.path.insert(0, os.path.abspath("."))
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from browser_engine import BrowserEngine

e = BrowserEngine(port=9222)
ok, _ = e.connect(activate=False)

def inspect_apply_menu():
    def _action():
        page = e.manager._get_active_page_impl()
        # 点击第 1 个卡片的图片应用到
        first_header = page.locator("#variationImage .item-header").first
        first_header.scroll_into_view_if_needed()
        apply_btn = first_header.locator("span.link, a, [class*='apply']").filter(has_text="图片应用到").first
        apply_btn.click(force=True)
        page.wait_for_timeout(500)

        js_dump_menu = """
        () => {
            const drops = Array.from(document.querySelectorAll('.product-image-apply-menu, .ant-dropdown'));
            const res = [];
            for (const d of drops) {
                if (getComputedStyle(d).display === 'none') continue;
                const groups = Array.from(d.querySelectorAll('.menu-group, [class*="group"], li, ul, div'));
                res.push({
                    className: d.className,
                    html: d.outerHTML.slice(0, 1500),
                    innerText: d.innerText
                });
            }
            return res;
        }
        """
        menu_info = page.evaluate(js_dump_menu)
        return menu_info

    return e.manager.run_on_browser_thread(_action)

info = inspect_apply_menu()
print(f"Dropdown menu info:\n{info}")
