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
        const mfg = document.querySelector('div[data-path="manufacturer.0.value"] input')?.value || document.querySelector('input[placeholder="请输入制造商"]')?.value;
        const itemL = document.getElementById('form_item_item_length_width_height.0.length.value')?.value;
        const itemW = document.getElementById('form_item_item_length_width_height.0.width.value')?.value;
        const itemH = document.getElementById('form_item_item_length_width_height.0.height.value')?.value;
        
        const pkgL = document.getElementById('form_item_item_package_dimensions.0.length.value')?.value;
        const pkgW = document.getElementById('form_item_item_package_dimensions.0.width.value')?.value;
        const pkgH = document.getElementById('form_item_item_package_dimensions.0.height.value')?.value;
        
        const pkgWeight = document.getElementById('form_item_item_package_weight.0.value')?.value;
        
        const formItems = Array.from(document.querySelectorAll('.ant-form-item, div'));
        const stItem = formItems.find(fi => {
            const lbl = fi.querySelector('.ant-form-item-label, label');
            const txt = lbl ? (lbl.innerText || lbl.getAttribute('title') || '') : '';
            return txt.includes('Search Terms') || txt.includes('SearchTerms');
        });
        const st = (stItem ? stItem.querySelector('textarea, input') : document.querySelector('textarea.w-800\\!'))?.value;
        
        return {
            '1. 制造商 (Manufacturer)': mfg,
            '2. 品目寸法 (商品尺寸 长x宽x高)': `${itemL} x ${itemW} x ${itemH} cm`,
            '3. パッケージ寸法 (包装尺寸 长x宽x高)': `${pkgL} x ${pkgW} x ${pkgH} cm`,
            '4. 包装重量 (Package Weight)': `${pkgWeight} kg`,
            '5. Search Terms (搜索词)': st
        };
    }"""
    
    res = engine.manager.run_on_browser_thread(lambda: page.evaluate(js))
    print("\n" + "=" * 60)
    print("【前台 Chrome 页面实时字段校验结果】")
    print("=" * 60)
    for k, v in res.items():
        print(f" {k}: {v}")
    print("=" * 60)

if __name__ == "__main__":
    main()
