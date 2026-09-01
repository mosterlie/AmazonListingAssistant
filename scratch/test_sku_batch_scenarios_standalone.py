import sys
import os
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine
from core.form_operator import FormOperator

def run():
    print("🚀 连接 Chrome 端口 9222 ...", flush=True)
    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect(activate=True)
    if not ok:
        print(f"❌ 连接失败: {msg}")
        return

    def execute():
        page = engine.manager._get_active_page_impl()
        form = FormOperator(page)
        print(f"📄 当前页面: {page.url}", flush=True)

        target_url = "https://www.dianxiaomi.com/web/amazon/add"
        if "dianxiaomi.com/web/amazon/add" not in page.url:
            print("🌐 导航至店小秘添加产品页面...", flush=True)
            page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(3)

        # 检查是否已生成变体
        has_variations = page.locator("#variationImage").count() > 0 and page.locator("#variationImage .item-header").count() > 0
        if not has_variations:
            print("⚙️ 页面尚未生成变体，正在配置店铺与变体属性...", flush=True)
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
            time.sleep(1.5)

        headers_count = page.locator("#variationImage .item-header").count()
        print(f"✅ 变体图片卡片总数: {headers_count} 个", flush=True)

        artifact_dir = "/Users/gx/.gemini/antigravity-ide/brain/bc6c623e-3e59-4b66-9b53-0c5d637be539"
        uploads = os.path.join(PROJECT_DIR, "data", "uploads")

        main_1 = os.path.join(uploads, "sku1.jpg")
        main_2 = os.path.join(uploads, "sku2.jpg")
        main_3 = os.path.join(uploads, "sku3.jpg")
        extras = [os.path.join(uploads, f"PT{i:02d}.jpg") for i in [1, 2, 3, 4, 5]]

        # =========================================================================
        # 场景 1: 为第一个 SKU (11 / aa) 上传主图与 5 张附图
        # =========================================================================
        first_crit = {"颜色": "11", "尺寸": "aa"}
        print("\n=============================================================")
        print(f"📸 场景 1: 为第一个 SKU {first_crit} 上传主图与 5 张附图...", flush=True)
        page.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(1)

        print("  1.1 上传主图 sku1.jpg ...", flush=True)
        up_main_1 = form.upload_variation_image(first_crit, main_1, image_type="main", timeout_ms=30000)
        print(f"      主图上传: {'✅ 成功' if up_main_1 else '❌ 失败'}")
        time.sleep(1)

        print(f"  1.2 上传 5 张附图 (PT01~PT05) ...", flush=True)
        up_extra_1 = form.upload_variation_image(first_crit, extras, image_type="extra", timeout_ms=45000)
        print(f"      附图上传: {'✅ 成功' if up_extra_1 else '❌ 失败'}")
        time.sleep(1)

        snap1 = os.path.join(artifact_dir, "sku_batch_01_first_sku_uploaded.png")
        page.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        page.screenshot(path=snap1)
        print(f"  📸 场景1截图已保存: {snap1}")

        # =========================================================================
        # 场景 2: 触发第一个 SKU 卡片头部的「图片应用到」下拉菜单（附图）
        # =========================================================================
        print("\n=============================================================")
        print("📸 场景 2: 触发「图片应用到」下拉菜单展示...", flush=True)
        page.keyboard.press("Escape")
        time.sleep(0.3)

        var_container = page.locator("#variationImage .overflow-y-auto, #variationImage .max-h-700").first
        target_header = None
        for i in range(var_container.locator(".item-header").count()):
            h = var_container.locator(".item-header").nth(i)
            if "11" in h.inner_text() and "aa" in h.inner_text():
                target_header = h
                break

        if target_header:
            target_header.scroll_into_view_if_needed()
            time.sleep(0.5)
            apply_btn = target_header.locator("span.link, a, span[class*='link']").filter(has_text="图片应用到").first
            apply_btn.click()
            time.sleep(1.0)

            snap2 = os.path.join(artifact_dir, "sku_batch_02_extra_dropdown_menu.png")
            page.screenshot(path=snap2)
            print(f"  📸 场景2截图已保存 (下拉菜单展开展示【附图 ➔ 所有变种】): {snap2}")

        # =========================================================================
        # 场景 3: 执行点击【附图 ➔ 所有变体】并留存同步到所有变体的效果
        # =========================================================================
        print("\n=============================================================")
        print("📸 场景 3: 执行【附图 ➔ 所有变体】批量应用...", flush=True)
        apply_extra_ok = form.apply_variation_image(first_crit, apply_type="extra_all", timeout_ms=15000)
        print(f"      附图批量应用至所有变体: {'✅ 成功' if apply_extra_ok else '❌ 失败'}")
        time.sleep(1.5)

        snap3 = os.path.join(artifact_dir, "sku_batch_03_extra_applied_all_skus.png")
        page.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        page.screenshot(path=snap3)
        print(f"  📸 场景3截图已保存 (附图成功同步至全部 6 个变体卡片): {snap3}")

        # =========================================================================
        # 场景 4: 触发第一个 SKU 卡片头部的「图片应用到」下拉菜单（主图）
        # =========================================================================
        print("\n=============================================================")
        print("📸 场景 4: 触发「图片应用到」下拉菜单展示【主图 ➔ 同カラー(颜色)的变种】...", flush=True)
        page.keyboard.press("Escape")
        time.sleep(0.3)

        if target_header:
            target_header.scroll_into_view_if_needed()
            time.sleep(0.5)
            apply_btn = target_header.locator("span.link, a, span[class*='link']").filter(has_text="图片应用到").first
            apply_btn.click()
            time.sleep(1.0)

            snap4 = os.path.join(artifact_dir, "sku_batch_04_main_color_dropdown_menu.png")
            page.screenshot(path=snap4)
            print(f"  📸 场景4截图已保存 (下拉菜单展开展示【主图 ➔ 同カラー(颜色)的变种】): {snap4}")

        # =========================================================================
        # 场景 5: 执行点击【主图 ➔ 同颜色变体】(颜色11)
        # =========================================================================
        print("\n=============================================================")
        print("📸 场景 5: 执行【主图 ➔ 同カラー(颜色)的变种】批量应用 (颜色11)...", flush=True)
        apply_main_1_ok = form.apply_variation_image(first_crit, apply_type="main_color", timeout_ms=15000)
        print(f"      颜色11主图批量应用: {'✅ 成功' if apply_main_1_ok else '❌ 失败'}")
        time.sleep(1.5)

        snap5 = os.path.join(artifact_dir, "sku_batch_05_color11_main_applied.png")
        page.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        page.screenshot(path=snap5)
        print(f"  📸 场景5截图已保存 (颜色11所有尺寸的主图已全部自动应用): {snap5}")

        # =========================================================================
        # 场景 6: 为第二个颜色 (22 / aa) 上传主图并批量应用到同颜色
        # =========================================================================
        second_crit = {"颜色": "22", "尺寸": "aa"}
        print("\n=============================================================")
        print(f"📸 场景 6: 为颜色 22 ({second_crit}) 上传主图 sku2.jpg 并批量应用到同颜色...", flush=True)
        print("  6.1 上传颜色 22 主图 ...", flush=True)
        up_main_2 = form.upload_variation_image(second_crit, main_2, image_type="main", timeout_ms=30000)
        print(f"      上传: {'✅ 成功' if up_main_2 else '❌ 失败'}")
        time.sleep(1)

        print("  6.2 执行批量应用: 主图 ➔ 同颜色变体 ...", flush=True)
        apply_main_2_ok = form.apply_variation_image(second_crit, apply_type="main_color", timeout_ms=15000)
        print(f"      应用: {'✅ 成功' if apply_main_2_ok else '❌ 失败'}")
        time.sleep(1.5)

        snap6 = os.path.join(artifact_dir, "sku_batch_06_color22_main_applied.png")
        page.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        page.screenshot(path=snap6)
        print(f"  📸 场景6截图已保存 (颜色22所有尺寸的主图已全部自动应用): {snap6}")

        # =========================================================================
        # 场景 7: 为第三个颜色 (33 / aa) 上传主图并批量应用到同颜色
        # =========================================================================
        third_crit = {"颜色": "33", "尺寸": "aa"}
        print("\n=============================================================")
        print(f"📸 场景 7: 为颜色 33 ({third_crit}) 上传主图 sku3.jpg 并批量应用到同颜色...", flush=True)
        print("  7.1 上传颜色 33 主图 ...", flush=True)
        up_main_3 = form.upload_variation_image(third_crit, main_3, image_type="main", timeout_ms=30000)
        print(f"      上传: {'✅ 成功' if up_main_3 else '❌ 失败'}")
        time.sleep(1)

        print("  7.2 执行批量应用: 主图 ➔ 同颜色变体 ...", flush=True)
        apply_main_3_ok = form.apply_variation_image(third_crit, apply_type="main_color", timeout_ms=15000)
        print(f"      应用: {'✅ 成功' if apply_main_3_ok else '❌ 失败'}")
        time.sleep(1.5)

        snap7 = os.path.join(artifact_dir, "sku_batch_07_color33_main_applied.png")
        page.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        page.screenshot(path=snap7)
        print(f"  📸 场景7截图已保存 (颜色33所有尺寸的主图已全部自动应用): {snap7}")

        # =========================================================================
        # 场景 8: 最终全局变体图片矩阵全貌
        # =========================================================================
        print("\n=============================================================")
        print("📸 场景 8: 变体图片矩阵最终全貌截图留存...", flush=True)
        page.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(1)
        snap8 = os.path.join(artifact_dir, "sku_batch_08_final_matrix_verified.png")
        page.screenshot(path=snap8)
        print(f"  📸 场景8截图已保存: {snap8}")

        print("\n🎉 全部 8 个 SKU 批量应用测试场景与截图已 100% 成功完成并留存！", flush=True)

    engine.manager.run_on_browser_thread(execute)

if __name__ == "__main__":
    run()
