import json
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
    print("connect:", ok, msg)

    def probe():
        page = engine.manager._get_active_page_impl()
        print("active page:", page.title, "|", page.url)
        # 检查登录态：页面中是否存在用户名/退出登录等元素
        login_state = page.evaluate("""() => {
            const txt = document.body.innerText.slice(0, 3000);
            const hasLogin = !!document.querySelector('input[placeholder*="用户名"], input[placeholder*="密码"]');
            const hasLogout = txt.includes('退出') || txt.includes('注销');
            const hasUser = txt.includes('admin') || txt.includes('您好');
            return {hasLoginForm: hasLogin, hasLogout, hasUser, title: document.title, url: location.href};
        }""")
        print("login state:", json.dumps(login_state, ensure_ascii=False))

        # 导航到 add 页
        page.goto("https://www.dianxiaomi.com/web/amazon/add", wait_until="domcontentloaded", timeout=20000)
        time.sleep(6)
        print("after goto:", page.title, "|", page.url)
        state = page.evaluate("""() => {
            const txt = document.body.innerText.slice(0, 2000);
            const storeSel = document.querySelector('.ant-select-selection-item');
            const hasLoginForm = !!document.querySelector('input[placeholder*="用户名"], input[placeholder*="密码"]');
            return {
                url: location.href, title: document.title, hasLoginForm,
                storeFirst: storeSel ? storeSel.innerText : '',
                bodyHead: txt.slice(0, 300)
            };
        }""")
        print("add page state:", json.dumps(state, ensure_ascii=False))

    engine.manager.run_on_browser_thread(probe)

if __name__ == "__main__":
    main()
