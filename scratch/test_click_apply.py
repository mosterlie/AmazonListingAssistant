import os
import sys
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine

def test_apply():
    e = BrowserEngine(port=9222)
    e.connect()
    
    def run_check():
        page = e.manager._get_active_page_impl()
        
        # 1. 查找第一个变体卡片的「图片应用到」
        var_container = page.locator("#variationImage .overflow-y-auto, #variationImage .max-h-700, #variationImage").first
        headers = var_container.locator(".item-header")
        print("Total item-headers:", headers.count())
        
        first_header = None
        for i in range(headers.count()):
            h = headers.nth(i)
            btn = h.locator("span.link, a, span[class*='link']").filter(has_text="图片应用到").first
            if btn.count() > 0:
                first_header = h
                print(f"Found first variation header at index {i}: {h.inner_text()[:60]}")
                break
        
        if not first_header:
            print("No variation header with '图片应用到' found!")
            return
            
        first_header.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        
        btn = first_header.locator("span.link, a, span[class*='link']").filter(has_text="图片应用到").first
        print("Clicking '图片应用到' button...")
        btn.click(force=True)
        page.wait_for_timeout(800)
        
        # 2. Inspect all dropdowns on the page
        dropdown_info = page.evaluate("""() => {
            const drops = Array.from(document.querySelectorAll('.ant-dropdown, [class*=\"dropdown\"], [class*=\"menu\"]'));
            const visibleDrops = [];
            for (const d of drops) {
                const style = getComputedStyle(d);
                if (style.display === 'none' || style.visibility === 'hidden') continue;
                const rect = d.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                
                const items = Array.from(d.querySelectorAll('.menu-item, li, [class*=\"item\"]')).map(it => ({
                    tag: it.tagName,
                    className: it.className,
                    text: it.innerText.trim(),
                    rect: it.getBoundingClientRect()
                }));
                
                visibleDrops.push({
                    tag: d.tagName,
                    className: d.className,
                    text: d.innerText.trim(),
                    rect: rect,
                    itemsCount: items.length,
                    items: items
                });
            }
            return visibleDrops;
        }""")
        
        print("Visible dropdowns:", len(dropdown_info))
        for idx, d in enumerate(dropdown_info):
            print(f"\n--- Dropdown {idx} ({d['className']}) ---")
            print("Full Text:\n", d['text'])
            print("Items:")
            for item in d['items']:
                print(f"  - [{item['className']}] {item['text']}")
                
    e.manager.run_on_browser_thread(run_check)

if __name__ == "__main__":
    test_apply()
