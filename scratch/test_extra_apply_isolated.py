import os
import sys
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine

def test():
    e = BrowserEngine(port=9222)
    e.connect()
    e.open_or_focus_url("https://www.dianxiaomi.com/web/amazon/add")
    
    filter_crit = {"颜色": "一方向囲い‑人工芝 1 枚付き"}
    print(f"Testing apply_variation_image with {filter_crit}...", flush=True)
    
    ok = e.apply_variation_image(filter_criteria=filter_crit, apply_type="extra_all", timeout_ms=10000)
    print(f"Result of apply_variation_image: {ok}", flush=True)

if __name__ == "__main__":
    test()
