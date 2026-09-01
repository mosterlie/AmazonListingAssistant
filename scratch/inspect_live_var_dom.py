import sys
import os
import json
sys.path.insert(0, os.path.abspath("."))
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from browser_engine import BrowserEngine

def inspect():
    engine = BrowserEngine(9222)
    ok, msg = engine.connect(activate=False)
    print("connect:", ok, msg)
    if not ok:
        return

    def inspect_in_thread():
        pages = engine.manager.context.pages
        res = []
        for p in pages:
            url = p.url
            title = p.title()
            has_var = p.locator("#variationImage").count()
            var_headers = p.locator("#variationImage .item-header").count()
            res.append({"url": url, "title": title, "has_var": has_var, "headers": var_headers})
        return res

    info = engine.manager.run_on_browser_thread(inspect_in_thread)
    print("Pages info:", json.dumps(info, indent=2, ensure_ascii=False))

    # Let's inspect the page with headers > 0
    def inspect_cards():
        for p in engine.manager.context.pages:
            if p.locator("#variationImage .item-header").count() > 0:
                js = """
                () => {
                    const sec = document.querySelector('#variationImage');
                    if (!sec) return { error: 'no sec' };
                    const headers = Array.from(sec.querySelectorAll('.item-header'));
                    return headers.map((h, i) => {
                        const body = h.nextElementSibling;
                        const p8s = body ? Array.from(body.querySelectorAll('.p8')) : [];
                        return {
                            idx: i + 1,
                            header: h.innerText.replace(/\\s+/g, ' ').trim(),
                            p8_count: p8s.length,
                            p8_details: p8s.map((b, bi) => {
                                const imgs = Array.from(b.querySelectorAll('img')).map(img => img.src);
                                return {
                                    box_idx: bi,
                                    img_count: imgs.length,
                                    imgs: imgs
                                };
                            })
                        };
                    });
                }
                """
                return p.evaluate(js)
        return {"error": "no page with headers"}

    cards_info = engine.manager.run_on_browser_thread(inspect_cards)
    print("Cards info:", json.dumps(cards_info, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    inspect()
