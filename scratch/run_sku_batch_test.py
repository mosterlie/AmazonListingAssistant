import sys
import os
import time
import json

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine

CONV_ID = "4d70ba54-c5b0-4648-8adb-474ba62b907e"
ARTIFACT_DIR = f"/Users/gx/.gemini/antigravity-ide/brain/{CONV_ID}"
os.makedirs(ARTIFACT_DIR, exist_ok=True)

UPLOADS = os.path.join(PROJECT_DIR, "data", "uploads")
FIRST_FILTER = {"颜色": "11", "尺寸": "aa"}
EXTRA_IMGS = [os.path.join(UPLOADS, f"PT{i:02d}.jpg") for i in [1, 2, 3, 4, 5]]
COLOR_MAIN_PLAN = [
    ("11", os.path.join(UPLOADS, "sku1.jpg")),
    ("22", os.path.join(UPLOADS, "sku2.jpg")),
    ("33", os.path.join(UPLOADS, "sku3.jpg")),
]

def main():
    print("=" * 70)
    print("🚀 开始执行【店小秘-SKU批量上传与图片批量应用功能】深度自动化测试...")
    print(f"📁 截图输出目录: {ARTIFACT_DIR}")
    print("=" * 70)

    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect(activate=True)
    if not ok:
        print(f"❌ 连接浏览器失败: {msg}")
        return False

    # 1. 确保在店小秘添加产品页面
    target_url = "https://www.dianxiaomi.com/web/amazon/add"
    print("🌐 检查并聚焦店小秘添加产品页...")
    engine.open_or_focus_url(target_url)
    time.sleep(2)

    # 2. 检查页面变体卡片数量
    def get_var_cards_count():
        p = engine.manager._get_active_page_impl()
        if not p:
            return 0
        return p.locator("#variationImage .item-header").count()

    count = engine.manager.run_on_browser_thread(get_var_cards_count)
    print(f"📊 当前变体图片卡片数量: {count}")

    if count < 2:
        print("⚙️ 正在自动配置店铺、类目与多变体属性 (11/22/33 × aa/qq)...")
        # 店铺
        engine.select_store_account("金梧汇辰", "日本", timeout_ms=15000)
        time.sleep(1)
        # 标题
        engine.fill("产品标题", "日本人気ペット用トイレトレー 自動洗浄ガード付き")
        time.sleep(1)
        # 类目
        if engine.click_button("自动识别产品类型"):
            time.sleep(2)
            engine.confirm_modal("确定", wait_timeout_ms=5000)
            time.sleep(2)
        # 变体
        engine.click_radio("多变体(variation)")
        time.sleep(1)
        engine.select("变种主题", "Color-Size")
        time.sleep(1)
        engine.add_variation_option("カラー", "11")
        time.sleep(0.5)
        engine.add_variation_option("カラー", "22")
        time.sleep(0.5)
        engine.add_variation_option("カラー", "33")
        time.sleep(0.5)
        engine.add_variation_option("サイズ", "aa")
        time.sleep(0.5)
        engine.add_variation_option("サイズ", "qq")
        time.sleep(2.0)

    count = engine.manager.run_on_browser_thread(get_var_cards_count)
    print(f"✅ 变体矩阵就绪，共 {count} 个 SKU 卡片！\n")

    # 截图0: 初始变体卡片状态
    def snap_initial():
        p = engine.manager._get_active_page_impl()
        p.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        p_path = os.path.join(ARTIFACT_DIR, "step0_variation_matrix_initial.png")
        p.screenshot(path=p_path)
        return p_path

    s0 = engine.manager.run_on_browser_thread(snap_initial)
    print(f"📸 [截图 0] 变体矩阵初始状态: {s0}\n")

    # =========================================================================
    # 步骤 1: 为第一个 SKU (颜色11 / 尺寸aa) 上传 1 张主图与 5 张附图
    # =========================================================================
    print("-" * 60)
    print("📸 【步骤 1】为第一个 SKU (カラー: 11 / サイズ: aa) 上传主图与 5 张附图...")
    print("  1.1 上传主图 (sku1.jpg)...")
    up_main_1 = engine.upload_variation_image(
        filter_criteria=FIRST_FILTER,
        image_path=COLOR_MAIN_PLAN[0][1],
        image_type="main",
        timeout_ms=30000
    )
    print(f"      主图上传: {'✅ 成功' if up_main_1 else '❌ 失败'}")
    time.sleep(1)

    print(f"  1.2 上传 5 张附图 (PT01~PT05)...")
    up_extra_1 = engine.upload_variation_image(
        filter_criteria=FIRST_FILTER,
        image_path=EXTRA_IMGS,
        image_type="extra",
        timeout_ms=45000
    )
    print(f"      附图上传: {'✅ 成功' if up_extra_1 else '❌ 失败'}")
    time.sleep(1)

    def snap_step1():
        p = engine.manager._get_active_page_impl()
        p.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        path = os.path.join(ARTIFACT_DIR, "step1_first_sku_uploaded.png")
        p.screenshot(path=path)
        return path

    s1 = engine.manager.run_on_browser_thread(snap_step1)
    print(f"📸 [截图 1] 第一个 SKU 上传完成留痕: {s1}\n")

    # =========================================================================
    # 步骤 2: 点击「图片应用到」下拉菜单，捕获【附图 ➔ 所有变体】菜单项展开截图
    # =========================================================================
    print("-" * 60)
    print("📸 【步骤 2】触发「图片应用到」下拉菜单，捕获【附图 ➔ 所有变体】点击菜单截图...")

    def open_and_snap_extra_menu():
        p = engine.manager._get_active_page_impl()
        p.keyboard.press("Escape")
        p.mouse.click(300, 200)
        time.sleep(0.4)
        var_box = p.locator("#variationImage .overflow-y-auto, #variationImage .max-h-700").first
        headers = var_box.locator(".item-header")
        for i in range(headers.count()):
            h = headers.nth(i)
            if "11" in h.inner_text() and "aa" in h.inner_text():
                h.scroll_into_view_if_needed()
                time.sleep(0.5)
                apply_btn = h.locator("span.link, a, span[class*='link']").filter(has_text="图片应用到").first
                apply_btn.click()
                time.sleep(0.8)
                
                # 移动鼠标至【附图 ➔ 所有变体】选项上方以突出高亮状态
                js_hover = """
                () => {
                    const drops = Array.from(document.querySelectorAll('.ant-dropdown'));
                    for (const d of drops) {
                        if (getComputedStyle(d).display === 'none') continue;
                        const groups = d.querySelectorAll('.menu-group');
                        for (const g of groups) {
                            const title = (g.querySelector('.group-title')?.innerText || '').trim();
                            if (!title.includes('附图')) continue;
                            for (const it of g.querySelectorAll('.menu-item')) {
                                if (it.innerText.includes('所有变种') || it.innerText.includes('所有变体')) {
                                    const r = it.getBoundingClientRect();
                                    return { found: true, x: r.left + r.width / 2, y: r.top + r.height / 2 };
                                }
                            }
                        }
                    }
                    return { found: false };
                }
                """
                pos = p.evaluate(js_hover)
                if pos and pos.get("found"):
                    p.mouse.move(pos["x"], pos["y"])
                    time.sleep(0.3)

                snap_path = os.path.join(ARTIFACT_DIR, "step2_click_batch_apply_extra_menu.png")
                p.screenshot(path=snap_path)
                return snap_path
        return ""

    s2 = engine.manager.run_on_browser_thread(open_and_snap_extra_menu)
    print(f"📸 [截图 2] 点击【附图 ➔ 所有变体】下拉菜单捕获: {s2}\n")

    # =========================================================================
    # 步骤 3: 执行点击【附图 ➔ 所有变体】批量应用，并截图全量 SKU 附图同步效果
    # =========================================================================
    print("-" * 60)
    print("📸 【步骤 3】执行点击【附图 ➔ 所有变体】批量应用...")
    apply_extra_ok = engine.apply_variation_image(
        filter_criteria=FIRST_FILTER,
        apply_type="extra_all",
        timeout_ms=15000
    )
    print(f"      附图批量应用结果: {'✅ 成功' if apply_extra_ok else '❌ 失败'}")
    time.sleep(1.5)

    def snap_extra_applied():
        p = engine.manager._get_active_page_impl()
        p.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        path = os.path.join(ARTIFACT_DIR, "step3_extra_images_applied_to_all_skus.png")
        p.screenshot(path=path)
        return path

    s3 = engine.manager.run_on_browser_thread(snap_extra_applied)
    print(f"📸 [截图 3] 全量 SKU 附图批量应用同步完成留痕: {s3}\n")

    # =========================================================================
    # 步骤 4: 点击「图片应用到」下拉菜单，捕获【主图 ➔ 同颜色变体】菜单项展开截图
    # =========================================================================
    print("-" * 60)
    print("📸 【步骤 4】触发「图片应用到」下拉菜单，捕获【主图 ➔ 同カラー(颜色)的变种】点击菜单截图...")

    def open_and_snap_main_menu():
        p = engine.manager._get_active_page_impl()
        p.keyboard.press("Escape")
        p.mouse.click(300, 200)
        time.sleep(0.4)
        var_box = p.locator("#variationImage .overflow-y-auto, #variationImage .max-h-700").first
        headers = var_box.locator(".item-header")
        for i in range(headers.count()):
            h = headers.nth(i)
            if "11" in h.inner_text() and "aa" in h.inner_text():
                h.scroll_into_view_if_needed()
                time.sleep(0.5)
                apply_btn = h.locator("span.link, a, span[class*='link']").filter(has_text="图片应用到").first
                apply_btn.click()
                time.sleep(0.8)

                # 移动鼠标至【主图 ➔ 同カラー(颜色)的变种】选项上方以突出高亮状态
                js_hover_main = """
                () => {
                    const drops = Array.from(document.querySelectorAll('.ant-dropdown'));
                    for (const d of drops) {
                        if (getComputedStyle(d).display === 'none') continue;
                        const groups = d.querySelectorAll('.menu-group');
                        for (const g of groups) {
                            const title = (g.querySelector('.group-title')?.innerText || '').trim();
                            if (!title.includes('主图')) continue;
                            for (const it of g.querySelectorAll('.menu-item')) {
                                if (it.innerText.includes('カラー') || it.innerText.includes('颜色')) {
                                    const r = it.getBoundingClientRect();
                                    return { found: true, x: r.left + r.width / 2, y: r.top + r.height / 2 };
                                }
                            }
                        }
                    }
                    return { found: false };
                }
                """
                pos = p.evaluate(js_hover_main)
                if pos and pos.get("found"):
                    p.mouse.move(pos["x"], pos["y"])
                    time.sleep(0.3)

                snap_path = os.path.join(ARTIFACT_DIR, "step4_click_batch_apply_main_color_menu.png")
                p.screenshot(path=snap_path)
                return snap_path
        return ""

    s4 = engine.manager.run_on_browser_thread(open_and_snap_main_menu)
    print(f"📸 [截图 4] 点击【主图 ➔ 同颜色变体】下拉菜单捕获: {s4}\n")

    # =========================================================================
    # 步骤 5: 执行点击【主图 ➔ 同颜色变体】(颜色 11)
    # =========================================================================
    print("-" * 60)
    print("📸 【步骤 5】执行点击【主图 ➔ 同カラー(颜色)的变种】(颜色11)...")
    apply_main_1_ok = engine.apply_variation_image(
        filter_criteria=FIRST_FILTER,
        apply_type="main_color",
        timeout_ms=15000
    )
    print(f"      颜色11主图批量应用结果: {'✅ 成功' if apply_main_1_ok else '❌ 失败'}")
    time.sleep(1.5)

    def snap_color11_applied():
        p = engine.manager._get_active_page_impl()
        p.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        path = os.path.join(ARTIFACT_DIR, "step5_color11_main_image_applied.png")
        p.screenshot(path=path)
        return path

    s5 = engine.manager.run_on_browser_thread(snap_color11_applied)
    print(f"📸 [截图 5] 颜色11所有尺寸主图同步完成留痕: {s5}\n")

    # =========================================================================
    # 步骤 6: 为第二个颜色 (22 / aa) 上传主图并执行批量应用到同颜色
    # =========================================================================
    second_crit = {"颜色": "22", "尺寸": "aa"}
    print("-" * 60)
    print(f"📸 【步骤 6】为第二个颜色 (カラー: 22 / サイズ: aa) 上传主图 sku2.jpg 并批量应用到同颜色...")
    up_main_2 = engine.upload_variation_image(
        filter_criteria=second_crit,
        image_path=COLOR_MAIN_PLAN[1][1],
        image_type="main",
        timeout_ms=30000
    )
    print(f"      主图上传: {'✅ 成功' if up_main_2 else '❌ 失败'}")
    time.sleep(1)

    apply_main_2_ok = engine.apply_variation_image(
        filter_criteria=second_crit,
        apply_type="main_color",
        timeout_ms=15000
    )
    print(f"      颜色22主图批量应用: {'✅ 成功' if apply_main_2_ok else '❌ 失败'}")
    time.sleep(1.5)

    def snap_color22_applied():
        p = engine.manager._get_active_page_impl()
        p.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        path = os.path.join(ARTIFACT_DIR, "step6_color22_main_image_applied.png")
        p.screenshot(path=path)
        return path

    s6 = engine.manager.run_on_browser_thread(snap_color22_applied)
    print(f"📸 [截图 6] 颜色22所有尺寸主图同步完成留痕: {s6}\n")

    # =========================================================================
    # 步骤 7: 为第三个颜色 (33 / aa) 上传主图并执行批量应用到同颜色
    # =========================================================================
    third_crit = {"颜色": "33", "尺寸": "aa"}
    print("-" * 60)
    print(f"📸 【步骤 7】为第三个颜色 (カラー: 33 / サイズ: aa) 上传主图 sku3.jpg 并批量应用到同颜色...")
    up_main_3 = engine.upload_variation_image(
        filter_criteria=third_crit,
        image_path=COLOR_MAIN_PLAN[2][1],
        image_type="main",
        timeout_ms=30000
    )
    print(f"      主图上传: {'✅ 成功' if up_main_3 else '❌ 失败'}")
    time.sleep(1)

    apply_main_3_ok = engine.apply_variation_image(
        filter_criteria=third_crit,
        apply_type="main_color",
        timeout_ms=15000
    )
    print(f"      颜色33主图批量应用: {'✅ 成功' if apply_main_3_ok else '❌ 失败'}")
    time.sleep(1.5)

    def snap_color33_applied():
        p = engine.manager._get_active_page_impl()
        p.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        path = os.path.join(ARTIFACT_DIR, "step7_color33_main_image_applied.png")
        p.screenshot(path=path)
        return path

    s7 = engine.manager.run_on_browser_thread(snap_color33_applied)
    print(f"📸 [截图 7] 颜色33所有尺寸主图同步完成留痕: {s7}\n")

    # =========================================================================
    # 步骤 8: 变体图片矩阵最终全貌截图与深度 DOM 校验
    # =========================================================================
    print("-" * 60)
    print("📸 【步骤 8】变体图片矩阵最终全貌截图与数据校验...")

    def snap_final_and_verify():
        p = engine.manager._get_active_page_impl()
        p.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(1.0)
        final_path = os.path.join(ARTIFACT_DIR, "step8_final_variation_image_matrix.png")
        p.screenshot(path=final_path)

        # 深度核验每个卡片中的图片结构
        js_audit = """
        () => {
            const cards = Array.from(document.querySelectorAll('#variationImage .item-header')).map(h => {
                const headerText = h.innerText.replace(/\\s+/g, ' ').trim();
                const parent = h.closest('.variation-item, .item-wrap, [class*=\"item\"]') || h.parentElement;
                
                // 查找主图
                const mainImgs = Array.from(parent.querySelectorAll('.main-img img, .main-image img, [class*=\"main\"] img'))
                    .map(img => img.src)
                    .filter(src => src && !src.includes('loading') && !src.includes('default'));

                // 查找附图
                const extraImgs = Array.from(parent.querySelectorAll('.extra-img img, .extra-image img, .sub-img img, [class*=\"extra\"] img, [class*=\"sub\"] img'))
                    .map(img => img.src)
                    .filter(src => src && !src.includes('loading') && !src.includes('default'));

                // 全量图片
                const allImgs = Array.from(parent.querySelectorAll('img'))
                    .map(img => img.src)
                    .filter(src => src && !src.includes('loading') && !src.includes('default') && !src.includes('icon'));

                return {
                    header: headerText,
                    hasMain: mainImgs.length > 0 || allImgs.length >= 1,
                    mainCount: mainImgs.length,
                    extraCount: extraImgs.length,
                    totalValidImages: allImgs.length
                };
            });
            return cards;
        }
        """
        audit_results = p.evaluate(js_audit)
        return final_path, audit_results

    final_shot, audit_results = engine.manager.run_on_browser_thread(snap_final_and_verify)
    print(f"📸 [截图 8] 变体矩阵全貌截图留痕: {final_shot}")
    print("\n📊 变体图片矩阵核验明细:")
    for idx, card in enumerate(audit_results):
        print(f"  变体卡片 {idx+1}: [{card.get('header')}] - 总有效图片数: {card.get('totalValidImages')}, 主图: {card.get('hasMain')}")

    print("=" * 70)
    print("🎉 店小秘 SKU 图片上传与批量应用（附图批量 + 主图批量）测试全部完成！")
    print("=" * 70)
    return True

if __name__ == "__main__":
    main()
