import os
import sys
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine
from core.form_operator import FormOperator

def test_verify():
    e = BrowserEngine(port=9222)
    e.connect()
    e.open_or_focus_url("https://www.dianxiaomi.com/web/amazon/add")
    
    def run():
        page = e.manager._get_active_page_impl()
        form = FormOperator(page)
        
        filter_crit = {"颜色": "一方向囲い‑人工芝 1 枚付き"}
        print("1. Testing apply_variation_image with auto verification...", flush=True)
        ok = form.apply_variation_image(filter_crit, apply_type="extra_all", timeout_ms=10000, verify_success=True)
        print(f"apply_variation_image result: {ok}", flush=True)
        
        print("\n2. Checking cards image counts after apply:", flush=True)
        cards = page.evaluate("""() => {
            const sec = document.querySelector('#variationImage');
            return Array.from(sec.querySelectorAll('.item-header')).map((h, i) => {
                const p8s = h.nextElementSibling ? Array.from(h.nextElementSibling.querySelectorAll('.p8')) : [];
                const extraImgs = p8s[2] ? Array.from(p8s[2].querySelectorAll('img')).filter(img => !/addimg|kong-|\\/assets\\//i.test(img.src)) : [];
                return { idx: i, extraCount: extraImgs.length };
            });
        }""")
        print("Cards status:", cards, flush=True)
        
    e.manager.run_on_browser_thread(run)

if __name__ == "__main__":
    test_verify()
