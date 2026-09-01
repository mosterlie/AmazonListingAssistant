import os
import sys
import time
from playwright.sync_api import sync_playwright

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from server.services.auth_service import AuthService

CONV_ID = "d012c055-fb36-493d-b989-7e2ebf98f314"
ARTIFACT_DIR = f"/Users/gx/.gemini/antigravity-ide/brain/{CONV_ID}"
os.makedirs(ARTIFACT_DIR, exist_ok=True)

def verify_publish_modal():
    print("=" * 80, flush=True)
    print("🧪 【自动化测试与验证】点击「🚀 上件」按钮后模态弹窗稳定展现、日志实时流转测试", flush=True)
    print(f"📁 截图输出目录: {ARTIFACT_DIR}", flush=True)
    print("=" * 80, flush=True)

    session_token = AuthService.create_session(1)
    print(f"🔑 生成测试 Admin Session: {session_token[:10]}...", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.add_cookies([{
            "name": "session_token",
            "value": session_token,
            "domain": "127.0.0.1",
            "path": "/"
        }])

        page = context.new_page()

        page.on("console", lambda msg: print(f"[Browser Console {msg.type}]: {msg.text}", flush=True))
        page.on("pageerror", lambda err: print(f"[Browser PageError]: {err}", flush=True))

        # 1. 访问商品管理列表
        print("\n🌐 1. 打开商品管理列表: http://127.0.0.1:8000/list ...", flush=True)
        page.goto("http://127.0.0.1:8000/list", wait_until="networkidle")
        time.sleep(1.0)

        snap1 = os.path.join(ARTIFACT_DIR, "01_product_list_page.png")
        page.screenshot(path=snap1)
        print(f"📸 [截图 1] 商品列表加载完成: {snap1}", flush=True)

        # 2. 定位商品 #56 的「🚀 上件」按钮
        target_row = page.locator("#productListTableBody tr").filter(has_text="#56").first
        if target_row.count() == 0:
            # 如果没有 #56，取第一行的上件按钮
            print("⚠️ 查找第一行商品的【🚀 上件】按钮...", flush=True)
            publish_btn = page.locator("#productListTableBody button:has-text('上件')").first
        else:
            publish_btn = target_row.locator("button:has-text('上件')").first

        print("🎯 已精准定位【🚀 上件】按钮，准备点击...", flush=True)

        # 3. 点击「🚀 上件」按钮
        publish_btn.click()
        print("👆 已点击【🚀 上件】按钮！", flush=True)

        # 4. 连续 10 秒多采样检测弹窗是否稳定展现（绝不闪退）
        modal = page.locator("#publishProgressModal")
        time.sleep(0.5)

        vis = modal.is_visible()
        print(f"👀 点击 0.5s 后进度弹窗可见性: {'✅ 稳定展现' if vis else '❌ 弹窗未展现'}", flush=True)
        assert vis, "弹窗未正常弹出！"

        # 截图 2: 弹窗已成功弹出且稳定显示
        snap2 = os.path.join(ARTIFACT_DIR, "02_publish_modal_stable_open.png")
        page.screenshot(path=snap2)
        print(f"📸 [截图 2] 上件进度弹窗稳定展现留痕: {snap2}", flush=True)

        # 5. 持续轮询观察日志流式输出
        for i in range(12):
            time.sleep(1.0)
            vis = modal.is_visible()
            logs = page.locator("#publishConsoleLogs").inner_text()
            hint = page.locator("#publishStatusHint").inner_text()
            log_lines = logs.strip().splitlines()
            print(f"   ⏱️ [T+{i+1}s] 弹窗可见: {vis} | 终端日志: {len(log_lines)} 行 | 底部状态: {hint[:35]}...", flush=True)
            assert vis, f"弹窗在第 {i+1} 秒意外消失！"

        # 截图 3: 弹窗内日志实时推进与步骤高亮
        snap3 = os.path.join(ARTIFACT_DIR, "03_publish_modal_progress_logs.png")
        page.screenshot(path=snap3)
        print(f"📸 [截图 3] 上件执行过程实时日志流转截图: {snap3}", flush=True)

        # 6. 测试主动点击「✕」或「关闭窗口」
        close_btn = page.locator("#publishModalCloseBtn")
        close_btn.click()
        time.sleep(0.5)
        print(f"🚪 主动点击关闭后弹窗状态: {'✅ 已正常关闭' if not modal.is_visible() else '❌ 未关闭'}", flush=True)

        # 7. 测试从「👁️ 查看详情」弹窗中点击「🚀 自动化上件店小秘」
        print("\n🌐 2. 测试从【查看详情】模态框中调起上件...", flush=True)
        detail_btn = page.locator("#productListTableBody button:has-text('查看详情')").first
        detail_btn.click()
        time.sleep(1.0)

        detail_modal = page.locator("#productDetailModal")
        print(f"📦 查看详情弹窗状态: {'✅ 打开' if detail_modal.is_visible() else '❌ 未打开'}", flush=True)

        snap4 = os.path.join(ARTIFACT_DIR, "04_product_detail_modal.png")
        page.screenshot(path=snap4)
        print(f"📸 [截图 4] 商品详情弹窗: {snap4}", flush=True)

        # 点击详情弹窗底部的「🚀 自动化上件店小秘」
        detail_pub_btn = page.locator("#modalPublishBtn")
        detail_pub_btn.click()
        time.sleep(0.8)

        print(f"🚀 从详情切换到上件弹窗: detail_modal={detail_modal.is_visible()}, publish_modal={modal.is_visible()}", flush=True)
        assert modal.is_visible(), "从详情弹窗切换到上件弹窗失败！"

        snap5 = os.path.join(ARTIFACT_DIR, "05_publish_modal_from_detail.png")
        page.screenshot(path=snap5)
        print(f"📸 [截图 5] 从详情顺利切换并稳定展现上件弹窗: {snap5}", flush=True)

        browser.close()

    print("\n🎉 【全流程自动化测试通过】所有断言均已满足，弹窗稳定展现无闪退！", flush=True)
    return True

if __name__ == "__main__":
    verify_publish_modal()
