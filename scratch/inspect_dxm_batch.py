import os
import sys
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine

def inspect():
    e = BrowserEngine(port=9222)
    e.connect()
    page = None
    for t in e.get_tabs():
        if "dianxiaomi.com/web/amazon/add" in t.url:
            e.open_or_focus_url(t.url)
            page = e.get_active_page()
            break
    
    if not page:
        print("No dianxiaomi page found!")
        return

    print("Page URL:", page.url)
    
    # Check variationImage section
    def do_eval():
        p = e.manager._get_active_page_impl()
        return p.evaluate("""() => {
            const sec = document.querySelector('#variationImage') || document.querySelector('[id*="variationImage"]') || document.querySelector('[class*="variationImage"]');
            if (!sec) return { found: false, msg: 'variationImage container not found' };
            
            const headers = Array.from(sec.querySelectorAll('.item-header, [class*="header"]')).map(h => ({
                text: h.innerText.trim(),
                applyBtn: Array.from(h.querySelectorAll('*')).filter(el => el.innerText && el.innerText.includes('图片应用到')).map(el => ({
                    tag: el.tagName,
                    className: el.className,
                    text: el.innerText
                }))
            }));
            
            return {
                found: true,
                secId: sec.id,
                secClass: sec.className,
                headersCount: headers.length,
                headers: headers.slice(0, 5)
            };
        }""")
    info = e.manager.run_on_browser_thread(do_eval)
    print("Variation section info:", info)

if __name__ == "__main__":
    inspect()
