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

def inspect_variation_dom():
    e = BrowserEngine(port=9222)
    ok, msg = e.connect(activate=False)
    if not ok:
        print(f"❌ 浏览器连接失败: {msg}")
        return

    tabs = e.get_tabs()
    dxm_tab = next((t for t in tabs if "dianxiaomi.com" in t.url), None)
    if not dxm_tab:
        print("未找到店小秘页面")
        return

    e.open_or_focus_url(dxm_tab.url)
    
    js = """
    () => {
        const sec = document.querySelector('#variationImage');
        if (!sec) return { error: 'no #variationImage' };
        const headers = Array.from(sec.querySelectorAll('.item-header'));
        return {
            totalHeaders: headers.length,
            cards: headers.map((h, i) => {
                const body = h.nextElementSibling;
                const p8s = body ? Array.from(body.querySelectorAll('.p8')) : [];
                return {
                    idx: i,
                    text: h.innerText.trim(),
                    p8Count: p8s.length,
                    mainImgs: p8s[0] ? Array.from(p8s[0].querySelectorAll('img')).map(img => img.src) : [],
                    extraImgs: p8s[2] ? Array.from(p8s[2].querySelectorAll('img')).map(img => img.src) : []
                };
            })
        };
    }
    """
    res = e.manager.run_on_browser_thread(lambda: e.manager._get_active_page_impl().evaluate(js))
    print(f"DOM 变体图片概况: totalHeaders={res.get('totalHeaders')}")
    for c in res.get("cards", [])[:5]:
        print(f"  Card #{c['idx']} text={c['text']}")
        print(f"    mainImgs: {c['mainImgs']}")
        print(f"    extraImgs: {c['extraImgs']}")

if __name__ == "__main__":
    inspect_variation_dom()
