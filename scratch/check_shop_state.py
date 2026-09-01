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
    print(f"❌ 浏览器连接失败: {msg}")
    sys.exit(1)

js = """
() => {
    return {
        url: window.location.href,
        title: document.title,
        bodyTextSnippet: document.body.innerText.slice(0, 300),
        hasShopSelect: !!document.querySelector('#shopSelect, select[name="shopId"], .shop-select, .ant-select'),
        selectTexts: Array.from(document.querySelectorAll('select option, .ant-select-selection-item, .ant-select-item-option-content')).map(o => o.innerText.trim()).filter(Boolean)
    };
}
"""
res = e.manager.run_on_browser_thread(lambda: e.manager._get_active_page_impl().evaluate(js))
print(f"URL: {res.get('url')}")
print(f"Title: {res.get('title')}")
print(f"Select texts: {res.get('selectTexts')[:20]}")
print(f"Body snippet: {res.get('bodyTextSnippet')}")
