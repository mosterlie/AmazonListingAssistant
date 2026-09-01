import sys
import os
sys.path.insert(0, os.path.abspath("."))
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import time
from browser_engine import BrowserEngine

def test_live_extra_all():
    print("=" * 80)
    print("🚀 【直接测试当前页面：附图应用到所有变体并实时逐 SKU 打印】")
    print("=" * 80)

    e = BrowserEngine(port=9222)
    ok, msg = e.connect(activate=False)
    if not ok:
        print(f"❌ 浏览器连接失败: {msg}")
        return

    # 1. 查询当前页面每个 SKU 的附图状态
    js_query_all = """
    () => {
        const sec = document.querySelector('#variationImage');
        if (!sec) return { ok: false, reason: '未找到 #variationImage' };
        const headers = Array.from(sec.querySelectorAll('.item-header'));
        const cards = headers.map((h, i) => {
            const body = h.nextElementSibling;
            const p8s = body ? Array.from(body.querySelectorAll('.p8')) : [];
            const mainImgs = p8s[0] ? Array.from(p8s[0].querySelectorAll('img')).filter(img => !/addimg|kong-|\\/assets\\//i.test(img.src)) : [];
            const extraImgs = p8s[2] ? Array.from(p8s[2].querySelectorAll('img')).filter(img => !/addimg|kong-|\\/assets\\//i.test(img.src)) : [];
            return {
                idx: i + 1,
                text: h.innerText.replace(/\\s+/g, ' ').trim(),
                mainCount: mainImgs.length,
                extraCount: extraImgs.length
            };
        });
        return { ok: true, total: cards.length, cards };
    }
    """
    
    before_state = e.manager.run_on_browser_thread(lambda: e.manager._get_active_page_impl().evaluate(js_query_all))
    print(f"📋 【应用前】检测到 {before_state['total']} 个变体卡片:")
    for c in before_state["cards"]:
        print(f"   • SKU #{c['idx']:02d} | 附图: 【{c['extraCount']} 张】 | 主图: 【{c['mainCount']} 张】 | {c['text']}")

    # 找出一个已有附图的卡片作为源卡片
    src_card = next((c for c in before_state["cards"] if c["extraCount"] > 0), None)
    if not src_card:
        print("❌ 当前页面没有包含附图的变体卡片")
        return

    print(f"\n🎯 选取源卡片: SKU #{src_card['idx']} ({src_card['text']})，已有附图 {src_card['extraCount']} 张")

    # 2. 点击该卡片的「图片应用到」并选择【附图 ➔ 所有变体】
    def _do_apply():
        page = e.manager._get_active_page_impl()
        # 找到该卡片
        headers = page.locator("#variationImage .item-header")
        target_h = headers.nth(src_card["idx"] - 1)
        apply_btn = target_h.locator("span.link, a, [class*='apply']").filter(has_text="图片应用到").first
        apply_btn.click(force=True)
        page.wait_for_timeout(500)

        # 查找附图 - 所有变体
        js_find_extra_all = """
        () => {
            const drops = Array.from(document.querySelectorAll('.product-image-apply-menu, .ant-dropdown'));
            for (const d of drops) {
                if (getComputedStyle(d).display === 'none') continue;
                const groups = d.querySelectorAll('.menu-group, [class*="group"]');
                for (const g of groups) {
                    const title = (g.querySelector('.group-title, [class*="title"]')?.innerText || g.innerText || '').trim();
                    if (!title.includes('附图')) continue;
                    for (const it of g.querySelectorAll('.menu-item, [class*="item"]')) {
                        const txt = (it.innerText || '').trim();
                        if (txt.includes('所有')) {
                            const r = it.getBoundingClientRect();
                            it.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                            it.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                            it.click();
                            return { found: true, x: r.left + r.width/2, y: r.top + r.height/2, text: txt };
                        }
                    }
                }
            }
            return { found: false };
        }
        """
        res = page.evaluate(js_find_extra_all)
        print(f"   ➔ 下拉选项选择结果: {res}")
        if res.get("found"):
            page.mouse.click(res["x"], res["y"])
            page.wait_for_timeout(600)
            
            # 点击 Ant Modal 确定
            confirm_btn = page.locator(".ant-modal:not([style*='display: none']) button, .ant-modal:not([style*='display: none']) .ant-btn-primary").filter(has_text="确定").first
            if confirm_btn.count() > 0:
                print("   ➔ 检测到二次确认弹窗，正在点击【确定】...")
                confirm_btn.click()
            else:
                # evaluate 兜底
                page.evaluate("""
                () => {
                    const btns = Array.from(document.querySelectorAll('.ant-modal button, .ant-modal .ant-btn'));
                    const ok = btns.find(b => (b.innerText || '').trim() === '确定' || (b.innerText || '').trim() === 'OK');
                    if (ok) ok.click();
                }
                """)
        return True

    print("\n⚡ 正在触发【附图 ➔ 所有变体】批量应用...")
    e.manager.run_on_browser_thread(_do_apply)

    # 3. 逐秒实时扫描每个 SKU 的附图同步数量变化
    print("\n🔍 正在持续逐秒采样，核验每个 SKU 的附图同步结果 (持续 8 秒)...")
    expected_extra = src_card["extraCount"]
    
    all_success = False
    for sec in range(1, 9):
        time.sleep(1.0)
        curr = e.manager.run_on_browser_thread(lambda: e.manager._get_active_page_impl().evaluate(js_query_all))
        cards = curr.get("cards", [])
        synced = [c for c in cards if c["extraCount"] >= expected_extra]
        print(f"\n⏱️ [第 {sec} 秒检查] 全量同步率: {len(synced)} / {len(cards)} 个达标 (目标每 SKU >= {expected_extra} 张附图)")
        for c in cards:
            tag = "✅ 已同步" if c["extraCount"] >= expected_extra else f"⏳ 仅 {c['extraCount']} 张"
            print(f"     SKU #{c['idx']:02d} | 附图: {c['extraCount']:02d} 张 ({tag}) | {c['text']}")

        if len(synced) == len(cards) and len(cards) > 0:
            all_success = True
            print(f"\n🎉 完美！在第 {sec} 秒时，全部 {len(cards)} 个 SKU 附图已 100% 批量同步完成（每卡片均为 {expected_extra} 张附图）！")
            break

    print("\n" + "=" * 80)
    if all_success:
        print(f"✅ 测试结论: 附图批量应用【完全成功】！全部 {len(cards)} 个 SKU 均已同步 {expected_extra} 张附图！")
    else:
        print("⚠️ 测试结论: 部分 SKU 附图同步未完成。")
    print("=" * 80)

if __name__ == "__main__":
    test_live_extra_all()
