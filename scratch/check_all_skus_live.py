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

def check_all_skus():
    engine = BrowserEngine(9222)
    ok, msg = engine.connect(activate=False)
    if not ok:
        print(f"连接失败: {msg}")
        return

    def inspect():
        p = [page for page in engine.manager.context.pages if page.locator("#variationImage").count() > 0][0]
        
        js = """
        async () => {
            const sec = document.querySelector('#variationImage');
            const scrollBox = sec.querySelector('.overflow-y-auto, .max-h-700') || sec;
            const headers = Array.from(sec.querySelectorAll('.item-header'));
            
            const isRealImg = (src) => {
                if (!src) return false;
                const s = src.toLowerCase();
                return !s.includes('addimg') && !s.includes('kong-') && !s.includes('/assets/') && !s.startsWith('data:image/svg');
            };

            const results = [];
            const origTop = scrollBox.scrollTop;

            for (let i = 0; i < headers.length; i++) {
                const h = headers[i];
                h.scrollIntoView({ block: 'center' });
                await new Promise(r => setTimeout(r, 180));

                const body = h.nextElementSibling;
                const p8s = body ? Array.from(body.querySelectorAll('.p8')) : [];
                const mainBox = p8s[0];
                let extraBox = null;
                for (let j = 0; j < p8s.length; j++) {
                    if (p8s[j].innerText.includes('选择图片') || p8s[j].querySelector('button, .ant-btn')) {
                        extraBox = p8s[j];
                        break;
                    }
                }
                if (!extraBox) {
                    if (p8s.length >= 3) extraBox = p8s[2];
                    else if (p8s.length === 2) extraBox = p8s[1];
                    else extraBox = p8s[0];
                }

                const mainImgs = mainBox ? Array.from(mainBox.querySelectorAll('img')).map(img => img.src).filter(isRealImg) : [];
                const extraImgs = extraBox ? Array.from(extraBox.querySelectorAll('img')).map(img => img.src).filter(isRealImg) : [];

                results.push({
                    idx: i + 1,
                    spec: h.innerText.replace('变种属性:', '').replace('图片应用到', '').replace(/\\s+/g, ' ').trim(),
                    mainCount: mainImgs.length,
                    extraCount: extraImgs.length,
                    extraUrls: extraImgs
                });
            }
            scrollBox.scrollTop = origTop;
            return results;
        }
        """
        return p.evaluate(js)

    cards = engine.manager.run_on_browser_thread(inspect)
    print("=" * 80)
    print(f"📊 [店小秘实时页面深度核验] 共检测到 {len(cards)} 个变体 SKU:")
    print("=" * 80)
    synced_cnt = 0
    for c in cards:
        if c["extraCount"] >= 6:
            tag = f"✅ 达标 (已装配 {c['extraCount']} 张附图)"
            synced_cnt += 1
        elif c["extraCount"] > 0:
            tag = f"⚠️ 部分 (已装配 {c['extraCount']} 张附图)"
            synced_cnt += 1
        else:
            tag = "❌ 未装配 (0 张附图)"
        print(f"SKU #{c['idx']:02d} | 附图: {c['extraCount']} 张 ({tag}) | 主图: {c['mainCount']} 张 | 规格: {c['spec']}")
    print("=" * 80)
    print(f"统计汇总: {synced_cnt}/{len(cards)} 个 SKU 已装配附图 (装配率: {synced_cnt/len(cards)*100:.1f}%)")
    print("=" * 80)

if __name__ == "__main__":
    check_all_skus()
