import sys
import os
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine
from core.form_operator import FormOperator

def run_test():
    print("🚀 连接 Chrome 端口 9222 ...", flush=True)
    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect(activate=True)
    if not ok:
        print(f"❌ 连接失败: {msg}")
        return

    def execute_in_browser():
        page = engine.manager._get_active_page_impl()
        form = FormOperator(page)
        print(f"📄 当前活跃页面 URL: {page.url}", flush=True)

        target_url = "https://www.dianxiaomi.com/web/amazon/add"
        if "dianxiaomi.com/web/amazon/add" not in page.url:
            print("🌐 正在导航至店小秘添加产品页面...", flush=True)
            page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(3)

        # 检查是否需要配置变体
        has_variations = page.locator("#variationImage").count() > 0 and page.locator("#variationImage .item-header").count() > 0
        if not has_variations:
            print("⚙️ 页面尚未生成变体，正在自动配置店铺与变体属性...", flush=True)
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
            form.add_variation_option("サイズ", "aa")
            time.sleep(0.5)
            form.add_variation_option("サイズ", "bb")
            time.sleep(1.5)

        headers_count = page.locator("#variationImage .item-header").count()
        print(f"✅ 变体图片卡片总数: {headers_count}", flush=True)

        artifact_dir = "/Users/gx/.gemini/antigravity-ide/brain/bc6c623e-3e59-4b66-9b53-0c5d637be539"
        test_imgs_dir = os.path.join(PROJECT_DIR, "test_images")

        main_img_1 = os.path.join(test_imgs_dir, "black_s.jpg")
        main_img_2 = os.path.join(test_imgs_dir, "white_s.jpg")
        extra_imgs = [
            os.path.join(test_imgs_dir, "blue_s.jpg"),
            os.path.join(test_imgs_dir, "yellow_s.jpg"),
            os.path.join(test_imgs_dir, "blue_m.jpg")
        ]

        # =========================================================================
        # 场景 1: 为第一个 SKU (颜色11 / 尺寸aa) 上传主图 + 3张附图
        # =========================================================================
        first_crit = {"颜色": "11", "尺寸": "aa"}
        print("\n-------------------------------------------------------------")
        print(f"📸 场景 1: 为第一个 SKU {first_crit} 上传主图与多张附图...", flush=True)
        
        page.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(1)

        print("  1.1 上传主图 (black_s.jpg)...", flush=True)
        up_main_1 = form.upload_variation_image(
            filter_criteria=first_crit,
            image_path=main_img_1,
            image_type="main",
            timeout_ms=30000
        )
        print(f"      主图上传: {'✅ 成功' if up_main_1 else '❌ 失败'}")
        time.sleep(1)

        print("  1.2 上传附图 (3张: blue_s, yellow_s, blue_m)...", flush=True)
        up_extra_1 = form.upload_variation_image(
            filter_criteria=first_crit,
            image_path=extra_imgs,
            image_type="extra",
            timeout_ms=45000
        )
        print(f"      附图上传: {'✅ 成功' if up_extra_1 else '❌ 失败'}")
        time.sleep(1)

        # 截图 1: 第一个 SKU 图片上传完成
        snap1 = os.path.join(artifact_dir, "sku_scenario1_first_sku_uploaded.png")
        page.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        page.screenshot(path=snap1)
        print(f"  📸 截图已留存: {snap1}")

        # =========================================================================
        # 场景 2: 点击「图片应用到」并展示【附图 ➔ 所有变体】下拉菜单
        # =========================================================================
        print("\n-------------------------------------------------------------")
        print("📸 场景 2: 触发「图片应用到」下拉菜单（附图批量应用）...", flush=True)
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

            # 截图 2: 附图下拉菜单展开
            snap2 = os.path.join(artifact_dir, "sku_scenario2_dropdown_extra_all.png")
            page.screenshot(path=snap2)
            print(f"  📸 截图已留存 (下拉菜单展开展示【附图-所有变体】): {snap2}")

            # 执行点击【附图 ➔ 所有变体】
            print("  2.2 执行批量应用: 附图 ➔ 所有变体...", flush=True)
            apply_extra_ok = form.apply_variation_image(
                filter_criteria=first_crit,
                apply_type="extra_all",
                timeout_ms=15000
            )
            print(f"      附图批量应用结果: {'✅ 成功' if apply_extra_ok else '❌ 失败'}")
            time.sleep(1.5)

            # 截图 3: 附图成功批量应用到所有变体
            snap3 = os.path.join(artifact_dir, "sku_scenario2_extra_applied_to_all.png")
            page.screenshot(path=snap3)
            print(f"  📸 截图已留存 (附图已同步至全部变体卡片): {snap3}")

        # =========================================================================
        # 场景 3: 点击「图片应用到」并展示【主图 ➔ 同カラー(颜色)的变种】
        # =========================================================================
        print("\n-------------------------------------------------------------")
        print("📸 场景 3: 触发「图片应用到」下拉菜单（主图按颜色批量应用）...", flush=True)
        page.keyboard.press("Escape")
        time.sleep(0.3)

        if target_header:
            target_header.scroll_into_view_if_needed()
            time.sleep(0.5)
            apply_btn = target_header.locator("span.link, a, span[class*='link']").filter(has_text="图片应用到").first
            apply_btn.click()
            time.sleep(1.0)

            # 截图 4: 主图下拉菜单展开
            snap4 = os.path.join(artifact_dir, "sku_scenario3_dropdown_main_color.png")
            page.screenshot(path=snap4)
            print(f"  📸 截图已留存 (下拉菜单展开展示【主图-同カラー(颜色)的变种】): {snap4}")

            # 执行点击【主图 ➔ 同颜色变体】
            print("  3.2 执行批量应用: 主图 ➔ 同颜色变体...", flush=True)
            apply_main_1_ok = form.apply_variation_image(
                filter_criteria=first_crit,
                apply_type="main_color",
                timeout_ms=15000
            )
            print(f"      主图(颜色11)批量应用结果: {'✅ 成功' if apply_main_1_ok else '❌ 失败'}")
            time.sleep(1.5)

            # 截图 5: 颜色11的所有尺寸卡片主图已应用
            snap5 = os.path.join(artifact_dir, "sku_scenario3_color11_main_applied.png")
            page.screenshot(path=snap5)
            print(f"  📸 截图已留存 (颜色11所有尺寸主图已同步): {snap5}")

        # =========================================================================
        # 场景 4: 为第二个颜色 (22 / aa) 上传主图并批量应用到同颜色
        # =========================================================================
        second_crit = {"颜色": "22", "尺寸": "aa"}
        print("\n-------------------------------------------------------------")
        print(f"📸 场景 4: 为第二个颜色 {second_crit} 上传主图并批量应用到同颜色...", flush=True)
        
        print("  4.1 上传颜色22主图 (white_s.jpg)...", flush=True)
        up_main_2 = form.upload_variation_image(
            filter_criteria=second_crit,
            image_path=main_img_2,
            image_type="main",
            timeout_ms=30000
        )
        print(f"      颜色22主图上传: {'✅ 成功' if up_main_2 else '❌ 失败'}")
        time.sleep(1)

        print("  4.2 执行批量应用: 主图 ➔ 同颜色变体...", flush=True)
        apply_main_2_ok = form.apply_variation_image(
            filter_criteria=second_crit,
            apply_type="main_color",
            timeout_ms=15000
        )
        print(f"      主图(颜色22)批量应用结果: {'✅ 成功' if apply_main_2_ok else '❌ 失败'}")
        time.sleep(1.5)

        # 截图 6: 颜色22的所有尺寸卡片主图已应用
        snap6 = os.path.join(artifact_dir, "sku_scenario4_color22_main_applied.png")
        page.screenshot(path=snap6)
        print(f"  📸 截图已留存 (颜色22所有尺寸主图已同步): {snap6}")

        # =========================================================================
        # 场景 5: 全局最终变体矩阵全貌留存
        # =========================================================================
        print("\n-------------------------------------------------------------")
        print("📸 场景 5: 最终变体矩阵所有 SKU 主附图完整配置全貌留存...", flush=True)
        page.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(1)
        snap7 = os.path.join(artifact_dir, "sku_scenario5_final_full_matrix.png")
        page.screenshot(path=snap7)
        print(f"  📸 最终全貌截图已留存: {snap7}")

        print("\n🎉 SKU 图片上传与全部批量应用测试场景执行完毕，全部截图已留存！", flush=True)

    engine.manager.run_on_browser_thread(execute_in_browser)

if __name__ == "__main__":
    run_test()
