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

from browser_engine import BrowserEngine

def main():
    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect(activate=True)
    print("connect:", ok)

    def probe():
        page = None
        for p in engine.manager.context.pages:
            if "pageList/draft" in p.url:
                page = p
                break
        if not page:
            page = engine.manager.context.new_page()
            page.goto("https://www.dianxiaomi.com/web/amazon/pageList/draft", wait_until="domcontentloaded", timeout=20000)
        else:
            page.bring_to_front()
            page.reload(wait_until="domcontentloaded", timeout=15000)
        time.sleep(6)
        res = page.evaluate("""() => {
            const rows = Array.from(document.querySelectorAll('.ant-table-tbody tr, table tbody tr'));
            const hit = rows.filter(r => (r.innerText || '').includes('admin12') || (r.innerText || '').includes('ADMIN12'));
            return {
                url: location.href,
                totalRows: rows.length,
                matched: hit.map(r => (r.innerText || '').replace(/\\s+/g, ' ').slice(0, 150))
            };
        }""")
        print(json.dumps(res, ensure_ascii=False, indent=2))

    engine.manager.run_on_browser_thread(probe)

if __name__ == "__main__":
    main()
