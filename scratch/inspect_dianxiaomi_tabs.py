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
print(f"Connected: {ok}, {msg}")
tabs = e.get_tabs()
print("Tabs count:", len(tabs))
for idx, t in enumerate(tabs):
    print(f"Tab {idx}: {t.title} -> {t.url}")
