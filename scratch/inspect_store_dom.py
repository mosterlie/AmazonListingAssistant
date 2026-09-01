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
ok, _ = e.connect(activate=False)

js = """
() => {
    const labels = Array.from(document.querySelectorAll('.ant-form-item-label label'));
    const storeLabel = labels.find(l => (l.innerText || '').includes('店铺账号'));
    const row = storeLabel ? storeLabel.closest('.ant-form-item, .ant-row') : null;
    const select = row ? row.querySelector('.ant-select, select') : null;

    return {
        rowHtml: row ? row.outerHTML.slice(0, 1000) : null,
        selectFound: !!select,
        selectClass: select ? select.className : null
    };
}
"""
res = e.manager.run_on_browser_thread(lambda: e.manager._get_active_page_impl().evaluate(js))
print(f"Row HTML:\n{res.get('rowHtml')}")
