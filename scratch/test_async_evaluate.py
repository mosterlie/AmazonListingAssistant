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

def test_async():
    engine = BrowserEngine(9222)
    engine.connect(activate=False)

    def run():
        p = [page for page in engine.manager.context.pages if page.locator('#variationImage').count() > 0][0]
        js = """
        async () => {
            const sec = document.querySelector('#variationImage');
            const headers = Array.from(sec.querySelectorAll('.item-header'));
            const scrollBox = sec.querySelector('.overflow-y-auto, .max-h-700') || sec;
            const origTop = scrollBox.scrollTop;

            if (sec.querySelectorAll('.render-skeleton').length > 0) {
                for (const h of headers) {
                    h.scrollIntoView({ block: 'nearest' });
                    await new Promise(r => setTimeout(r, 60));
                }
                scrollBox.scrollTop = origTop;
            }

            const isRealImg = (src) => {
                if (!src) return false;
                const s = src.toLowerCase();
                return !s.includes('addimg') && !s.includes('kong-') && !s.includes('/assets/') && !s.startsWith('data:image/svg');
            };

            const cards = headers.map((h, idx) => {
                const body = h.nextElementSibling;
                const p8s = body ? Array.from(body.querySelectorAll('.p8')) : [];
                const mainBox = p8s[0];
                let extraBox = null;
                for (let i = 0; i < p8s.length; i++) {
                    if (p8s[i].innerText.includes('选择图片') || p8s[i].querySelector('button, .ant-btn')) {
                        extraBox = p8s[i];
                        break;
                    }
                }
                if (!extraBox) {
                    if (p8s.length >= 3) extraBox = p8s[2];
                    else if (p8s.length === 2) extraBox = p8s[1];
                    else extraBox = p8s[0];
                }
                const mainImgs = mainBox ? Array.from(mainBox.querySelectorAll('img')).map(i => i.src).filter(isRealImg) : [];
                const extraImgs = extraBox ? Array.from(extraBox.querySelectorAll('img')).map(i => i.src).filter(isRealImg) : [];
                return {
                    idx: idx + 1,
                    mainCount: mainImgs.length,
                    extraCount: extraImgs.length
                };
            });

            return {
                total: cards.length,
                withExtra: cards.filter(c => c.extraCount > 0).length,
                cards
            };
        }
        """
        return p.evaluate(js)

    res = engine.manager.run_on_browser_thread(run)
    print("Async evaluate result:", res["total"], "cards, withExtra:", res["withExtra"])

if __name__ == "__main__":
    test_async()
