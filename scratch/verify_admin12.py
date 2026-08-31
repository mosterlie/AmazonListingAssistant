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
        const brandInp = document.querySelector('div[data-path="brand.0.value"] input') || document.querySelector('input[placeholder="请输入品牌"]');
        const mfgInp = document.querySelector('div[data-path="manufacturer.0.value"] input') || document.querySelector('input[placeholder="请输入制造商"]');
        
        // 变体表格
        const trs = Array.from(document.querySelectorAll('#variationInfo table tbody tr'));
        const rowsData = trs.map((tr, idx) => {
            const inputs = Array.from(tr.querySelectorAll('input')).map(i => i.value);
            return { index: idx, inputs: inputs };
        });
        
        // 变体图片
        const imageCards = Array.from(document.querySelectorAll('#variationImage .item-header')).map((h, idx) => {
            const txt = (h.innerText || '').trim();
            const body = h.nextElementSibling;
            const mainImg = body ? body.querySelector('.p8:nth-child(1) img')?.src : '';
            const extraImgs = body ? Array.from(body.querySelectorAll('.p8:nth-child(3) img')).map(el => el.src).filter(s => s && !s.includes('kong')) : [];
            return {
                title: txt.replace(/\n/g, ' '),
                has_main: Boolean(mainImg && !mainImg.includes('kong')),
                extra_count: extraImgs.length
            };
        });
        
        return {
            store: storeVal,
            site: siteVal,
            title: titleInp ? titleInp.value : '',
            parentSku: parentSkuInp ? parentSkuInp.value : '',
            brand: brandInp ? brandInp.value : '',
            manufacturer: mfgInp ? mfgInp.value : '',
            variation_rows_count: rowsData.length,
            variation_rows: rowsData,
            image_cards_count: imageCards.length,
            image_cards: imageCards
        };
    }"""
    
    res = engine.manager.run_on_browser_thread(lambda: page.evaluate(js))
    with open("scratch/admin12_verify.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print("Verification dumped to scratch/admin12_verify.json")

if __name__ == "__main__":
    main()
