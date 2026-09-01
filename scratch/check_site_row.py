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
    const labels = Array.from(document.querySelectorAll('.ant-form-item-label, label'));
    const storeLbl = labels.find(l => (l.innerText || '').includes('店铺账号'));
    const storeRow = storeLbl ? storeLbl.closest('.ant-form-item, .ant-form-item-row, .ant-row') : null;
    const storeItem = storeRow ? storeRow.querySelector('.ant-select-selection-item') : null;

    const siteLbl = labels.find(l => (l.innerText || '').includes('站点选择'));
    const siteRow = siteLbl ? siteLbl.closest('.ant-form-item, .ant-form-item-row, .ant-row') : null;

    return {
        storeText: storeItem ? storeItem.innerText : null,
        siteRowHtml: siteRow ? siteRow.outerHTML : null,
        siteRowText: siteRow ? siteRow.innerText : null
    };
}
"""
res = e.manager.run_on_browser_thread(lambda: e.manager._get_active_page_impl().evaluate(js))
print(f"Store: {res.get('storeText')}")
print(f"Site Row Text: {res.get('siteRowText')}")
print(f"Site Row HTML: {res.get('siteRowHtml')}")
