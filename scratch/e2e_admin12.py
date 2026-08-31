#!/usr/bin/env python3
"""
端到端测试：在 /list 页面点击 admin12 的【上件】按钮，
实时跟踪进度弹窗日志，直到上件完成，全程输出到控制台。
"""
import sys
import os
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine

MAX_WAIT_S = 8 * 60  # 最长等待 8 分钟

def main():
    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect(activate=True)
    print(f"[E2E] Browser connected: {ok} ({msg})")

    def run():
        manager = engine.manager
        contexts = manager.browser.contexts if manager.browser else ([manager.context] if manager.context else [])

        # 1. 查找或打开 /list 页面
        page = None
        for ctx in contexts:
            for p in ctx.pages:
                if ":8000/list" in p.url:
                    page = p
                    break
            if page:
                break
        if not page:
            print("[E2E] Opening http://127.0.0.1:8000/list ...")
            ctx = contexts[0] if contexts else manager.browser.new_context()
            page = ctx.new_page()
            page.goto("http://127.0.0.1:8000/list", wait_until="domcontentloaded", timeout=15000)
        page.bring_to_front()
        page.reload(wait_until="domcontentloaded", timeout=15000)
        time.sleep(2)

        # 处理 confirm 弹窗（自动接受）
        page.on("dialog", lambda dialog: (print(f"[E2E] 🔔 confirm 弹窗已自动接受: {dialog.message[:60]}"), dialog.accept()))

        print(f"[E2E] 页面就绪: {page.title()} | {page.url}")

        # 2. 若被重定向到登录页则登录
        if "login" in page.url:
            print("[E2E] 检测到未登录，正在自动登录 admin/admin ...")
            page.fill("input[name='username'], #username, input[type='text']", "admin")
            page.fill("input[name='password'], #password, input[type='password']", "admin")
            page.click("button[type='submit'], .btn-primary")
            page.wait_for_url("**/list", timeout=8000)
            print("[E2E] 登录完成！")
            time.sleep(2)

        # 3. 点击 admin12 行的上件按钮
        rows = page.locator("#productListTableBody tr")
        print(f"[E2E] 列表商品行数: {rows.count()}")
        clicked = False
        for i in range(rows.count()):
            r = rows.nth(i)
            if "admin12" in r.inner_text():
                info = r.inner_text().splitlines()
                print(f"[E2E] 🎯 找到 admin12 行 (#{info[0] if info else i+1}): {info[:4]}")
                btn = r.locator("button:has-text('上件')")
                if btn.count() > 0:
                    print("[E2E] 🚀 正在点击【🚀 上件】按钮（等价于用户真实点击）...")
                    btn.click()
                    clicked = True
                    break
        if not clicked:
            print("[E2E] 表格未匹配到，直接调用页面 triggerPublish(56) ...")
            page.evaluate("() => { if (typeof triggerPublish === 'function') triggerPublish(56); }")

        # 4. 实时跟踪进度弹窗
        time.sleep(2)
        seen_lines = 0
        start = time.time()
        while time.time() - start < MAX_WAIT_S:
            try:
                state = page.evaluate("""() => {
                    const logs = Array.from(document.querySelectorAll('#publishConsoleLogs > div')).map(d => d.textContent || '');
                    const hint = document.querySelector('#publishStatusHint');
                    const modalVisible = (() => { const m = document.getElementById('publishProgressModal'); return m && m.style.display !== 'none'; })();
                    return {logs, hint: hint ? hint.innerText.trim() : '', modalVisible};
                }""")
            except Exception as e:
                print(f"[E2E] 读取状态异常(忽略): {e}")
                time.sleep(3)
                continue

            logs = state.get("logs", [])
            for line in logs[seen_lines:]:
                print(f"    {line}")
            seen_lines = len(logs)

            hint = state.get("hint", "")
            if ("上件完成" in hint) or ("🎉" in hint and "完成" in hint):
                print(f"\n[E2E] ✅✅✅ 端到端测试成功！最终状态: {hint}")
                return
            if "❌" in hint and ("失败" in hint or "异常" in hint):
                print(f"\n[E2E] ❌ 端到端测试失败！最终状态: {hint}")
                return
            if "超时" in hint:
                print(f"\n[E2E] ⏱️ 轮询超时: {hint}")
                return
            time.sleep(3)

        print("\n[E2E] ⏱️ 超出最大等待时间，任务可能仍在后台执行。")

    engine.manager.run_on_browser_thread(run)

if __name__ == "__main__":
    main()
