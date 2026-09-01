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

def inspect_dropdown():
    def _action():
        page = e.manager._get_active_page_impl()
        # 点击第 1 个卡片的图片应用到
        headers = page.locator("#variationImage .item-header")
        if headers.count() == 0:
            print("页面无变体卡片")
            return
        
        btn = headers.first.locator("span.link, a, [class*='apply']").filter(has_text="图片应用到").first
        btn.click(force=True)
        page.wait_for_timeout(500)

        js = """
        () => {
            const drops = Array.from(document.querySelectorAll('.product-image-apply-menu, .ant-dropdown'));
            const list = [];
            for (const d of drops) {
                if (getComputedStyle(d).display === 'none') continue;
                const items = Array.from(d.querySelectorAll('*')).map(el => ({
                    tagName: el.tagName,
                    className: el.className,
                    text: el.innerText ? el.innerText.trim() : ''
                })).filter(x => x.text && x.text.length < 50);
                list.push({
                    className: d.className,
                    items: items
                });
            }
            return list;
        }
        """
        res = page.evaluate(js)
        return res

    return e.manager.run_on_browser_thread(_action)

res = inspect_dropdown()
print(f"Dropdown items: {res}")
