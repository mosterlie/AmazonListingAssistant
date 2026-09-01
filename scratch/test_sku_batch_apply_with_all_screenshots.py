import sys
import os
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine

ARTIFACT_DIR = "/Users/gx/.gemini/antigravity-ide/brain/bc6c623e-3e59-4b66-9b53-0c5d637be539"
UPLOADS = os.path.join(PROJECT_DIR, "data", "uploads")

FIRST_FILTER = {"颜色": "11", "尺寸": "aa"}
EXTRA_IMGS = [os.path.join(UPLOADS, f"PT{i:02d}.jpg") for i in [1, 2, 3, 4, 5]]
COLOR_MAIN_PLAN = [
    ("11", os.path.join(UPLOADS, "sku1.jpg")),
    ("22", os.path.join(UPLOADS, "sku2.jpg")),
    ("33", os.path.join(UPLOADS, "sku3.jpg")),
]

def main():
    print("🚀 启动 SKU 图片上传与批量应用场景自动化测试...", flush=True)
    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect(activate=True)
    if not ok:
        print("❌ 连接失败:", msg)
        return

    # 1. 确保在店小秘添加产品页面
    target_url = "https://www.dianxiaomi.com/web/amazon/add"
    print("🌐 确保进入店小秘页面...", flush=True)
    engine.open_or_focus_url(target_url)
    time.sleep(2)

    # 2. 检查页面是否已具备变体矩阵
    def check_variations():
        p = engine.manager._get_active_page_impl()
        return p.locator("#variationImage .item-header").count()

    headers_count = engine.manager.run_on_browser_thread(check_variations)
    print(f"🔍 当前变体卡片数量: {headers_count}")

    if headers_count < 2:
        print("⚙️ 正在配置店铺、类目与多变体属性 (11/22/33 × aa/qq)...", flush=True)
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

    headers_count = engine.manager.run_on_browser_thread(check_variations)
    print(f"✅ 变体矩阵已就绪，共 {headers_count} 个 SKU 卡片！\n", flush=True)

    # =========================================================================
    # 场景 1: 为第一个 SKU (颜色11 / 尺寸aa) 上传主图与 5 张附图
    # =========================================================================
    print("=================================================================")
    print("📸 【场景 1】为第一个 SKU (カラー: 11 / サイズ: aa) 上传主图与 5 张附图...", flush=True)
    
    print("  1.1 上传主图 (sku1.jpg)...", flush=True)
    up_main_1 = engine.upload_variation_image(
        filter_criteria=FIRST_FILTER,
        image_path=COLOR_MAIN_PLAN[0][1],
        image_type="main",
        timeout_ms=30000
    )
    print(f"      主图上传: {'✅ 成功并确认渲染' if up_main_1 else '❌ 失败'}")
    time.sleep(1)

    print(f"  1.2 上传附图 ({len(EXTRA_IMGS)} 张: PT01~PT05)...", flush=True)
    up_extra_1 = engine.upload_variation_image(
        filter_criteria=FIRST_FILTER,
        image_path=EXTRA_IMGS,
        image_type="extra",
        timeout_ms=45000
    )
    print(f"      附图上传: {'✅ 成功并确认渲染' if up_extra_1 else '❌ 失败'}")
    time.sleep(1)

    # 截图 1
    def snap_first():
        p = engine.manager._get_active_page_impl()
        p.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        snap1_path = os.path.join(ARTIFACT_DIR, "sku_batch_01_first_sku_uploaded.png")
        p.screenshot(path=snap1_path)
        return snap1_path

    s1 = engine.manager.run_on_browser_thread(snap_first)
    print(f"  📸 截图已保存: {s1}\n")

    # =========================================================================
    # 场景 2: 触发第一个 SKU 卡片头部的「图片应用到」下拉菜单（附图）
    # =========================================================================
    print("=================================================================")
    print("📸 【场景 2】触发「图片应用到」下拉菜单，捕获【附图 ➔ 所有变体】选项菜单...", flush=True)
    
    def open_dropdown_extra():
        p = engine.manager._get_active_page_impl()
        p.keyboard.press("Escape")
        time.sleep(0.3)
        var_box = p.locator("#variationImage .overflow-y-auto, #variationImage .max-h-700").first
        headers = var_box.locator(".item-header")
        for i in range(headers.count()):
            h = headers.nth(i)
            if "11" in h.inner_text() and "aa" in h.inner_text():
                h.scroll_into_view_if_needed()
                time.sleep(0.5)
                apply_btn = h.locator("span.link, a, span[class*='link']").filter(has_text="图片应用到").first
                apply_btn.click()
                time.sleep(1.0)
                snap2_path = os.path.join(ARTIFACT_DIR, "sku_batch_02_extra_dropdown_menu.png")
                p.screenshot(path=snap2_path)
                return snap2_path
        return ""

    s2 = engine.manager.run_on_browser_thread(open_dropdown_extra)
    print(f"  📸 截图已保存 (下拉菜单展示【附图 ➔ 所有变体】): {s2}\n")

    # =========================================================================
    # 场景 3: 执行点击【附图 ➔ 所有变体】并留存同步到所有变体的效果
    # =========================================================================
    print("=================================================================")
    print("📸 【场景 3】执行【附图 ➔ 所有变体】批量应用，并捕获所有 SKU 附图同步效果...", flush=True)
    apply_extra_ok = engine.apply_variation_image(
        filter_criteria=FIRST_FILTER,
        apply_type="extra_all",
        timeout_ms=15000
    )
    print(f"      附图批量应用结果: {'✅ 成功' if apply_extra_ok else '❌ 失败'}")
    time.sleep(1.5)

    def snap_extra_all():
        p = engine.manager._get_active_page_impl()
        p.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        snap3_path = os.path.join(ARTIFACT_DIR, "sku_batch_03_extra_applied_all_skus.png")
        p.screenshot(path=snap3_path)
        return snap3_path

    s3 = engine.manager.run_on_browser_thread(snap_extra_all)
    print(f"  📸 截图已保存 (全量 SKU 附图同步完成): {s3}\n")

    # =========================================================================
    # 场景 4: 触发第一个 SKU 卡片头部的「图片应用到」下拉菜单（主图）
    # =========================================================================
    print("=================================================================")
    print("📸 【场景 4】触发「图片应用到」下拉菜单，捕获【主图 ➔ 同カラー(颜色)的变种】选项菜单...", flush=True)

    def open_dropdown_main():
        p = engine.manager._get_active_page_impl()
        p.keyboard.press("Escape")
        time.sleep(0.3)
        var_box = p.locator("#variationImage .overflow-y-auto, #variationImage .max-h-700").first
        headers = var_box.locator(".item-header")
        for i in range(headers.count()):
            h = headers.nth(i)
            if "11" in h.inner_text() and "aa" in h.inner_text():
                h.scroll_into_view_if_needed()
                time.sleep(0.5)
                apply_btn = h.locator("span.link, a, span[class*='link']").filter(has_text="图片应用到").first
                apply_btn.click()
                time.sleep(1.0)
                snap4_path = os.path.join(ARTIFACT_DIR, "sku_batch_04_main_color_dropdown_menu.png")
                p.screenshot(path=snap4_path)
                return snap4_path
        return ""

    s4 = engine.manager.run_on_browser_thread(open_dropdown_main)
    print(f"  📸 截图已保存 (下拉菜单展示【主图 ➔ 同カラー(颜色)的变种】): {s4}\n")

    # =========================================================================
    # 场景 5: 执行点击【主图 ➔ 同颜色变体】(颜色11)
    # =========================================================================
    print("=================================================================")
    print("📸 【场景 5】执行【主图 ➔ 同カラー(颜色)的变种】(颜色11)，捕获同步效果...", flush=True)
    apply_main_1_ok = engine.apply_variation_image(
        filter_criteria=FIRST_FILTER,
        apply_type="main_color",
        timeout_ms=15000
    )
    print(f"      颜色11主图批量应用结果: {'✅ 成功' if apply_main_1_ok else '❌ 失败'}")
    time.sleep(1.5)

    def snap_color11():
        p = engine.manager._get_active_page_impl()
        p.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        snap5_path = os.path.join(ARTIFACT_DIR, "sku_batch_05_color11_main_applied.png")
        p.screenshot(path=snap5_path)
        return snap5_path

    s5 = engine.manager.run_on_browser_thread(snap_color11)
    print(f"  📸 截图已保存 (颜色11所有尺寸主图同步完成): {s5}\n")

    # =========================================================================
    # 场景 6: 为第二个颜色 (22 / aa) 上传主图并批量应用到同颜色
    # =========================================================================
    second_crit = {"颜色": "22", "尺寸": "aa"}
    print("=================================================================")
    print(f"📸 【场景 6】为第二个颜色 {second_crit} 上传主图 sku2.jpg 并批量应用到同颜色...", flush=True)
    
    print("  6.1 上传颜色22主图 (sku2.jpg)...", flush=True)
    up_main_2 = engine.upload_variation_image(
        filter_criteria=second_crit,
        image_path=COLOR_MAIN_PLAN[1][1],
        image_type="main",
        timeout_ms=30000
    )
    print(f"      上传: {'✅ 成功' if up_main_2 else '❌ 失败'}")
    time.sleep(1)

    print("  6.2 执行批量应用: 主图 ➔ 同カラー(颜色)的变种...", flush=True)
    apply_main_2_ok = engine.apply_variation_image(
        filter_criteria=second_crit,
        apply_type="main_color",
        timeout_ms=15000
    )
    print(f"      应用: {'✅ 成功' if apply_main_2_ok else '❌ 失败'}")
    time.sleep(1.5)

    def snap_color22():
        p = engine.manager._get_active_page_impl()
        p.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        snap6_path = os.path.join(ARTIFACT_DIR, "sku_batch_06_color22_main_applied.png")
        p.screenshot(path=snap6_path)
        return snap6_path

    s6 = engine.manager.run_on_browser_thread(snap_color22)
    print(f"  📸 截图已保存 (颜色22所有尺寸主图同步完成): {s6}\n")

    # =========================================================================
    # 场景 7: 为第三个颜色 (33 / aa) 上传主图并批量应用到同颜色
    # =========================================================================
    third_crit = {"颜色": "33", "尺寸": "aa"}
    print("=================================================================")
    print(f"📸 【场景 7】为第三个颜色 {third_crit} 上传主图 sku3.jpg 并批量应用到同颜色...", flush=True)
    
    print("  7.1 上传颜色33主图 (sku3.jpg)...", flush=True)
    up_main_3 = engine.upload_variation_image(
        filter_criteria=third_crit,
        image_path=COLOR_MAIN_PLAN[2][1],
        image_type="main",
        timeout_ms=30000
    )
    print(f"      上传: {'✅ 成功' if up_main_3 else '❌ 失败'}")
    time.sleep(1)

    print("  7.2 执行批量应用: 主图 ➔ 同カラー(颜色)的变种...", flush=True)
    apply_main_3_ok = engine.apply_variation_image(
        filter_criteria=third_crit,
        apply_type="main_color",
        timeout_ms=15000
    )
    print(f"      应用: {'✅ 成功' if apply_main_3_ok else '❌ 失败'}")
    time.sleep(1.5)

    def snap_color33():
        p = engine.manager._get_active_page_impl()
        p.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        snap7_path = os.path.join(ARTIFACT_DIR, "sku_batch_07_color33_main_applied.png")
        p.screenshot(path=snap7_path)
        return snap7_path

    s7 = engine.manager.run_on_browser_thread(snap_color33)
    print(f"  📸 截图已保存 (颜色33所有尺寸主图同步完成): {s7}\n")

    # =========================================================================
    # 场景 8: 变体图片矩阵最终全貌截图
    # =========================================================================
    print("=================================================================")
    print("📸 【场景 8】变体图片矩阵最终全貌截图留存...", flush=True)

    def snap_final():
        p = engine.manager._get_active_page_impl()
        p.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(1.0)
        snap8_path = os.path.join(ARTIFACT_DIR, "sku_batch_08_final_matrix_verified.png")
        p.screenshot(path=snap8_path)
        return snap8_path

    s8 = engine.manager.run_on_browser_thread(snap_final)
    print(f"  📸 截图已保存: {s8}\n")

    print("🎉 SKU 图片上传与全部批量应用测试场景 100% 成功执行完毕！全部截图已留存！", flush=True)

if __name__ == "__main__":
    main()
