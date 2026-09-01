import os
import sys
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine

def inspect_var_images():
    e = BrowserEngine(port=9222)
    e.connect()
    
    def run():
        page = e.manager._get_active_page_impl()
        
        info = page.evaluate("""() => {
            const cards = Array.from(document.querySelectorAll('#variationImage .item-header, #variationImage .variation-item, #variationImage [class*=\"item\"]'));
            // Find variation item wraps
            const wraps = Array.from(document.querySelectorAll('#variationImage .overflow-y-auto > div, #variationImage .max-h-700 > div'));
            
            return wraps.map((w, idx) => {
                const header = w.querySelector('.item-header')?.innerText.trim() || '';
                const imgs = Array.from(w.querySelectorAll('img')).map(i => ({
                    src: i.src,
                    alt: i.alt,
                    isPlaceholder: i.src.includes('addimg') || i.src.includes('kong-')
                }));
                const realImgs = imgs.filter(i => !i.isPlaceholder);
                return {
                    index: idx,
                    header: header.replace(/\\n/g, ' | '),
                    totalImgs: imgs.length,
                    realImgsCount: realImgs.length,
                    realSrcs: realImgs.map(i => i.src.slice(-30))
                };
            });
        }""")
        
        print(f"Total variation wraps: {len(info)}")
        for item in info:
            print(f"Wrap #{item['index']}: {item['header'][:50]}")
            print(f"  Real images: {item['realImgsCount']} -> {item['realSrcs']}")
            
    e.manager.run_on_browser_thread(run)

if __name__ == "__main__":
    inspect_var_images()
