import os
import sys
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine

def test_clicks():
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
        btn.click(force=True)
        page.wait_for_timeout(600)
        
        # 2. Test direct JS click on the matching element
        res = page.evaluate("""() => {
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
                            // Try calling click() directly
                            it.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                            it.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                            it.click();
                            return { clicked: true, text: txt, title };
                        }
                    }
                }
            }
            return { clicked: false };
        }""")
        print("JS Click Result:", res, flush=True)
        page.wait_for_timeout(1000)
        
        # Check cards
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
        print("Cards after JS click:", cards, flush=True)
        
    e.manager.run_on_browser_thread(run)

if __name__ == "__main__":
    test_clicks()
