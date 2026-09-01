import sys
import os
import json

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine

def inspect():
    engine = BrowserEngine(port=9222)
    engine.connect(activate=False)
    
    def run():
        page = engine.manager._get_active_page_impl()
        res = page.evaluate("""() => {
            return {
                url: window.location.href,
                title: document.title,
                storeSelected: document.querySelector('.ant-form-item .ant-select-selection-item')?.innerText || 'None',
                titleVal: document.querySelector('input[placeholder*="产品标题"], input[placeholder*="请输入标题"]')?.value || 'None',
                hasModals: document.querySelectorAll('.ant-modal:not([style*="display: none"])').length,
                modalText: Array.from(document.querySelectorAll('.ant-modal')).map(m => m.innerText).join(' | '),
                hasVariationSection: Boolean(document.querySelector('#variationImage')),
                headersCount: document.querySelectorAll('#variationImage .item-header').length
            };
        }""")
        print("Page state:", json.dumps(res, ensure_ascii=False, indent=2))
        
    engine.manager.run_on_browser_thread(run)

if __name__ == "__main__":
    inspect()
