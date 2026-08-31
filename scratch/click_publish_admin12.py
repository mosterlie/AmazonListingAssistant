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

def main():
    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect(activate=True)
    print(f"Browser connected: {ok} ({msg})")

    def run_action():
        manager = engine.manager
        page = None
        contexts = manager.browser.contexts if manager.browser else ([manager.context] if manager.context else [])
        for ctx in contexts:
            for p in ctx.pages:
                if "127.0.0.1:8000/list" in p.url or ":8000/list" in p.url:
                    page = p
                    break
            if page:
                break

        if not page:
            print("Opening http://127.0.0.1:8000/list ...")
            ctx = contexts[0] if contexts else manager.browser.new_context()
            page = ctx.new_page()
            page.goto("http://127.0.0.1:8000/list")
        
        page.bring_to_front()
        page.on("dialog", lambda dialog: (print(f"🔔 捕获弹窗 [{dialog.type}]: {dialog.message}"), dialog.accept()))

        time.sleep(1.0)
        print(f"当前页面标题: {page.title()}, URL: {page.url}")

        # 检查是否在登录页面
        if "login" in page.url:
            print("检测到未登录，正在自动登录 admin / admin ...")
            page.fill("input[name='username'], #username, input[type='text']", "admin")
            page.fill("input[name='password'], #password, input[type='password']", "admin")
            page.click("button[type='submit'], .btn-primary")
            page.wait_for_url("**/list", timeout=5000)
            print("登录完成并进入列表页！")

        rows = page.locator("#productListTableBody tr, table tbody tr")
        total_rows = rows.count()
        print(f"列表总商品行数: {total_rows}")

        clicked = False
        for i in range(total_rows):
            r = rows.nth(i)
            text = r.inner_text()
            if "admin12" in text:
                print(f"🎯 找到 admin12 所在数据行 (第 {i+1} 行): {text.splitlines()[:3]}")
                btn = r.locator("button:has-text('上件')")
                if btn.count() > 0:
                    print("🚀 正在点击【上件】按钮...")
                    btn.click()
                    clicked = True
                    break
        
        if not clicked:
            print("未在表格中直接匹配到 admin12 按钮，调用页面 triggerPublish(56)...")
            page.evaluate("() => { if (typeof triggerPublish === 'function') triggerPublish(56); }")

        print("✅ 点击上件操作已触发！等待进度弹窗与上件执行...")
        time.sleep(3.0)

    engine.manager.run_on_browser_thread(run_action)

if __name__ == "__main__":
    main()
