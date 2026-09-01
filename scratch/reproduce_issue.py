import os
import sys
import time
from playwright.sync_api import sync_playwright

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from server.services.auth_service import AuthService

def reproduce():
    session_token = AuthService.create_session(1)
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

        page.on("console", lambda msg: print(f"[Browser Console {msg.type}]: {msg.text}"))
        page.on("pageerror", lambda err: print(f"[Browser PageError]: {err}"))

        print("Navigating to /list...")
        page.goto("http://127.0.0.1:8000/list")
        time.sleep(1)

        # Let's find the publish buttons
        buttons = page.locator("button:has-text('上件')").all()
        print(f"Found {len(buttons)} publish buttons")

        page.on("dialog", lambda dialog: (print(f"[Dialog]: {dialog.message}"), dialog.accept()))

        if buttons:
            print("Clicking first publish button...")
            buttons[0].click()
            
            for i in range(20):
                time.sleep(0.5)
                modal = page.locator("#publishProgressModal")
                detail_modal = page.locator("#productDetailModal")
                vis = modal.is_visible()
                disp = modal.evaluate("el => el.style.display")
                logs = page.locator("#publishConsoleLogs").inner_text()
                hint = page.locator("#publishStatusHint").inner_text()
                print(f"T+{(i+1)*0.5}s: modal is_visible={vis}, display={disp}, detail_modal={detail_modal.is_visible()}, hint={hint[:30]}")
                if not vis:
                    print("⚠️ Modal became invisible!")
                    print(f"Modal outerHTML: {modal.evaluate('el => el.outerHTML')[:200]}")
        
        browser.close()

if __name__ == "__main__":
    reproduce()
