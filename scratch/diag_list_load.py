import json
import sys
import os
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        ctx = browser.contexts[0]
        page = None
        for pg in ctx.pages:
            if "8000/list" in pg.url or "newtab" in pg.url:
                page = pg
                break
        if not page:
            page = ctx.new_page()
        page.bring_to_front()
        print("before:", page.url, "| title:", page.title())
        try:
            resp = page.goto("http://127.0.0.1:8000/list", wait_until="domcontentloaded", timeout=15000)
            print("goto status:", resp.status if resp else None)
        except Exception as e:
            print("goto error:", e)
        time.sleep(3)
        try:
            state = page.evaluate("""() => ({
                url: location.href, title: document.title,
                readyState: document.readyState,
                bodyLen: (document.body ? document.body.innerText.length : 0),
                head: (document.body ? document.body.innerText.slice(0, 120) : '')
            })""")
            print("state:", json.dumps(state, ensure_ascii=False))
        except Exception as e:
            print("evaluate error:", e)

if __name__ == "__main__":
    main()
