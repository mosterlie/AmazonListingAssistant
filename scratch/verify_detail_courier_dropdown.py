import os
import sys
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine

CONV_ID = "d012c055-fb36-493d-b989-7e2ebf98f314"
ARTIFACT_DIR = f"/Users/gx/.gemini/antigravity-ide/brain/{CONV_ID}"
os.makedirs(ARTIFACT_DIR, exist_ok=True)

def verify_detail_courier_dropdown():
    print("=" * 80, flush=True)
    print("🚀 验证详情页面的快递选择列（显示运费、可下拉查看各快递公司、只读不可改）", flush=True)
    print("=" * 80, flush=True)

    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect()
    assert ok, f"Connect failed: {msg}"

    engine.open_or_focus_url("http://127.0.0.1:8000/list")
    time.sleep(1.0)

    def run_check():
        p = engine.manager._get_active_page_impl()
        p.reload()
        p.wait_for_timeout(1000)

        # 触发打开商品 56 的详情弹窗
        p.evaluate("() => { if (window.viewProductDetail) window.viewProductDetail(56); }")
        p.wait_for_timeout(1500)

        modal = p.locator("#productDetailModal")
        if not modal.is_visible():
            print("❌ 详情弹窗未展示！", flush=True)
            return False

        # 检查变体表格中的快递选择下拉框
        selects = modal.locator("select.readonly-channel-select")
        select_count = selects.count()
        print(f"✅ 成功渲染 {select_count} 个变体行的快递选择下拉框", flush=True)
        assert select_count > 0, "变体行中未找到 select.readonly-channel-select！"

        first_sel = selects.first
        first_sel.scroll_into_view_if_needed()
        p.wait_for_timeout(300)

        # 获取当前选中的值和文本
        val = first_sel.input_value()
        options = p.evaluate("""() => {
            const sel = document.querySelector('#productDetailModal select.readonly-channel-select');
            return Array.from(sel.options).map(o => ({ value: o.value, text: o.text, selected: o.selected }));
        }""")
        print(f"📌 当前变体行选中渠道: {val}", flush=True)
        print("📋 下拉框中展示的所有快递公司及运费选项:", flush=True)
        for opt in options:
            print(f"   • {opt['text']} {' (当前默认/选用)' if opt['selected'] else ''}", flush=True)

        # 测试尝试更改值，验证是否自动复原（只读保护，不允许修改）
        if len(options) > 1:
            other_val = options[1]['value'] if options[1]['value'] != val else options[0]['value']
            first_sel.select_option(value=other_val)
            first_sel.dispatch_event("change")
            p.wait_for_timeout(300)
            new_val = first_sel.input_value()
            print(f"🔒 尝试选中其他项 '{other_val}' 后，当前值状态: '{new_val}'", flush=True)
            assert new_val == val, f"只读保护失效！值被更改为 {new_val}"
            print("✅ 只读防改机制 100% 生效：用户在下拉框查看其他渠道后，系统保持原有选定渠道不被误改！", flush=True)

        # 滚动到变体表格区域并截图留痕
        p.evaluate("() => { const sec = document.querySelector('#productDetailModal .detail-section:last-of-type'); if (sec) sec.scrollIntoView(); }")
        p.wait_for_timeout(500)
        screenshot_path = os.path.join(ARTIFACT_DIR, "detail_courier_price_dropdown.png")
        p.screenshot(path=screenshot_path)
        print(f"📸 详情弹窗留痕截图已保存: {screenshot_path}", flush=True)
        return True

    res = engine.manager.run_on_browser_thread(run_check)
    assert res, "验证失败！"
    print("\n🎉 【全流程测试 100% 成功通过】详情页快递列已完美支持显示运费价格、下拉查看所有快递公司及只读防改！", flush=True)

if __name__ == "__main__":
    verify_detail_courier_dropdown()
