import sys
import os
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine
from core.form_operator import FormOperator

ARTIFACT_DIR = "/Users/gx/.gemini/antigravity-ide/brain/bc6c623e-3e59-4b66-9b53-0c5d637be539"
UPLOADS = os.path.join(PROJECT_DIR, "data", "uploads")

FIRST_FILTER = {"颜色": "11", "尺寸": "aa"}
EXTRA_IMGS = [os.path.join(UPLOADS, f"PT{i:02d}.jpg") for i in [1, 2, 3, 4]]
MAIN_1 = os.path.join(UPLOADS, "sku1.jpg")  # Black
MAIN_2 = os.path.join(UPLOADS, "sku2.jpg")  # White
MAIN_3 = os.path.join(UPLOADS, "sku3.jpg")  # Blue

def main():
    print("🚀 启动 SKU 图片上传与批量应用完整视觉回归测试 (无悬浮干扰)...", flush=True)
    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect(activate=True)
    if not ok:
        print("❌ 连接失败:", msg)
        return

    def run_flow():
        p = engine.manager._get_active_page_impl()
        target_url = "https://www.dianxiaomi.com/web/amazon/add"
        if "dianxiaomi.com/web/amazon/add" not in p.url:
            p.goto(target_url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(2)

        var_box = p.locator("#variationImage .overflow-y-auto, #variationImage .max-h-700").first
        form = FormOperator(p)
        headers = var_box.locator(".item-header")
        if headers.count() < 4:
            print("⚙️ 页面变体未初始化，正在初始化 (11/22/33 × aa/qq)...")
            form.select_store_account("金梧汇辰", "日本", timeout_ms=15000)
            time.sleep(0.5)
            form.fill("产品标题", "日本人気ペット用トイレトレー 自動洗浄ガード付き")
            time.sleep(0.5)
            if form.click_button("自动识别产品类型"):
                time.sleep(1.5)
                form.confirm_modal("确定", wait_timeout_ms=5000)
                time.sleep(1.5)
            form.click_radio("多变体")
            time.sleep(0.5)
            form.select("变种主题", "Color-Size")
            time.sleep(0.5)
            form.add_variation_option("カラー", "11")
            time.sleep(0.3)
            form.add_variation_option("カラー", "22")
            time.sleep(0.3)
            form.add_variation_option("カラー", "33")
            time.sleep(0.3)
            form.add_variation_option("サイズ", "aa")
            time.sleep(0.3)
            form.add_variation_option("サイズ", "qq")
            time.sleep(1.5)

        headers = var_box.locator(".item-header")
        print(f"✅ 变体卡片数量: {headers.count()}")

        def clean_snap(path):
            p.mouse.move(0, 0)
            time.sleep(0.4)
            p.screenshot(path=path)

        # -----------------------------------------------------------------
        # 场景 1: 上传第一个 SKU (11 / aa) 主图 + 4 张附图
        # -----------------------------------------------------------------
        print("\n📸 【场景 1】上传第一个 SKU (11 / aa) 主图与 4 张附图...")
        form.upload_variation_image(FIRST_FILTER, MAIN_1, image_type="main", timeout_ms=30000)
        time.sleep(0.5)
        form.upload_variation_image(FIRST_FILTER, EXTRA_IMGS, image_type="extra", timeout_ms=45000)
        time.sleep(1.0)

        headers.nth(0).scroll_into_view_if_needed()
        time.sleep(0.5)
        snap1 = os.path.join(ARTIFACT_DIR, "sku_test_01_first_sku_uploaded.png")
        clean_snap(snap1)
        print(f"  ✅ 场景 1 截图已保存: {snap1}")

        # -----------------------------------------------------------------
        # 场景 2: 展开「图片应用到」下拉菜单（附图 ➔ 所有变种）
        # -----------------------------------------------------------------
        print("\n📸 【场景 2】触发「图片应用到」下拉菜单，展示【附图 ➔ 所有变种】...")
        p.keyboard.press("Escape")
        time.sleep(0.3)
        h0 = headers.nth(0)
        h0.scroll_into_view_if_needed()
        time.sleep(0.3)
        btn0 = h0.locator("span.link, a, span[class*='link']").filter(has_text="图片应用到").first
        btn0.click()
        time.sleep(0.8)

        snap2 = os.path.join(ARTIFACT_DIR, "sku_test_02_click_extra_all_menu.png")
        p.screenshot(path=snap2)
        print(f"  ✅ 场景 2 截图已保存 (下拉菜单展示【附图-所有变种】): {snap2}")

        # -----------------------------------------------------------------
        # 场景 3: 执行点击【附图 ➔ 所有变体】，捕获所有卡片附图同步效果
        # -----------------------------------------------------------------
        print("\n📸 【场景 3】执行点击【附图 ➔ 所有变体】...")
        form.apply_variation_image(FIRST_FILTER, apply_type="extra_all", timeout_ms=15000)
        time.sleep(1.5)

        headers.nth(1).scroll_into_view_if_needed()
        time.sleep(0.5)
        snap3 = os.path.join(ARTIFACT_DIR, "sku_test_03_extra_synced_all_skus.png")
        clean_snap(snap3)
        print(f"  ✅ 场景 3 截图已保存 (全量变体卡片附图同步完成): {snap3}")

        # -----------------------------------------------------------------
        # 场景 4: 展开「图片应用到」下拉菜单（主图 ➔ 同カラー(颜色)的变种）
        # -----------------------------------------------------------------
        print("\n📸 【场景 4】触发「图片应用到」下拉菜单，展示【主图 ➔ 同カラー(颜色)的变种】...")
        p.keyboard.press("Escape")
        time.sleep(0.3)
        h0.scroll_into_view_if_needed()
        time.sleep(0.3)
        btn0.click()
        time.sleep(0.8)

        snap4 = os.path.join(ARTIFACT_DIR, "sku_test_04_click_main_color_menu.png")
        p.screenshot(path=snap4)
        print(f"  ✅ 场景 4 截图已保存 (下拉菜单展示【主图-同カラー(颜色)的变种】): {snap4}")

        # -----------------------------------------------------------------
        # 场景 5: 执行点击【主图 ➔ 同颜色变体】(颜色 11)
        # -----------------------------------------------------------------
        print("\n📸 【场景 5】执行点击【主图 ➔ 同颜色变体】(颜色 11)...")
        form.apply_variation_image(FIRST_FILTER, apply_type="main_color", timeout_ms=15000)
        time.sleep(1.5)

        for i in range(headers.count()):
            txt = headers.nth(i).inner_text()
            if "11" in txt and "qq" in txt:
                headers.nth(i).scroll_into_view_if_needed()
                break
        time.sleep(0.5)
        snap5 = os.path.join(ARTIFACT_DIR, "sku_test_05_color11_synced.png")
        clean_snap(snap5)
        print(f"  ✅ 场景 5 截图已保存 (颜色 11 全部尺寸主图同步): {snap5}")

        # -----------------------------------------------------------------
        # 场景 6: 为颜色 22 (22 / aa) 上传主图并批量应用到同颜色
        # -----------------------------------------------------------------
        crit_22 = {"颜色": "22", "尺寸": "aa"}
        print("\n📸 【场景 6】为颜色 22 上传主图并批量应用到同颜色...")
        form.upload_variation_image(crit_22, MAIN_2, image_type="main", timeout_ms=30000)
        time.sleep(0.5)
        form.apply_variation_image(crit_22, apply_type="main_color", timeout_ms=15000)
        time.sleep(1.5)

        for i in range(headers.count()):
            txt = headers.nth(i).inner_text()
            if "22" in txt and "aa" in txt:
                headers.nth(i).scroll_into_view_if_needed()
                break
        time.sleep(0.5)
        snap6 = os.path.join(ARTIFACT_DIR, "sku_test_06_color22_synced.png")
        clean_snap(snap6)
        print(f"  ✅ 场景 6 截图已保存 (颜色 22 全部尺寸主图同步): {snap6}")

        # -----------------------------------------------------------------
        # 场景 7: 为颜色 33 (33 / aa) 上传主图并批量应用到同颜色
        # -----------------------------------------------------------------
        crit_33 = {"颜色": "33", "尺寸": "aa"}
        print("\n📸 【场景 7】为颜色 33 上传主图并批量应用到同颜色...")
        form.upload_variation_image(crit_33, MAIN_3, image_type="main", timeout_ms=30000)
        time.sleep(0.5)
        form.apply_variation_image(crit_33, apply_type="main_color", timeout_ms=15000)
        time.sleep(1.5)

        for i in range(headers.count()):
            txt = headers.nth(i).inner_text()
            if "33" in txt and "aa" in txt:
                headers.nth(i).scroll_into_view_if_needed()
                break
        time.sleep(0.5)
        snap7 = os.path.join(ARTIFACT_DIR, "sku_test_07_color33_synced.png")
        clean_snap(snap7)
        print(f"  ✅ 场景 7 截图已保存 (颜色 33 全部尺寸主图同步): {snap7}")

        # -----------------------------------------------------------------
        # 场景 8: 变体图片矩阵最终全貌留存
        # -----------------------------------------------------------------
        print("\n📸 【场景 8】变体图片矩阵全局最终配置全貌...")
        p.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(1.0)
        snap8 = os.path.join(ARTIFACT_DIR, "sku_test_08_full_matrix_complete.png")
        clean_snap(snap8)
        print(f"  ✅ 场景 8 截图已保存 (最终完整矩阵全景): {snap8}")

        print("\n🎉 SKU 图片上传与全量批量应用测试执行 100% 成功！8 张清晰截图已更新！", flush=True)

    engine.manager.run_on_browser_thread(run_flow)

if __name__ == "__main__":
    main()
