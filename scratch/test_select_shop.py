import sys
import os
sys.path.insert(0, os.path.abspath("."))
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from browser_engine import BrowserEngine

e = BrowserEngine(port=9222)
ok, msg = e.connect(activate=False)
if not ok:
    print(f"未连接: {msg}")
    sys.exit(1)

res = e.select_store_account("飞奔的高压锅", "日本", timeout_ms=5000)
print(f"select_store_account result: {res}")
