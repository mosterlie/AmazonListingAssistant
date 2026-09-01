import os
import sys
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine

def debug_modal():
    e = BrowserEngine(port=9222)
    e.connect()
    e.open_or_focus_url("http://127.0.0.1:8000/list")
    time.sleep(1.0)
    
    def run():
        p = e.manager._get_active_page_impl()
        p.reload()
        p.wait_for_timeout(1000)
        
        # Check console logs
        msgs = []
        p.on("console", lambda m: msgs.append(f"[{m.type}] {m.text}"))
        p.on("pageerror", lambda err: msgs.append(f"[ERROR] {str(err)}"))
        
        p.evaluate("() => { if (window.viewProductDetail) window.viewProductDetail(56); }")
        p.wait_for_timeout(1500)
        
        body_html = p.evaluate("() => document.getElementById('modalContentBody')?.innerHTML")
        print("Modal body HTML:\n", body_html[:500], flush=True)
        print("\nConsole messages:\n", msgs, flush=True)
        
    e.manager.run_on_browser_thread(run)

if __name__ == "__main__":
    debug_modal()
