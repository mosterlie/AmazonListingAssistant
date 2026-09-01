import sys, os, json
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path: sys.path.insert(0, PROJECT_DIR)
from browser_engine import BrowserEngine

def inspect_radios():
    engine = BrowserEngine(port=9222)
    engine.connect(activate=False)
    def run():
        p = engine.manager._get_active_page_impl()
        res = p.evaluate("""() => {
            const radios = Array.from(document.querySelectorAll('.ant-radio-wrapper, .ant-checkbox-wrapper, label.ant-radio-button-wrapper, input[type="radio"]')).map(r => ({
                text: (r.innerText || r.textContent || '').trim(),
                checked: r.classList?.contains('ant-radio-wrapper-checked') || r.querySelector('input')?.checked
            }));
            return radios;
        }""")
        print("Radios:", json.dumps(res, ensure_ascii=False, indent=2))
    engine.manager.run_on_browser_thread(run)

if __name__ == "__main__":
    inspect_radios()
