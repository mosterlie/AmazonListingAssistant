import sys
import os
import json

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine

def inspect_store():
    engine = BrowserEngine(port=9222)
    engine.connect(activate=False)
    
    def run():
        p = engine.manager._get_active_page_impl()
        res = p.evaluate("""() => {
            const formItems = Array.from(document.querySelectorAll('.ant-form-item, .form-item, div'));
            const storeItem = formItems.find(fi => (fi.innerText || '').includes('店铺账号'));
            const selects = Array.from(document.querySelectorAll('.ant-select')).map(s => ({
                id: s.id,
                className: s.className,
                text: s.innerText,
                parentText: s.parentElement?.innerText?.slice(0, 40)
            }));
            return {
                url: window.location.href,
                storeItemText: storeItem ? storeItem.innerText.slice(0, 100) : 'None',
                allSelects: selects.slice(0, 6)
            };
        }""")
        print(json.dumps(res, ensure_ascii=False, indent=2))
        
    engine.manager.run_on_browser_thread(run)

if __name__ == "__main__":
    inspect_store()
