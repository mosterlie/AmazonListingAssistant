import sys
import os
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine

def main():
    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect(activate=True)
    print("Connect:", ok, msg)
    if not ok:
        return

    def inspect():
        p = None
        for page in engine.manager.context.pages:
            if "dianxiaomi.com" in page.url:
                p = page
                break
        if not p:
            p = engine.manager.context.pages[0]
        p.bring_to_front()
        print("Page URL:", p.url)
        print("Page Title:", p.title())
        var_headers = p.locator("#variationImage .item-header")
        count = var_headers.count()
        print(f"Variation card count: {count}")
        for i in range(count):
            print(f"Card {i}: {var_headers.nth(i).inner_text().strip()}")
        return count

    engine.manager.run_on_browser_thread(inspect)

if __name__ == "__main__":
    main()
