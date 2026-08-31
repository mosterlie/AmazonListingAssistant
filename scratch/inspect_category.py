import sys
import os
import json

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
        const btn = Array.from(document.querySelectorAll('button, .ant-btn')).find(b => (b.innerText || '').includes('自动识别产品类型'));
        const container = btn ? btn.closest('.ant-form-item, div.flex, div') : null;
        
        // 查找分类显示的文本元素
        const allSpans = Array.from(document.querySelectorAll('span, div, p, label')).filter(el => {
            const t = (el.innerText || '').trim();
            return (t.includes('未选择分类') || t.includes('分类') || t.includes('产品类型')) && el.children.length <= 1;
        }).map(el => ({ tag: el.tagName, className: el.className, text: el.innerText.trim() }));
        
        return {
            btn_found: Boolean(btn),
            container_html: container ? container.innerHTML.slice(0, 800) : '',
            container_text: container ? container.innerText.slice(0, 300) : '',
            matching_spans: allSpans
        };
    }"""
    
    res = engine.manager.run_on_browser_thread(lambda: page.evaluate(js))
    with open("scratch/category_dom.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print("Dumped to scratch/category_dom.json")

if __name__ == "__main__":
    main()
