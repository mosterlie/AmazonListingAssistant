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

def test_menu_matching():
    engine = BrowserEngine(9222)
    engine.connect(activate=False)

    def run():
        p = [page for page in engine.manager.context.pages if page.locator('#variationImage').count() > 0][0]
        
        h1 = p.locator('#variationImage .item-header').first
        h1.scroll_into_view_if_needed()
        p.wait_for_timeout(300)

        apply_btn = h1.locator("span.link, a, span[class*='link'], [class*='apply']").filter(has_text="图片应用到").first
        apply_btn.click(force=True)
        p.wait_for_timeout(500)

        js_match = """
        (args) => {
            const { targetGroup, targetKeywords } = args;
            const drops = Array.from(document.querySelectorAll('.product-image-apply-menu, .ant-dropdown'));
            for (const d of drops) {
                if (getComputedStyle(d).display === 'none') continue;
                const groups = d.querySelectorAll('.menu-group, [class*="group"]');
                for (const g of groups) {
                    const title = (g.querySelector('.group-title, [class*="title"]')?.innerText || g.innerText || '').trim();
                    // 严格比对分组名，避免“全部图片”与“主图”混淆
                    if (targetGroup === '主图' && title !== '主图') continue;
                    if (targetGroup === '附图' && !title.includes('附图')) continue;
                    if (targetGroup === '全部图片' && !title.includes('全部图片')) continue;
                    if (targetGroup === 'Swatch Image' && !title.includes('Swatch')) continue;
                    
                    const items = Array.from(g.querySelectorAll('.menu-item, [class*="item"]'));
                    
                    // 优先按传入关键词顺序严格匹配
                    for (const kw of targetKeywords) {
                        for (const it of items) {
                            const txt = (it.innerText || '').trim();
                            if (txt.toLowerCase().includes(kw.toLowerCase())) {
                                const r = it.getBoundingClientRect();
                                return { found: true, group: title, item: txt, matchedKw: kw, rect: { x: r.left + r.width/2, y: r.top + r.height/2 } };
                            }
                        }
                    }
                }
            }
            return { found: false };
        }
        """

        match_color = p.evaluate(js_match, {"targetGroup": "主图", "targetKeywords": ["カラー", "颜色", "color", "色"]})
        match_size = p.evaluate(js_match, {"targetGroup": "主图", "targetKeywords": ["サイズ", "尺寸", "size"]})
        match_all = p.evaluate(js_match, {"targetGroup": "主图", "targetKeywords": ["所有变种", "所有变体", "所有"]})

        p.keyboard.press("Escape")
        return {
            "match_color": match_color,
            "match_size": match_size,
            "match_all": match_all
        }

    res = engine.manager.run_on_browser_thread(run)
    print(json.dumps(res, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    test_menu_matching()
