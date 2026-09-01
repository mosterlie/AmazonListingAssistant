import sys
import os
sys.path.insert(0, os.path.abspath("."))
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import time
from server.services.erp_bridge import ERPBridgeService
from browser_engine import BrowserEngine

def run_test():
    print("=" * 80)
    print("🚀 【附图批量应用与逐 SKU 附图数量深度核验测试】")
    print("=" * 80)

    def on_log(line: str):
        print(f"  {line}")

    # 执行自动化上件（阶段 1 ~ 阶段 5 变体附图与主图装配）
    res = ERPBridgeService.publish_product_to_erp(61, log_callback=on_log)
    print("\n" + "=" * 80)
    print(f"📊 上件执行结果: success={res.get('success')}, msg={res.get('msg')}")
    print("=" * 80)

    # 最终连接页面并打印每个 SKU 的附图与主图详情
    engine = BrowserEngine(port=9222)
    ok, _ = engine.connect(activate=False)
    if ok:
        js_summary = """
        () => {
            const sec = document.querySelector('#variationImage');
            if (!sec) return { ok: false };
            const headers = Array.from(sec.querySelectorAll('.item-header'));
            return {
                ok: true,
                total: headers.length,
                cards: headers.map((h, i) => {
                    const text = h.innerText.replace(/\\s+/g, ' ').trim();
                    const body = h.nextElementSibling;
                    const p8s = body ? Array.from(body.querySelectorAll('.p8')) : [];
                    
                    const mainImgs = p8s[0] ? Array.from(p8s[0].querySelectorAll('img')).filter(img => !/addimg|kong-|\\/assets\\//i.test(img.src)) : [];
                    const extraImgs = p8s[2] ? Array.from(p8s[2].querySelectorAll('img')).filter(img => !/addimg|kong-|\\/assets\\//i.test(img.src)) : [];

                    return {
                        idx: i + 1,
                        text: text,
                        mainCount: mainImgs.length,
                        extraCount: extraImgs.length
                    };
                })
            };
        }
        """
        data = engine.manager.run_on_browser_thread(lambda: engine.manager._get_active_page_impl().evaluate(js_summary))
        if data and data.get("ok"):
            print(f"\n📋 【页面 DOM 实时核查】全部 {data['total']} 个 SKU 的附图与主图统计:")
            for c in data["cards"]:
                tag = "✅ 附图已同步" if c["extraCount"] > 0 else "❌ 附图缺失"
                print(f"   • SKU #{c['idx']:02d} | 附图: 【{c['extraCount']} 张】({tag}) | 主图: 【{c['mainCount']} 张】 | 规格: {c['text']}")

if __name__ == "__main__":
    run_test()
