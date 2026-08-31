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

from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        ctx = browser.contexts[0]
        page = ctx.new_page()

        events = []
        page.on("request", lambda r: events.append(f">> REQ {r.url[:80]}"))
        page.on("requestfailed", lambda r: events.append(f"XX FAIL {r.url[:80]} | err={r.failure}"))
        page.on("response", lambda r: events.append(f"<< RESP {r.status} {r.url[:80]}"))

        # 先试 127.0.0.1
        try:
            page.goto("http://127.0.0.1:8000/list", wait_until="commit", timeout=10000)
            time.sleep(2)
            print("127 navigated:", page.url)
        except Exception as e:
            print("127 error:", str(e)[:200])
        print("--- events for 127.0.0.1 ---")
        for ev in events[:15]:
            print(" ", ev)
        events.clear()
        page.close()

        # 再试 localhost
        page2 = ctx.new_page()
        page2.on("requestfailed", lambda r: events.append(f"XX FAIL {r.url[:80]} | err={r.failure}"))
        page2.on("response", lambda r: events.append(f"<< RESP {r.status} {r.url[:80]}"))
        try:
            page2.goto("http://localhost:8000/list", wait_until="commit", timeout=10000)
            time.sleep(3)
            print("localhost navigated:", page2.url, "| title:", page2.title())
        except Exception as e:
            print("localhost error:", str(e)[:200])
        print("--- events for localhost ---")
        for ev in events[:15]:
            print(" ", ev)
        page2.close()

if __name__ == "__main__":
    main()
