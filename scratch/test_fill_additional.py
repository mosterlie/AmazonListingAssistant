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
        const results = {};
        const proto = window.HTMLInputElement.prototype;
        const textProto = window.HTMLTextAreaElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
        const textSetter = Object.getOwnPropertyDescriptor(textProto, 'value')?.set;
        
        function setVal(input, val) {
            if (!input || val === undefined || val === null) return false;
            input.focus();
            if (input.tagName === 'TEXTAREA' && textSetter) textSetter.call(input, String(val));
            else if (setter) setter.call(input, String(val));
            else input.value = String(val);
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
            input.blur();
            return true;
        }
        
        // 1. 制造商填写品牌名称
        const mfgInp = document.querySelector('div[data-path="manufacturer.0.value"] input') || document.querySelector('input[placeholder="请输入制造商"]');
        results['manufacturer'] = setVal(mfgInp, 'Hiremo');
        
        // 2. 品目寸法（L x W x H）(商品尺寸 长 x 宽 x 高)
        const itemL = document.getElementById('form_item_item_length_width_height.0.length.value');
        const itemW = document.getElementById('form_item_item_length_width_height.0.width.value');
        const itemH = document.getElementById('form_item_item_length_width_height.0.height.value');
        results['item_length'] = setVal(itemL, '11');
        results['item_width'] = setVal(itemW, '11');
        results['item_height'] = setVal(itemH, '11');
        
        // 3. パッケージ寸法(包装尺寸)
        const pkgL = document.getElementById('form_item_item_package_dimensions.0.length.value');
        const pkgW = document.getElementById('form_item_item_package_dimensions.0.width.value');
        const pkgH = document.getElementById('form_item_item_package_dimensions.0.height.value');
        results['pkg_length'] = setVal(pkgL, '33');
        results['pkg_width'] = setVal(pkgW, '33');
        results['pkg_height'] = setVal(pkgH, '33');
        
        // 4. 包装時の重さ(包装重量)
        const pkgWeight = document.getElementById('form_item_item_package_weight.0.value');
        results['pkg_weight'] = setVal(pkgWeight, '33');
        
        // 5. Search Terms
        const formItems = Array.from(document.querySelectorAll('.ant-form-item'));
        const stItem = formItems.find(fi => {
            const lbl = fi.querySelector('.ant-form-item-label, label');
            const txt = lbl ? (lbl.innerText || lbl.getAttribute('title') || '') : '';
            return txt.includes('Search Terms') || txt.includes('SearchTerms');
        });
        const searchTermsArea = stItem ? stItem.querySelector('textarea, input') : document.querySelector('textarea.w-800\\!');
        results['search_terms'] = setVal(searchTermsArea, '日本人気ペット用トイレトレー 自動洗浄ガード付き');
        
        return results;
    }"""
    
    res = engine.manager.run_on_browser_thread(lambda: page.evaluate(js))
    print("Fill results:", res)

if __name__ == "__main__":
    main()
