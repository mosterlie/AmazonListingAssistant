import sys
import os
import json

sys.path.insert(0, os.path.abspath("."))
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from browser_engine import BrowserEngine

def inspect_first_sku_menu():
    engine = BrowserEngine(9222)
    engine.connect(activate=False)

    def run():
        p = [page for page in engine.manager.context.pages if page.locator('#variationImage').count() > 0][0]
        
        h1 = p.locator('#variationImage .item-header').first
        h1.scroll_into_view_if_needed()
        p.wait_for_timeout(300)
        
        h1_text = h1.inner_text()
        print('Header 1 text:', h1_text)

        apply_btn = h1.locator("span.link, a, span[class*='link'], [class*='apply']").filter(has_text="图片应用到").first
        print('Apply button count:', apply_btn.count())
        apply_btn.click(force=True)
        p.wait_for_timeout(500)

        menu_info = p.evaluate("""
        () => {
            const dropdowns = Array.from(document.querySelectorAll('.ant-dropdown:not([style*="display: none"])'));
            const items = [];
            dropdowns.forEach((dd, ddi) => {
                const lis = Array.from(dd.querySelectorAll('li, .ant-dropdown-menu-item, .ant-dropdown-menu-submenu-title, div'));
                lis.forEach((li, lii) => {
                    const rect = li.getBoundingClientRect();
                    const txt = li.innerText.trim();
                    if (txt && rect.width > 0 && rect.height > 0) {
                        items.push({
                            dropdownIdx: ddi,
                            itemIdx: lii,
                            tag: li.tagName,
                            text: txt,
                            className: li.className,
                            rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
                        });
                    }
                });
            });
            return {
                dropdownCount: dropdowns.length,
                dropdownHtml: dropdowns.map(d => d.outerHTML),
                items: items
            };
        }
        """)
        p.keyboard.press("Escape")
        return menu_info

    res = engine.manager.run_on_browser_thread(run)
    print("Dropdown Count:", res["dropdownCount"])
    for html in res["dropdownHtml"]:
        print("\n--- DROPDOWN HTML ---")
        print(html)
    print("\n--- VISIBLE ITEMS ---")
    for it in res["items"]:
        print(f"Tag: {it['tag']} | Class: {it['className']} | Text: {it['text']} | Pos: ({it['rect']['x']}, {it['rect']['y']})")

if __name__ == '__main__':
    inspect_first_sku_menu()
