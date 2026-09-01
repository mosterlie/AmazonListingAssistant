import sys
import os
import time
from playwright.sync_api import sync_playwright

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from server.services.auth_service import AuthService

CONV_ID = "4d70ba54-c5b0-4648-8adb-474ba62b907e"
ARTIFACT_DIR = f"/Users/gx/.gemini/antigravity-ide/brain/{CONV_ID}"
os.makedirs(ARTIFACT_DIR, exist_ok=True)

def test_web_publish_modal():
    print("=" * 80, flush=True)
    print("🧪 【前端交互全流程验证】测试点击「上件」后进度弹窗持续展示与日志流式传输", flush=True)
    print(f"📁 截图输出目录: {ARTIFACT_DIR}", flush=True)
    print("=" * 80, flush=True)

    session_token = AuthService.create_session(1)
    print(f"🔑 生成测试 Admin Session: {session_token[:10]}...", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        
        # 设置认证 Cookie
        context.add_cookies([{
            "name": "session_token",
            "value": session_token,
            "domain": "127.0.0.1",
            "path": "/"
        }])

        page = context.new_page()

        # 1. 访问商品管理列表
        print("\n🌐 正在打开商品管理列表: http://127.0.0.1:8000/list ...", flush=True)
        page.goto("http://127.0.0.1:8000/list", wait_until="networkidle")
        time.sleep(1.0)

        # 截图 1: 商品管理列表全貌
        snap1 = os.path.join(ARTIFACT_DIR, "test_ui_01_product_list.png")
        page.screenshot(path=snap1)
        print(f"📸 [截图 1] 商品列表加载完成: {snap1}", flush=True)

        # 2. 定位商品 #56 的「🚀 上件」按钮
        target_row = page.locator("#productListTableBody tr").filter(has_text="#56").first
        if target_row.count() == 0:
            print("❌ 未在表格中找到商品 #56 行！", flush=True)
            browser.close()
            return False

        publish_btn = target_row.locator("button").filter(has_text="上件").first
        print("🎯 已定位商品 #56 的【🚀 上件】按钮", flush=True)

        # 3. 处理 window.confirm 对话框并点击上件
        page.on("dialog", lambda dialog: dialog.accept())
        publish_btn.click()
        print("👆 已点击【🚀 上件】按钮并自动确认确认框", flush=True)
        time.sleep(1.5)

        # 4. 验证弹窗是否稳定开启
        modal = page.locator("#publishProgressModal")
        is_visible = modal.is_visible()
        print(f"👀 进度弹窗可见性状态: {'✅ 稳定可见' if is_visible else '❌ 异常不可见/已关闭'}", flush=True)

        # 截图 2: 上件进度弹窗稳定展现与初始日志
        snap2 = os.path.join(ARTIFACT_DIR, "test_ui_02_modal_opened_steady.png")
        page.screenshot(path=snap2)
        print(f"📸 [截图 2] 上件进度弹窗稳定展开留痕: {snap2}", flush=True)

        # 5. 持续观察与轮询日志 (最长 90 秒)
        print("\n⏳ 正在观察弹窗实时流式日志与步骤推进...", flush=True)
        start_time = time.time()
        max_duration = 90
        step_snaps = {}

        while time.time() - start_time < max_duration:
            time.sleep(2.5)
            elapsed = int(time.time() - start_time)
            logs_text = page.locator("#publishConsoleLogs").inner_text()
            hint_text = page.locator("#publishStatusHint").inner_text()
            log_lines = logs_text.strip().splitlines()
            print(f"   ⏱️ [T+{elapsed}s] 终端日志行数: {len(log_lines)} 行 | 底部提示: {hint_text[:40]}...", flush=True)

            # 抓取不同阶段高光截图
            if "[阶段 2/7]" in logs_text and 2 not in step_snaps:
                snap_s2 = os.path.join(ARTIFACT_DIR, "test_ui_03_modal_step2_category.png")
                page.screenshot(path=snap_s2)
                step_snaps[2] = snap_s2
                print(f"📸 [阶段 2 截图] 类目识别步骤流转: {snap_s2}", flush=True)

            if "[阶段 4/7]" in logs_text and 4 not in step_snaps:
                snap_s4 = os.path.join(ARTIFACT_DIR, "test_ui_04_modal_step4_matrix.png")
                page.screenshot(path=snap_s4)
                step_snaps[4] = snap_s4
                print(f"📸 [阶段 4 截图] 变体矩阵生成步骤流转: {snap_s4}", flush=True)

            if "[阶段 5/7]" in logs_text and 5 not in step_snaps:
                snap_s5 = os.path.join(ARTIFACT_DIR, "test_ui_05_modal_step5_images.png")
                page.screenshot(path=snap_s5)
                step_snaps[5] = snap_s5
                print(f"📸 [阶段 5 截图] 变体图片装配步骤流转: {snap_s5}", flush=True)

            if "🎉" in hint_text or "❌" in hint_text or "完成" in hint_text:
                print("🏁 观测到任务完成状态！", flush=True)
                break

        # 截图 6: 任务执行最终状态
        snap6 = os.path.join(ARTIFACT_DIR, "test_ui_06_modal_final_success.png")
        page.screenshot(path=snap6)
        print(f"📸 [截图 6] 上件弹窗最终执行状态留痕: {snap6}", flush=True)

        # 6. 测试主动点击关闭弹窗
        close_btn = page.locator("#publishModalCloseBtn")
        if close_btn.is_visible():
            close_btn.click()
            time.sleep(0.5)
            is_closed = not modal.is_visible()
            print(f"🚪 点击关闭按钮后弹窗状态: {'✅ 已正常关闭' if is_closed else '❌ 未正常关闭'}", flush=True)

        snap7 = os.path.join(ARTIFACT_DIR, "test_ui_07_modal_closed.png")
        page.screenshot(path=snap7)
        print(f"📸 [截图 7] 弹窗关闭后列表页留痕: {snap7}", flush=True)

        browser.close()

    # 7. 从正在运行的 CDP 浏览器中截取店小秘页面的实际渲染结果
    print("\n🌐 正在从 CDP 浏览器中截取店小秘前台页面实际效果...", flush=True)
    try:
        from browser_engine import BrowserEngine
        cdp_engine = BrowserEngine(port=9222)
        if cdp_engine.connect(activate=False)[0]:
            snap_dxm = os.path.join(ARTIFACT_DIR, "test_ui_08_dxm_actual_page.png")
            cdp_engine.screenshot(save_path=snap_dxm)
            print(f"📸 [截图 8] 店小秘前台页面实际渲染留痕: {snap_dxm}", flush=True)
    except Exception as e:
        print(f"⚠️ 截取店小秘页面提示: {e}", flush=True)

    print("\n✅ 【前端交互全流程验证】测试完毕！", flush=True)
    return True

if __name__ == "__main__":
    test_web_publish_modal()
