import os
import sys
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine

def test_verify_dom():
    e = BrowserEngine(port=9222)
    e.connect()
    e.open_or_focus_url("https://www.dianxiaomi.com/web/amazon/add")
    
    def run_check():
        page = e.manager._get_active_page_impl()
        
        # JS to inspect all variation cards and their images
        js_cards = """() => {
            const sec = document.querySelector('#variationImage');
            if (!sec) return { found: false };
            const headers = Array.from(sec.querySelectorAll('.item-header'));
            
            const cards = headers.map((h, idx) => {
                const text = h.innerText.trim();
                const body = h.nextElementSibling;
                const p8s = body ? Array.from(body.querySelectorAll('.p8')) : [];
                
                // Box 0: Main image
                const mainBox = p8s[0];
                const mainImgs = mainBox ? Array.from(mainBox.querySelectorAll('img')) : [];
                const realMainImgs = mainImgs.filter(i => !/addimg|kong-|\\/assets\\//i.test(i.src)).map(i => i.src);
                
                // Box 1: Swatch
                const swatchBox = p8s[1];
                const swatchImgs = swatchBox ? Array.from(swatchBox.querySelectorAll('img')) : [];
                const realSwatchImgs = swatchImgs.filter(i => !/addimg|kong-|\\/assets\\//i.test(i.src)).map(i => i.src);
                
                // Box 2: Extra images
                const extraBox = p8s[2];
                const extraImgs = extraBox ? Array.from(extraBox.querySelectorAll('img')) : [];
                const realExtraImgs = extraImgs.filter(i => !/addimg|kong-|\\/assets\\//i.test(i.src)).map(i => i.src);
                
                return {
                    idx,
                    headerText: text,
                    mainCount: realMainImgs.length,
                    mainSrcs: realMainImgs,
                    swatchCount: realSwatchImgs.length,
                    extraCount: realExtraImgs.length,
                    extraSrcs: realExtraImgs
                };
            });
            
            return { found: true, count: cards.length, cards };
        }"""
        
        info = page.evaluate(js_cards)
        print(f"Variation Cards count: {info.get('count')}", flush=True)
        for c in info.get("cards", []):
            print(f"Card #{c['idx']}:", flush=True)
            print(f"  Header: {c['headerText'].replace(chr(10), ' | ')}", flush=True)
            print(f"  Main: {c['mainCount']}, Swatch: {c['swatchCount']}, Extra: {c['extraCount']}", flush=True)
            
    e.manager.run_on_browser_thread(run_check)

if __name__ == "__main__":
    test_verify_dom()
