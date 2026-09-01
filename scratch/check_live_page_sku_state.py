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
if ok:
    js = """
    () => {
        const title = document.title;
        const url = window.location.href;
        const sec = document.querySelector('#variationImage');
        const headers = sec ? Array.from(sec.querySelectorAll('.item-header')) : [];
        const logs = [];
        headers.forEach((h, i) => {
            const body = h.nextElementSibling;
            const p8s = body ? Array.from(body.querySelectorAll('.p8')) : [];
            const mainImgs = p8s[0] ? Array.from(p8s[0].querySelectorAll('img')).filter(img => !/addimg|kong-|\\/assets\\//i.test(img.src)) : [];
            const extraImgs = p8s[2] ? Array.from(p8s[2].querySelectorAll('img')).filter(img => !/addimg|kong-|\\/assets\\//i.test(img.src)) : [];
            logs.push({
                idx: i + 1,
                text: h.innerText.replace(/\\s+/g, ' ').trim(),
                mainCount: mainImgs.length,
                extraCount: extraImgs.length
            });
        });
        return {
            title, url,
            hasVarSection: !!sec,
            totalHeaders: headers.length,
            cards: logs
        };
    }
    """
    res = e.manager.run_on_browser_thread(lambda: e.manager._get_active_page_impl().evaluate(js))
    print(f"Title: {res.get('title')}")
    print(f"URL: {res.get('url')}")
    print(f"Has variation image section: {res.get('hasVarSection')}")
    print(f"Total variation cards: {res.get('totalHeaders')}")
    for c in res.get("cards", []):
        print(f"  SKU #{c['idx']:02d} | 附图: {c['extraCount']} 张 | 主图: {c['mainCount']} 张 | 规格: {c['text']}")
