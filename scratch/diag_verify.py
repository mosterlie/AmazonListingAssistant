import os
import sys
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine

def diag_verify():
    e = BrowserEngine(port=9222)
    e.connect()
    e.open_or_focus_url("https://www.dianxiaomi.com/web/amazon/add")
    
    def run():
        page = e.manager._get_active_page_impl()
        filter_criteria = {"颜色": "一方向囲い‑人工芝 1 枚付き", "尺寸": "75*50*36cm"}
        
        js_diag = """(args) => {
            const { filterCrit, applyType } = args;
            const sec = document.querySelector('#variationImage');
            if (!sec) return { success: false, reason: 'no variationImage' };
            const headers = Array.from(sec.querySelectorAll('.item-header'));
            if (headers.length === 0) return { success: false, reason: 'no headers' };

            const cards = headers.map((h, idx) => {
                const text = h.innerText.trim();
                const body = h.nextElementSibling;
                const p8s = body ? Array.from(body.querySelectorAll('.p8')) : [];
                
                const mainBox = p8s[0];
                const mainImgs = mainBox ? Array.from(mainBox.querySelectorAll('img')) : [];
                const realMainImgs = mainImgs.filter(i => !/addimg|kong-|\\/assets\\//i.test(i.src));

                const extraBox = p8s[2];
                const extraImgs = extraBox ? Array.from(extraBox.querySelectorAll('img')) : [];
                const realExtraImgs = extraImgs.filter(i => !/addimg|kong-|\\/assets\\//i.test(i.src));

                return {
                    idx,
                    text,
                    mainCount: realMainImgs.length,
                    extraCount: realExtraImgs.length
                };
            });

            const srcCard = cards.find(c => {
                return Object.values(filterCrit).every(v => c.text.includes(v));
            }) || cards[0];

            return {
                cardsCount: cards.length,
                srcCard,
                cards
            };
        }"""
        res = page.evaluate(js_diag, {"filterCrit": filter_criteria, "applyType": "extra_all"})
        print("Diagnosis result:", res)
        
    e.manager.run_on_browser_thread(run)

if __name__ == "__main__":
    diag_verify()
