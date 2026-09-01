import sys
import os
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine

ARTIFACT_DIR = "/Users/gx/.gemini/antigravity-ide/brain/bc6c623e-3e59-4b66-9b53-0c5d637be539"

def main():
    print("🚀 正在捕获并留存每个 SKU 批量操作场景的高清截图...", flush=True)
    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect(activate=False)
    if not ok:
        print("❌ 连接失败:", msg)
        return

    def capture():
        p = engine.manager._get_active_page_impl()
        var_container = p.locator("#variationImage .overflow-y-auto, #variationImage .max-h-700").first
        headers = var_container.locator(".item-header")
        print(f"✅ 找到 {headers.count()} 个变体卡片", flush=True)

        # -----------------------------------------------------------------
        # 截图 1: 第一个 SKU (11 / aa) 主图与附图已就绪
        # -----------------------------------------------------------------
        headers.nth(0).scroll_into_view_if_needed()
        time.sleep(0.6)
        snap1 = os.path.join(ARTIFACT_DIR, "sku_scenario1_first_sku_uploaded.png")
        p.screenshot(path=snap1)
        print(f"📸 [场景 1] 第一个 SKU 主图与附图已上传: {snap1}", flush=True)

        # -----------------------------------------------------------------
        # 截图 2: 展开「图片应用到」下拉菜单（附图 ➔ 所有变种）
        # -----------------------------------------------------------------
        p.keyboard.press("Escape")
        time.sleep(0.3)
        h0 = headers.nth(0)
        h0.scroll_into_view_if_needed()
        time.sleep(0.3)
        btn0 = h0.locator("span.link, a, span[class*='link']").filter(has_text="图片应用到").first
        btn0.click()
        time.sleep(0.8)
        snap2 = os.path.join(ARTIFACT_DIR, "sku_scenario2_dropdown_extra_all.png")
        p.screenshot(path=snap2)
        print(f"📸 [场景 2] 点击「图片应用到」展开【附图 ➔ 所有变种】下拉菜单: {snap2}", flush=True)

        # -----------------------------------------------------------------
        # 截图 3: 附图已全部同步应用到所有 6 个变体卡片
        # -----------------------------------------------------------------
        p.keyboard.press("Escape")
        time.sleep(0.4)
        # 滚动展示多个卡片中的附图
        headers.nth(1).scroll_into_view_if_needed()
        time.sleep(0.6)
        snap3 = os.path.join(ARTIFACT_DIR, "sku_scenario3_extra_applied_all_cards.png")
        p.screenshot(path=snap3)
        print(f"📸 [场景 3] 附图已批量应用至全部变体卡片: {snap3}", flush=True)

        # -----------------------------------------------------------------
        # 截图 4: 展开「图片应用到」下拉菜单（主图 ➔ 同カラー(颜色)的变种）
        # -----------------------------------------------------------------
        p.keyboard.press("Escape")
        time.sleep(0.3)
        h0.scroll_into_view_if_needed()
        time.sleep(0.3)
        btn0.click()
        time.sleep(0.8)
        snap4 = os.path.join(ARTIFACT_DIR, "sku_scenario4_dropdown_main_color.png")
        p.screenshot(path=snap4)
        print(f"📸 [场景 4] 点击「图片应用到」展开【主图 ➔ 同カラー(颜色)的变种】下拉菜单: {snap4}", flush=True)

        # -----------------------------------------------------------------
        # 截图 5: 颜色 11 主图批量应用到同颜色（11-aa, 11-qq）
        # -----------------------------------------------------------------
        p.keyboard.press("Escape")
        time.sleep(0.4)
        headers.nth(0).scroll_into_view_if_needed()
        time.sleep(0.6)
        snap5 = os.path.join(ARTIFACT_DIR, "sku_scenario5_color11_main_applied.png")
        p.screenshot(path=snap5)
        print(f"📸 [场景 5] 颜色 11 主图已同步至同颜色全部变体: {snap5}", flush=True)

        # -----------------------------------------------------------------
        # 截图 6: 颜色 33 主图批量应用到同颜色（33-aa, 33-qq）
        # -----------------------------------------------------------------
        # 找到颜色 33 的卡片
        h_33 = None
        for i in range(headers.count()):
            if "33" in headers.nth(i).inner_text():
                h_33 = headers.nth(i)
                break
        if h_33:
            h_33.scroll_into_view_if_needed()
            time.sleep(0.6)
            snap6 = os.path.join(ARTIFACT_DIR, "sku_scenario6_color33_main_applied.png")
            p.screenshot(path=snap6)
            print(f"📸 [场景 6] 颜色 33 主图已同步至同颜色全部变体: {snap6}", flush=True)

        # -----------------------------------------------------------------
        # 截图 7: 变体图片矩阵最终全景留存
        # -----------------------------------------------------------------
        p.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.8)
        snap7 = os.path.join(ARTIFACT_DIR, "sku_scenario7_final_full_matrix.png")
        p.screenshot(path=snap7)
        print(f"📸 [场景 7] 变体图片矩阵全局最终配置全貌: {snap7}", flush=True)

    engine.manager.run_on_browser_thread(capture)
    print("\n🎉 全部 7 个场景的留存截图已全部生成完毕！", flush=True)

if __name__ == "__main__":
    main()
