import os
import sys
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine
from server.services.product_service import ProductService
from server.services.file_service import FileService

CONV_ID = "d012c055-fb36-493d-b989-7e2ebf98f314"
ARTIFACT_DIR = f"/Users/gx/.gemini/antigravity-ide/brain/{CONV_ID}"
os.makedirs(ARTIFACT_DIR, exist_ok=True)

def test_strict_batch_verification():
    print("=" * 80, flush=True)
    print("🚀 【严格校验测试】点击批量应用后，必须完成 DOM 校验通过方可继续", flush=True)
    print("=" * 80, flush=True)

    product = ProductService.get_product_by_id(56)
    assert product is not None, "Product 56 not found!"

    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect()
    assert ok, f"Connect failed: {msg}"
    engine.open_or_focus_url("https://www.dianxiaomi.com/web/amazon/add")
    time.sleep(1.0)

    # 1. 附图批量应用与严格校验
    first_var = product["variations"][0]
    filter_crit = {"颜色": first_var["color"], "尺寸": first_var["size"]}
    print(f"\n🎯 1. 触发【附图 ➔ 所有变体】批量应用，并进行严格 DOM 校验...", flush=True)
    
    t0 = time.time()
    apply_extra_ok = engine.apply_variation_image(
        filter_criteria=filter_crit,
        apply_type="extra_all",
        timeout_ms=15000,
        verify_success=True
    )
    cost = time.time() - t0
    print(f"   • 【附图 ➔ 所有变体】批量应用及自动校验结果: {'✅ 通过' if apply_extra_ok else '❌ 未通过'} (耗时 {cost:.2f}s)", flush=True)
    assert apply_extra_ok, "附图批量应用校验失败！"

    # 2. 独立调用 verify_variation_batch_applied 再次确认
    v_extra = engine.verify_variation_batch_applied(filter_criteria=filter_crit, apply_type="extra_all", timeout_ms=3000)
    print(f"   • 独立验证器 verify_variation_batch_applied(extra_all): {'✅ 确认全部同步' if v_extra else '❌ 校验不一致'}", flush=True)
    assert v_extra, "独立验证器校验失败！"

    # 3. 主图按颜色批量应用与严格校验
    print(f"\n🎯 2. 触发【主图 ➔ 同颜色变种】批量应用，并进行严格 DOM 校验...", flush=True)
    t0 = time.time()
    apply_main_ok = engine.apply_variation_image(
        filter_criteria=filter_crit,
        apply_type="main_color",
        timeout_ms=15000,
        verify_success=True
    )
    cost = time.time() - t0
    print(f"   • 【主图 ➔ 同颜色变体】批量应用及自动校验结果: {'✅ 通过' if apply_main_ok else '❌ 未通过'} (耗时 {cost:.2f}s)", flush=True)
    assert apply_main_ok, "主图批量应用校验失败！"

    v_main = engine.verify_variation_batch_applied(filter_criteria=filter_crit, apply_type="main_color", timeout_ms=3000)
    print(f"   • 独立验证器 verify_variation_batch_applied(main_color): {'✅ 确认同颜色变体主图已全部同步' if v_main else '❌ 校验不一致'}", flush=True)
    assert v_main, "主图独立验证器校验失败！"

    # 4. 截图留痕
    s_path = os.path.join(ARTIFACT_DIR, "batch_apply_verified_success.png")
    def cap():
        p = engine.manager._get_active_page_impl()
        p.locator("#variationImage").scroll_into_view_if_needed()
        p.wait_for_timeout(400)
        p.screenshot(path=s_path)
    engine.manager.run_on_browser_thread(cap)
    print(f"\n📸 [校验现场截图]: {s_path}", flush=True)

    print("\n🎉 【批量应用校验测试 100% 成功通过】每次点完批量应用后均已严格校验 DOM 生效后再往下继续！", flush=True)

if __name__ == "__main__":
    test_strict_batch_verification()
