import os
import sys
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine

def dump_menu():
    e = BrowserEngine(port=9222)
    e.connect()
    
    def run_dump():
        page = e.manager._get_active_page_impl()
        html = page.evaluate("""() => {
            const menu = document.querySelector('.product-image-apply-menu') || document.querySelector('.ant-dropdown .product-image-apply-menu');
            if (!menu) return 'not found';
            return menu.parentElement.innerHTML;
        }""")
        print("Menu HTML:\n", html)
    
    e.manager.run_on_browser_thread(run_dump)

if __name__ == "__main__":
    dump_menu()
