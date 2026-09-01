import sys
import os
import json
import time

sys.path.insert(0, os.path.abspath("."))
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from browser_engine import BrowserEngine

def run_test_apply_first_main():
    engine = BrowserEngine(9222)
    engine.connect(activate=False)

    def run():
        p = [page for page in engine.manager.context.pages if page.locator('#variationImage').count() > 0][0]
        
        # 1. 检查第 1 个 SKU 当前状态
        h1 = p.locator('#variationImage .item-header').first
        h1.scroll_into_view_if_needed()
        p.wait_for_timeout(300)
        h1_text = h1.inner_text().replace('\n', ' ').strip()
        print(f"第 1 个 SKU 卡片标题: {h1_text}")

        # 2. 点击「图片应用到」
        apply_btn = h1.locator("span.link, a, span[class*='link'], [class*='apply']").filter(has_text="图片应用到").first
        apply_btn.click(force=True)
        p.wait_for_timeout(600)

        # 3. 定位「主图」分组下的「同カラー(颜色)的变种」
        js_find_option = """
        (args) => {
            const { targetGroup, targetKeywords } = args;
            const drops = Array.from(document.querySelectorAll('.product-image-apply-menu, .ant-dropdown'));
            for (const d of drops) {
                if (getComputedStyle(d).display === 'none') continue;
                const groups = d.querySelectorAll('.menu-group, [class*="group"]');
                for (const g of groups) {
                    const title = (g.querySelector('.group-title, [class*="title"]')?.innerText || g.innerText || '').trim();
                    if (targetGroup === '主图' && title !== '主图') continue;
                    if (targetGroup === '附图' && !title.includes('附图')) continue;
                    if (targetGroup === '全部图片' && !title.includes('全部图片')) continue;
                    
                    const items = Array.from(g.querySelectorAll('.menu-item, [class*="item"]'));
                    for (const kw of targetKeywords) {
                        for (const it of items) {
                            const txt = (it.innerText || '').trim();
                            if (txt.toLowerCase().includes(kw.toLowerCase())) {
                                const r = it.getBoundingClientRect();
                                it.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
                                it.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
                                it.click();
                                return { found: true, group: title, item: txt, matchedKw: kw,
                                         x: r.left + r.width / 2, y: r.top + r.height / 2 };
                            }
                        }
                    }
                }
            }
            return { found: false };
        }
        """
        match_res = p.evaluate(js_find_option, {"targetGroup": "主图", "targetKeywords": ["カラー", "颜色", "color", "色"]})
        print("点击菜单选项结果:", match_res)

        if match_res and match_res.get("found"):
            p.mouse.click(match_res["x"], match_res["y"])
            p.wait_for_timeout(800)

        # 4. 检查是否有确认弹窗并确认
        js_modal = """
        () => {
            const modals = Array.from(document.querySelectorAll('.ant-modal, .ant-modal-content, [role="dialog"], .el-message-box'));
            for (const m of modals) {
                if (getComputedStyle(m).display === 'none') continue;
                const btns = Array.from(m.querySelectorAll('button, .ant-btn, .el-button, a'));
                const okBtn = btns.find(b => {
                    const t = (b.innerText || b.textContent || '').trim();
                    return t === '确定' || t.includes('确定') || b.classList.contains('ant-btn-primary');
                });
                if (okBtn) {
                    okBtn.click();
                    return { clicked: true, text: okBtn.innerText.trim() };
                }
            }
            return { clicked: false };
        }
        """
        modal_res = p.evaluate(js_modal)
        print("弹窗确认结果:", modal_res)
        p.wait_for_timeout(1000)

        # 5. 逐个 SKU 检查主图同步情况
        js_check = """
        async () => {
            const sec = document.querySelector('#variationImage');
            const headers = Array.from(sec.querySelectorAll('.item-header'));
            const scrollBox = sec.querySelector('.overflow-y-auto, .max-h-700') || sec;
            const origTop = scrollBox.scrollTop;
            const hasSkeleton = sec.querySelectorAll('.render-skeleton').length > 0;

            const isRealImg = (src) => {
                if (!src) return false;
                const s = src.toLowerCase();
                return !s.includes('addimg') && !s.includes('kong-') && !s.includes('/assets/') && !s.startsWith('data:image/svg');
            };

            const cards = [];
            for (let i = 0; i < headers.length; i++) {
                const h = headers[i];
                if (hasSkeleton) {
                    h.scrollIntoView({ block: 'center', inline: 'nearest' });
                    await new Promise(r => setTimeout(r, 100));
                }
                const body = h.nextElementSibling;
                const p8s = body ? Array.from(body.querySelectorAll('.p8')) : [];
                const mainBox = p8s[0];
                const mainImgs = mainBox ? Array.from(mainBox.querySelectorAll('img')).map(img => img.src).filter(isRealImg) : [];

                cards.push({
                    idx: i + 1,
                    spec: h.innerText.replace('变种属性:', '').replace('图片应用到', '').replace(/\\s+/g, ' ').trim(),
                    mainCount: mainImgs.length,
                    mainSrcs: mainImgs
                });
            }
            if (hasSkeleton) scrollBox.scrollTop = origTop;
            return cards;
        }
        """
        cards = p.evaluate(js_check)
        return cards

    cards = engine.manager.run_on_browser_thread(run)
    print("\n" + "=" * 80)
    print("📊 [主图批量应用后检查结果]:")
    print("=" * 80)
    for c in cards:
        tag = "✅ 主图已装配" if c["mainCount"] > 0 else "❌ 主图为空"
        print(f"SKU #{c['idx']:02d} | 主图: {c['mainCount']} 张 ({tag}) | 规格: {c['spec']}")
    print("=" * 80)

if __name__ == '__main__':
    run_test_apply_first_main()
