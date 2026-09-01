import os
import sys
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine

def test_action():
    e = BrowserEngine(port=9222)
    e.connect()
    
    def run():
        page = e.manager._get_active_page_impl()
        
        # 1. 查找第一个变体卡片
        var_container = page.locator("#variationImage .overflow-y-auto, #variationImage .max-h-700, #variationImage").first
        headers = var_container.locator(".item-header")
        first_header = None
        for i in range(headers.count()):
            h = headers.nth(i)
            btn = h.locator("span.link, a, span[class*='link']").filter(has_text="图片应用到").first
            if btn.count() > 0:
                first_header = h
                break
        
        first_header.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        btn = first_header.locator("span.link, a, span[class*='link']").filter(has_text="图片应用到").first
        btn.click(force=True)
        page.wait_for_timeout(600)
        
        # 2. 找到附图 -> 所有变种
        js_find = """() => {
            const drops = Array.from(document.querySelectorAll('.ant-dropdown'));
            for (const d of drops) {
                if (getComputedStyle(d).display === 'none') continue;
                const groups = d.querySelectorAll('.menu-group');
                for (const g of groups) {
                    const title = (g.querySelector('.group-title')?.innerText || '').trim();
                    if (!title.includes('附图')) continue;
                    for (const it of g.querySelectorAll('.menu-item')) {
                        const txt = (it.innerText || '').trim();
                        if (txt.includes('所有变种') || txt.includes('所有')) {
                            const r = it.getBoundingClientRect();
                            return { found: true, text: txt, x: r.left + r.width/2, y: r.top + r.height/2 };
                        }
                    }
                }
            }
            return { found: false };
        }"""
        res = page.evaluate(js_find)
        print("Found item:", res)
        if res and res.get("found"):
            print(f"Clicking at ({res['x']}, {res['y']})...")
            page.mouse.click(res["x"], res["y"])
            page.wait_for_timeout(1000)
            
            # Check for any modal or confirm dialog
            modals = page.evaluate("""() => {
                const ms = Array.from(document.querySelectorAll('.ant-modal-root, .ant-modal, .ant-modal-confirm, [class*=\"modal\"], [class*=\"dialog\"], [class*=\"confirm\"]'));
                return ms.filter(m => {
                    const style = getComputedStyle(m);
                    return style.display !== 'none' && style.visibility !== 'hidden' && m.offsetHeight > 0;
                }).map(m => ({
                    className: m.className,
                    text: m.innerText.trim()
                }));
            }""")
            print("Visible modals after click:", modals)
            
    e.manager.run_on_browser_thread(run)

if __name__ == "__main__":
    test_action()
