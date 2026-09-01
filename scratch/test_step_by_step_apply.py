import os
import sys
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine

def test_step():
    e = BrowserEngine(port=9222)
    e.connect()
    e.open_or_focus_url("https://www.dianxiaomi.com/web/amazon/add")
    
    def run():
        page = e.manager._get_active_page_impl()
        
        # 1. Click apply button
        header = page.locator("#variationImage .item-header").first
        header.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        
        btn = header.locator("span.link, a, span[class*='link'], [class*='apply']").filter(has_text="图片应用到").first
        print("Clicking apply btn...", flush=True)
        btn.click(force=True)
        page.wait_for_timeout(600)
        
        # 2. Find dropdown option
        js_find = """() => {
            const drops = Array.from(document.querySelectorAll('.product-image-apply-menu, .ant-dropdown'));
            for (const d of drops) {
                if (getComputedStyle(d).display === 'none') continue;
                const groups = d.querySelectorAll('.menu-group, [class*="group"]');
                for (const g of groups) {
                    const title = (g.querySelector('.group-title, [class*="title"]')?.innerText || g.innerText || '').trim();
                    if (!title.includes('附图')) continue;
                    for (const it of g.querySelectorAll('.menu-item, [class*="item"]')) {
                        const txt = (it.innerText || '').trim();
                        if (txt.includes('所有变种') || txt.includes('所有变体') || txt.includes('所有')) {
                            const r = it.getBoundingClientRect();
                            return { found: true, group: title, item: txt, x: r.left + r.width/2, y: r.top + r.height/2 };
                        }
                    }
                }
            }
            return { found: false };
        }"""
        res = page.evaluate(js_find)
        print("Found option:", res, flush=True)
        
        if res.get("found"):
            print(f"Clicking at ({res['x']}, {res['y']})...", flush=True)
            page.mouse.click(res["x"], res["y"])
            page.wait_for_timeout(1000)
            
            # Check for any modal
            modals = page.evaluate("""() => {
                const ms = Array.from(document.querySelectorAll('.ant-modal, .el-dialog, [role="dialog"], .ant-modal-confirm'));
                return ms.map(m => ({
                    className: m.className,
                    text: m.innerText.trim(),
                    display: getComputedStyle(m).display,
                    visibility: getComputedStyle(m).visibility
                }));
            }""")
            print("Modals after click:", modals, flush=True)
            
            # Check cards after 1s
            cards = page.evaluate("""() => {
                const sec = document.querySelector('#variationImage');
                return Array.from(sec.querySelectorAll('.item-header')).map((h, idx) => {
                    const body = h.nextElementSibling;
                    const p8s = body ? Array.from(body.querySelectorAll('.p8')) : [];
                    const extraBox = p8s[2];
                    const imgs = extraBox ? Array.from(extraBox.querySelectorAll('img')).filter(i => !/addimg|kong-|\\/assets\\//i.test(i.src)) : [];
                    return { idx, extraCount: imgs.length };
                });
            }""")
            print("Cards after apply:", cards, flush=True)
            
    e.manager.run_on_browser_thread(run)

if __name__ == "__main__":
    test_step()
