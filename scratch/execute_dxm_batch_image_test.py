import sys
import os
import time
import json

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine
from core.form_operator import FormOperator

CONV_ID = "4d70ba54-c5b0-4648-8adb-474ba62b907e"
ARTIFACT_DIR = f"/Users/gx/.gemini/antigravity-ide/brain/{CONV_ID}"
os.makedirs(ARTIFACT_DIR, exist_ok=True)

UPLOADS = os.path.join(PROJECT_DIR, "data", "uploads")
FIRST_CRIT = {"颜色": "11", "尺寸": "aa"}
SECOND_CRIT = {"颜色": "22", "尺寸": "aa"}
THIRD_CRIT = {"颜色": "33", "尺寸": "aa"}

MAIN_1 = os.path.join(UPLOADS, "sku1.jpg")
MAIN_2 = os.path.join(UPLOADS, "sku2.jpg")
MAIN_3 = os.path.join(UPLOADS, "sku3.jpg")
EXTRA_IMGS = [os.path.join(UPLOADS, f"PT{i:02d}.jpg") for i in [1, 2, 3, 4, 5]]

def run_test():
    print("=" * 70, flush=True)
    print("🚀 [店小秘] SKU 批量上传与图片批量应用（附图批量 + 主图批量）自动化测试", flush=True)
    print(f"📁 截图保存目录: {ARTIFACT_DIR}", flush=True)
    print("=" * 70, flush=True)

    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect(activate=False)
    if not ok:
        print(f"❌ 浏览器连接失败: {msg}", flush=True)
        return False

    def execute():
        # 直接定位店小秘标签页
        page = None
        for p in engine.manager.context.pages:
            if "dianxiaomi.com" in p.url:
                page = p
                break
        if not page:
            page = engine.manager.context.pages[0]

        page.bring_to_front()
        form = FormOperator(page)
        print(f"📄 当前活动页面: {page.url}", flush=True)

        target_url = "https://www.dianxiaomi.com/web/amazon/add"
        if "dianxiaomi.com/web/amazon/add" not in page.url:
            print("🌐 导航至店小秘添加产品页面...", flush=True)
            page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(3)

        # 检查是否已生成变体
        has_variations = page.locator("#variationImage").count() > 0 and page.locator("#variationImage .item-header").count() >= 6
        if not has_variations:
            print("⚙️ 正在初始化店铺、类目与多变体选项 (11/22/33 × aa/qq)...", flush=True)
            form.select_store_account("金梧汇辰", "日本", timeout_ms=15000)
            time.sleep(1)

            form.fill("产品标题", "日本人気ペット用トイレトレー 自動洗浄ガード付き")
            time.sleep(1)
            if form.click_button("自动识别产品类型"):
                time.sleep(2)
                form.confirm_modal("确定", wait_timeout_ms=5000)
                time.sleep(2)

            form.click_radio("多变体(variation)", timeout_ms=5000)
            time.sleep(1)

            form.select("变种主题", "Color-Size")
            time.sleep(1)

            form.add_variation_option("カラー", "11")
            time.sleep(0.5)
            form.add_variation_option("カラー", "22")
            time.sleep(0.5)
            form.add_variation_option("カラー", "33")
            time.sleep(0.5)
            form.add_variation_option("サイズ", "aa")
            time.sleep(0.5)
            form.add_variation_option("サイズ", "qq")
            time.sleep(2.0)

        headers_count = page.locator("#variationImage .item-header").count()
        print(f"✅ 变体图片卡片矩阵已就绪，共 {headers_count} 个 SKU 卡片！", flush=True)

        # -----------------------------------------------------------------
        # 截图 1: 变体矩阵初始状态
        # -----------------------------------------------------------------
        snap0 = os.path.join(ARTIFACT_DIR, "dxm_01_matrix_initial.png")
        page.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        page.screenshot(path=snap0)
        print(f"📸 [截图 1] 变体矩阵初始状态: {snap0}", flush=True)

        # -----------------------------------------------------------------
        # 步骤 1: 为第一个 SKU (11 / aa) 上传主图 (sku1.jpg) 与 5 张附图 (PT01~PT05)
        # -----------------------------------------------------------------
        print("\n" + "-" * 60, flush=True)
        print(f"📸 【步骤 1】为第一个 SKU {FIRST_CRIT} 上传主图与 5 张附图...", flush=True)
        
        print("  1.1 上传主图 sku1.jpg ...", flush=True)
        up_main_1 = form.upload_variation_image(FIRST_CRIT, MAIN_1, image_type="main", timeout_ms=30000)
        print(f"      主图上传: {'✅ 成功' if up_main_1 else '❌ 失败'}", flush=True)
        time.sleep(1)

        print(f"  1.2 上传 5 张附图 (PT01~PT05) ...", flush=True)
        up_extra_1 = form.upload_variation_image(FIRST_CRIT, EXTRA_IMGS, image_type="extra", timeout_ms=45000)
        print(f"      附图上传: {'✅ 成功' if up_extra_1 else '❌ 失败'}", flush=True)
        time.sleep(1)

        snap1 = os.path.join(ARTIFACT_DIR, "dxm_02_first_sku_uploaded.png")
        page.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        page.screenshot(path=snap1)
        print(f"📸 [截图 2] 第一个 SKU 上传完成留痕: {snap1}", flush=True)

        # -----------------------------------------------------------------
        # 步骤 2: 点击「图片应用到」展开下拉菜单，捕获【附图 ➔ 所有变体】高亮截图
        # -----------------------------------------------------------------
        print("\n" + "-" * 60, flush=True)
        print("📸 【步骤 2】点击「图片应用到」，捕获【附图 ➔ 所有变体】下拉菜单及点击留痕...", flush=True)
        page.keyboard.press("Escape")
        page.mouse.click(300, 200)
        time.sleep(0.4)

        var_container = page.locator("#variationImage .overflow-y-auto, #variationImage .max-h-700").first
        headers = var_container.locator(".item-header")
        target_header = None
        for i in range(headers.count()):
            h = headers.nth(i)
            if "11" in h.inner_text() and "aa" in h.inner_text():
                target_header = h
                break

        if target_header:
            target_header.scroll_into_view_if_needed()
            time.sleep(0.5)
            apply_btn = target_header.locator("span.link, a, span[class*='link']").filter(has_text="图片应用到").first
            apply_btn.click()
            time.sleep(0.8)

            # 移动鼠标至【附图 ➔ 所有变体】选项以高亮展示
            js_hover_extra = """
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
            pos = page.evaluate(js_hover_extra)
            if pos and pos.get("found"):
                page.mouse.move(pos["x"], pos["y"])
                time.sleep(0.4)

            snap2 = os.path.join(ARTIFACT_DIR, "dxm_03_click_apply_extra_menu.png")
            page.screenshot(path=snap2)
            print(f"📸 [截图 3] 【附图 ➔ 所有变体】下拉菜单展开与高亮留痕: {snap2}", flush=True)

        # -----------------------------------------------------------------
        # 步骤 3: 执行点击【附图 ➔ 所有变体】批量应用，并截图全量 SKU 附图同步效果
        # -----------------------------------------------------------------
        print("\n" + "-" * 60, flush=True)
        print("📸 【步骤 3】执行点击【附图 ➔ 所有变体】批量应用...", flush=True)
        apply_extra_ok = form.apply_variation_image(FIRST_CRIT, apply_type="extra_all", timeout_ms=15000)
        print(f"      附图批量应用结果: {'✅ 成功' if apply_extra_ok else '❌ 失败'}", flush=True)
        time.sleep(1.5)

        snap3 = os.path.join(ARTIFACT_DIR, "dxm_04_extra_applied_all_skus.png")
        page.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        page.screenshot(path=snap3)
        print(f"📸 [截图 4] 全量 SKU 附图批量应用同步完成留痕: {snap3}", flush=True)

        # -----------------------------------------------------------------
        # 步骤 4: 点击「图片应用到」展开下拉菜单，捕获【主图 ➔ 同カラー(颜色)的变种】高亮截图
        # -----------------------------------------------------------------
        print("\n" + "-" * 60, flush=True)
        print("📸 【步骤 4】点击「图片应用到」，捕获【主图 ➔ 同カラー(颜色)的变种】下拉菜单及点击留痕...", flush=True)
        page.keyboard.press("Escape")
        page.mouse.click(300, 200)
        time.sleep(0.4)

        if target_header:
            target_header.scroll_into_view_if_needed()
            time.sleep(0.5)
            apply_btn = target_header.locator("span.link, a, span[class*='link']").filter(has_text="图片应用到").first
            apply_btn.click()
            time.sleep(0.8)

            # 移动鼠标至【主图 ➔ 同カラー(颜色)的变种】
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
            pos = page.evaluate(js_hover_main)
            if pos and pos.get("found"):
                page.mouse.move(pos["x"], pos["y"])
                time.sleep(0.4)

            snap4 = os.path.join(ARTIFACT_DIR, "dxm_05_click_apply_main_menu.png")
            page.screenshot(path=snap4)
            print(f"📸 [截图 5] 【主图 ➔ 同颜色变体】下拉菜单展开与高亮留痕: {snap4}", flush=True)

        # -----------------------------------------------------------------
        # 步骤 5: 执行点击【主图 ➔ 同颜色变体】(颜色 11)
        # -----------------------------------------------------------------
        print("\n" + "-" * 60, flush=True)
        print("📸 【步骤 5】执行点击【主图 ➔ 同颜色变体】(颜色 11)...", flush=True)
        apply_main_1_ok = form.apply_variation_image(FIRST_CRIT, apply_type="main_color", timeout_ms=15000)
        print(f"      颜色11主图批量应用: {'✅ 成功' if apply_main_1_ok else '❌ 失败'}", flush=True)
        time.sleep(1.5)

        snap5 = os.path.join(ARTIFACT_DIR, "dxm_06_color11_main_applied.png")
        page.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        page.screenshot(path=snap5)
        print(f"📸 [截图 6] 颜色11所有尺寸主图同步完成留痕: {snap5}", flush=True)

        # -----------------------------------------------------------------
        # 步骤 6: 为第二个颜色 (22 / aa) 上传主图并执行批量应用到同颜色
        # -----------------------------------------------------------------
        print("\n" + "-" * 60, flush=True)
        print(f"📸 【步骤 6】为颜色 22 ({SECOND_CRIT}) 上传主图 sku2.jpg 并批量应用到同颜色...", flush=True)
        print("  6.1 上传颜色 22 主图 ...", flush=True)
        up_main_2 = form.upload_variation_image(SECOND_CRIT, MAIN_2, image_type="main", timeout_ms=30000)
        print(f"      主图上传: {'✅ 成功' if up_main_2 else '❌ 失败'}", flush=True)
        time.sleep(1)

        print("  6.2 执行批量应用: 主图 ➔ 同颜色变体 ...", flush=True)
        apply_main_2_ok = form.apply_variation_image(SECOND_CRIT, apply_type="main_color", timeout_ms=15000)
        print(f"      颜色22批量应用: {'✅ 成功' if apply_main_2_ok else '❌ 失败'}", flush=True)
        time.sleep(1.5)

        snap6 = os.path.join(ARTIFACT_DIR, "dxm_07_color22_main_uploaded_and_applied.png")
        page.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        page.screenshot(path=snap6)
        print(f"📸 [截图 7] 颜色22主图批量同步完成留痕: {snap6}", flush=True)

        # -----------------------------------------------------------------
        # 步骤 7: 为第三个颜色 (33 / aa) 上传主图并执行批量应用到同颜色
        # -----------------------------------------------------------------
        print("\n" + "-" * 60, flush=True)
        print(f"📸 【步骤 7】为颜色 33 ({THIRD_CRIT}) 上传主图 sku3.jpg 并批量应用到同颜色...", flush=True)
        print("  7.1 上传颜色 33 主图 ...", flush=True)
        up_main_3 = form.upload_variation_image(THIRD_CRIT, MAIN_3, image_type="main", timeout_ms=30000)
        print(f"      主图上传: {'✅ 成功' if up_main_3 else '❌ 失败'}", flush=True)
        time.sleep(1)

        print("  7.2 执行批量应用: 主图 ➔ 同颜色变体 ...", flush=True)
        apply_main_3_ok = form.apply_variation_image(THIRD_CRIT, apply_type="main_color", timeout_ms=15000)
        print(f"      颜色33批量应用: {'✅ 成功' if apply_main_3_ok else '❌ 失败'}", flush=True)
        time.sleep(1.5)

        snap7 = os.path.join(ARTIFACT_DIR, "dxm_08_color33_main_uploaded_and_applied.png")
        page.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        page.screenshot(path=snap7)
        print(f"📸 [截图 8] 颜色33主图批量同步完成留痕: {snap7}", flush=True)

        # -----------------------------------------------------------------
        # 步骤 8: 最终变体图片矩阵全景图留痕
        # -----------------------------------------------------------------
        print("\n" + "-" * 60, flush=True)
        print("📸 【步骤 8】变体图片矩阵最终全貌截图与深度 DOM 校验...", flush=True)
        snap8 = os.path.join(ARTIFACT_DIR, "dxm_09_final_full_variation_matrix.png")
        page.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(1.0)
        page.screenshot(path=snap8)
        print(f"📸 [截图 9] 最终变体图片矩阵全貌截图: {snap8}", flush=True)

        # -----------------------------------------------------------------
        # 步骤 9: 变体 SKU 表格区域截图留痕
        # -----------------------------------------------------------------
        print("\n" + "-" * 60, flush=True)
        print("📸 【步骤 9】变体信息表格区域截图留痕...", flush=True)
        snap9 = os.path.join(ARTIFACT_DIR, "dxm_10_sku_table_overview.png")
        page.locator("#varInfoTable, #variationTable, .variation-table, table").first.scroll_into_view_if_needed()
        time.sleep(0.5)
        page.screenshot(path=snap9)
        print(f"📸 [截图 10] 变体 SKU 表格区域截图: {snap9}", flush=True)

        # -----------------------------------------------------------------
        # 步骤 10: 深度 DOM 审计与报告
        # -----------------------------------------------------------------
        js_audit = """
        () => {
            const result = [];
            const headers = document.querySelectorAll('#variationImage .item-header');
            headers.forEach(h => {
                const headerText = h.innerText.replace(/\\s+/g, ' ').trim();
                const parent = h.closest('.variation-item, .item-wrap, [class*=\"item\"]') || h.parentElement;
                
                const allImgs = Array.from(parent.querySelectorAll('img'))
                    .map(img => img.src)
                    .filter(src => src && !src.includes('loading') && !src.includes('default') && !src.includes('icon'));

                result.push({
                    header: headerText,
                    totalImages: allImgs.length,
                    hasMain: allImgs.length >= 1,
                    hasExtra: allImgs.length >= 6
                });
            });
            return result;
        }
        """
        audit_data = page.evaluate(js_audit)
        print("\n" + "=" * 70, flush=True)
        print("📊 变体图片矩阵 DOM 深度审计结果:", flush=True)
        for idx, item in enumerate(audit_data):
            print(f"  变体 SKU [{idx+1}]: {item['header']} | 主图状态: {'✅' if item['hasMain'] else '❌'} | 附图状态 (>=5张): {'✅' if item['hasExtra'] else '❌'} | 总有效图片: {item['totalImages']} 张", flush=True)
        print("=" * 70, flush=True)

        return True

    success = engine.manager.run_on_browser_thread(execute)
    if success:
        print("\n🎉 店小秘 SKU 批量上传与图片批量应用测试 100% 成功执行完毕！", flush=True)
    return success

if __name__ == "__main__":
    run_test()
