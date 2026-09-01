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

def verify_extra_images_batch():
    print("=" * 80, flush=True)
    print("🚀 【自动化测试与验证】SKU 附图批量应用至全部变体功能端到端全流程测试", flush=True)
    print(f"📁 截图输出目录: {ARTIFACT_DIR}", flush=True)
    print("=" * 80, flush=True)

    product_id = 56
    product = ProductService.get_product_by_id(product_id)
    assert product is not None, "Product 56 not found in database!"
    print(f"📦 测试商品: #{product['id']} - {product['title'][:40]}", flush=True)

    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect()
    assert ok, f"Browser connect failed: {msg}"

    engine.open_or_focus_url("https://www.dianxiaomi.com/web/amazon/add")
    time.sleep(1.0)

    # 1. 确保 variationImage 区域就绪
    def get_var_status():
        p = engine.manager._get_active_page_impl()
        return p.evaluate("""() => {
            const sec = document.querySelector('#variationImage');
            if (!sec) return { ready: false, count: 0 };
            const headers = Array.from(sec.querySelectorAll('.item-header'));
            return { ready: headers.length > 0, count: headers.length };
        }""")

    st = engine.manager.run_on_browser_thread(get_var_status)
    print(f"📊 当前页面变体卡片数量: {st.get('count')}", flush=True)

    # 2. 准备图片数据
    parent_extras = product.get("extra_images") or []
    parent_extra_abs_files = [
        FileService.resolve_image_path(p) 
        for p in parent_extras 
        if p and FileService.resolve_image_path(p) and os.path.exists(FileService.resolve_image_path(p))
    ]
    print(f"📸 待上传附图数量: {len(parent_extra_abs_files)} 张", flush=True)
    assert len(parent_extra_abs_files) > 0, "No extra images resolved!"

    # 3. 针对第一个变体执行附图上传与批量应用
    first_var = product["variations"][0]
    col1 = first_var["color"]
    sz1 = first_var["size"]
    filter_crit1 = {"颜色": col1, "尺寸": sz1}
    print(f"\n🎯 步骤 1: 为第一个变体【{col1} / {sz1}】上传附图并执行「附图 ➔ 所有变体」批量应用...", flush=True)

    # 3.1 上传附图
    upload_res = engine.upload_variation_image(
        filter_criteria=filter_crit1,
        image_path=parent_extra_abs_files,
        image_type="extra",
        timeout_ms=30000
    )
    print(f"   • 第一个变体附图上传结果: {'✅ 成功' if upload_res else '❌ 失败'}", flush=True)

    # 3.2 批量应用「附图 ➔ 所有变体」
    print("🎯 步骤 2: 触发「图片应用到」下拉并选择【附图 ➔ 所有变体】...", flush=True)
    apply_res = False
    for attempt in range(3):
        print(f"   • 第 {attempt+1} 次尝试调用 apply_variation_image(extra_all)...", flush=True)
        if engine.apply_variation_image(filter_criteria=filter_crit1, apply_type="extra_all", timeout_ms=10000):
            apply_res = True
            print("   ✅ apply_variation_image(extra_all) 调用成功！", flush=True)
            break
        time.sleep(1.0)

    assert apply_res, "apply_variation_image(extra_all) 失败！"

    # 4. 验证所有变体卡片中的附图是否均已同步装配
    print("\n🔍 步骤 3: 深度检验所有变体卡片中附图装配与同步情况...", flush=True)
    time.sleep(1.5)

    def check_all_cards():
        p = engine.manager._get_active_page_impl()
        return p.evaluate("""() => {
            const sec = document.querySelector('#variationImage');
            if (!sec) return [];
            const headers = Array.from(sec.querySelectorAll('.item-header'));
            return headers.map((h, idx) => {
                const body = h.nextElementSibling;
                const p8s = body ? Array.from(body.querySelectorAll('.p8')) : [];
                const extraBox = p8s[2]; // 第 3 个框为附图框
                const imgs = extraBox ? Array.from(extraBox.querySelectorAll('img')) : [];
                const realImgs = imgs.filter(i => !/addimg|kong-|\\/assets\\//i.test(i.src));
                return {
                    idx,
                    header: h.innerText.trim().replace(/\\n/g, ' | '),
                    extraRealCount: realImgs.length,
                    extraSrcs: realImgs.map(i => i.src.slice(-25))
                };
            });
        }""")

    cards_info = engine.manager.run_on_browser_thread(check_all_cards)
    print(f"📊 校验完成，共检索到 {len(cards_info)} 个变体卡片：", flush=True)
    all_passed = True
    for c in cards_info:
        count = c["extraRealCount"]
        status = "✅ 附图已全部同步 (8张)" if count >= 8 else f"❌ 附图数量不足 ({count}/8)"
        if count < 8:
            all_passed = False
        print(f"   • 卡片 #{c['idx']} 【{c['header'][:40]}】: {status}", flush=True)

    # 5. 截取高清现场留痕图片
    print("\n📸 步骤 4: 生成高清测试现场留痕截图...", flush=True)
    
    # 截图 1: 变体卡片 1 附图与图片应用菜单
    s1_path = os.path.join(ARTIFACT_DIR, "sku_extra_batch_01_first_card.png")
    def cap_s1():
        p = engine.manager._get_active_page_impl()
        sec = p.locator("#variationImage")
        sec.scroll_into_view_if_needed()
        p.wait_for_timeout(500)
        p.screenshot(path=s1_path)
    engine.manager.run_on_browser_thread(cap_s1)
    print(f"   📸 [截图 1] 第一个卡片与变体列表: {s1_path}", flush=True)

    # 截图 2: 滚动展示后续变体卡片附图已全部批量同步
    s2_path = os.path.join(ARTIFACT_DIR, "sku_extra_batch_02_all_synced.png")
    def cap_s2():
        p = engine.manager._get_active_page_impl()
        p.evaluate("() => { const sec = document.querySelector('#variationImage'); if(sec) sec.scrollIntoView({block: 'center'}); }")
        p.wait_for_timeout(500)
        p.screenshot(path=s2_path)
    engine.manager.run_on_browser_thread(cap_s2)
    print(f"   📸 [截图 2] 全量变体附图批量同步完成: {s2_path}", flush=True)

    assert all_passed, "存在变体附图未同步到 8 张！"
    print("\n🎉 【全流程自动化测试全部通过】SKU 附图批量应用至全部变体已 100% 验证成功！", flush=True)

if __name__ == "__main__":
    verify_extra_images_batch()
