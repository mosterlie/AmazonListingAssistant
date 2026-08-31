import json
import sys
import os

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
    engine.connect(activate=False)
    page = engine.manager._get_active_page_impl()
    
    js = r"""() => {
        const formItems = Array.from(document.querySelectorAll('.ant-form-item, div'));
        const storeItem = formItems.find(fi => {
            const lbl = fi.querySelector('.ant-form-item-label, label');
            return lbl && (lbl.innerText || '').includes('店铺账号');
        });
        const siteItem = formItems.find(fi => {
            const lbl = fi.querySelector('.ant-form-item-label, label');
            return lbl && (lbl.innerText || '').includes('站点选择');
        });
        
        const storeVal = storeItem?.querySelector('.ant-select-selection-item')?.innerText?.trim() || '';
        const siteVal = siteItem?.innerText?.trim() || '';
        
        const titleInp = document.querySelector('input[placeholder*="产品标题"], input[placeholder*="请输入标题"], #form_item_title');
        const parentSkuInp = document.querySelector('input[placeholder*="Parent SKU"], #form_item_parentSku');
        
        const modal = document.querySelector('.ant-modal-content, .ant-modal');
        const modalText = modal ? modal.innerText.slice(0, 200) : 'NO_MODAL';
        
        return {
            url: window.location.href,
            store: storeVal,
            site: siteVal,
            title: titleInp ? titleInp.value : '',
            parentSku: parentSkuInp ? parentSkuInp.value : '',
            modalText: modalText
        };
    }"""
    
    res = engine.manager.run_on_browser_thread(lambda: page.evaluate(js))
    print(json.dumps(res, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
