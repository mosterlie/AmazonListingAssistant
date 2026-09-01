import os
import sys
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine

def diag():
    e = BrowserEngine(port=9222)
    e.connect()
    e.open_or_focus_url("https://www.dianxiaomi.com/web/amazon/add")
    
    def run_diag():
        page = e.manager._get_active_page_impl()
        
        info = page.evaluate("""() => {
            const var_container = document.querySelector("#variationImage .overflow-y-auto, #variationImage .max-h-700, #variationImage");
            if (!var_container) return { found: false, error: 'no variationImage container' };
            
            const headers = Array.from(var_container.querySelectorAll(".item-header"));
            const cards = headers.map((h, idx) => {
                const body = h.nextElementSibling;
                const p8s = body ? Array.from(body.querySelectorAll(".p8")) : [];
                return {
                    idx,
                    text: h.innerText.trim().replace(/\\n/g, ' | '),
                    bodyExists: !!body,
                    p8Count: p8s.length,
                    boxes: p8s.map((p, pIdx) => {
                        const imgs = Array.from(p.querySelectorAll('img')).map(i => ({
                            src: i.src,
                            isPh: /addimg|kong-|\\/assets\\//i.test(i.src)
                        }));
                        const btns = Array.from(p.querySelectorAll('button, .ant-btn, .img-out, a, span.link')).map(b => ({
                            tag: b.tagName,
                            text: b.innerText.trim(),
                            className: b.className
                        }));
                        return {
                            boxIdx: pIdx,
                            totalImgs: imgs.length,
                            realImgs: imgs.filter(i => !i.isPh).length,
                            btns: btns
                        };
                    })
                };
            });
            
            return { found: true, cards };
        }""")
        
        print("Cards diagnosis:", flush=True)
        for c in info.get("cards", []):
            print(f"\nCard #{c['idx']}: {c['text'][:60]}", flush=True)
            for b in c["boxes"]:
                print(f"  Box #{b['boxIdx']}: realImgs={b['realImgs']}, totalImgs={b['totalImgs']}, btns={b['btns']}", flush=True)
                
    e.manager.run_on_browser_thread(run_diag)

if __name__ == "__main__":
    diag()
