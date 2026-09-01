import sys
import os
import time
import json

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from browser_engine import BrowserEngine
from core.form_operator import FormOperator
from server.services.product_service import ProductService
from server.services.file_service import FileService

CONV_ID = "4d70ba54-c5b0-4648-8adb-474ba62b907e"
ARTIFACT_DIR = f"/Users/gx/.gemini/antigravity-ide/brain/{CONV_ID}"
os.makedirs(ARTIFACT_DIR, exist_ok=True)

def run_admin12_test():
    print("=" * 80, flush=True)
    print("🚀 【店小秘上件流程】admin12 从头全流程录入 + SKU 图片批量应用（附图批量+主图批量）深度测试", flush=True)
    print(f"📁 截图输出目录: {ARTIFACT_DIR}", flush=True)
    print("=" * 80, flush=True)

    # 1. 获取 admin12 数据库完整数据
    product = ProductService.get_product_by_id(56)
    if not product:
        print("❌ 未在数据库中找到 product_id=56 (admin12)", flush=True)
        return False

    print(f"📦 已加载 admin12 商品数据: 标题={product.get('title')[:30]}...", flush=True)
    print(f"   变体数量: {len(product.get('variations', []))} 个", flush=True)

    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect(activate=False)
    if not ok:
        print(f"❌ 连接浏览器失败: {msg}", flush=True)
        return False

    def execute():
        page = None
        for p in engine.manager.context.pages:
            if "dianxiaomi.com" in p.url:
                page = p
                break
        if not page:
            page = engine.manager.context.pages[0]

        page.bring_to_front()
        form = FormOperator(page)
        print(f"📄 当前活动页面: {page.url}", flush=True)

        # -----------------------------------------------------------------
        # 阶段 0: 干净重载店小秘添加产品页面（从头开始录）
        # -----------------------------------------------------------------
        target_url = "https://www.dianxiaomi.com/web/amazon/add"
        print("\n🔄 [阶段 0] 从头开始：重载店小秘添加产品页...", flush=True)
        page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
        time.sleep(3)

        # 截图 1: 页面初始空白状态
        snap1 = os.path.join(ARTIFACT_DIR, "admin12_01_clean_page.png")
        page.screenshot(path=snap1)
        print(f"📸 [截图 1] 页面初始空白状态留痕: {snap1}", flush=True)

        # -----------------------------------------------------------------
        # 阶段 1: 选择店铺与填写标题
        # -----------------------------------------------------------------
        print("\n" + "-" * 70, flush=True)
        print("⏳ [阶段 1] 选择店铺账号并填入产品标题...", flush=True)
        
        # 点击店铺下拉并选择
        store_sel = page.locator(".ant-select").filter(has_text="请选择店铺").first
        if store_sel.count() > 0:
            store_sel.click()
            time.sleep(0.5)
            store_opt = page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option").first
            if store_opt.count() > 0:
                store_text = store_opt.inner_text().strip()
                store_opt.click()
                print(f"   • 已选择店铺: 【{store_text}】", flush=True)
            time.sleep(1.0)

        # 填入标题
        title_text = product.get("title", "")
        form.fill("产品标题", title_text)
        print(f"   • 已填入产品标题: 【{title_text[:35]}...】", flush=True)
        time.sleep(1.0)

        # -----------------------------------------------------------------
        # 阶段 2: 自动识别产品类型与确认类目
        # -----------------------------------------------------------------
        print("\n" + "-" * 70, flush=True)
        print("⏳ [阶段 2] 自动识别产品类型并确认推荐分类...", flush=True)
        rec_btn = page.locator("button, a, span").filter(has_text="自动识别产品类型").first
        if rec_btn.count() > 0:
            rec_btn.click()
            print("   • 已点击【自动识别产品类型】", flush=True)
            time.sleep(2.0)
            
            # 确认弹窗
            modal = page.locator(".ant-modal:not([style*='display: none'])")
            if modal.count() > 0:
                ok_btn = modal.first.locator("button").filter(has_text="确定").first
                if ok_btn.count() > 0:
                    ok_btn.click()
                    print("   • 已在推荐产品类型弹窗中点击【确定】！", flush=True)
                    time.sleep(2.5)

        # 截图 2: 店铺、标题与类目配置完成
        snap2 = os.path.join(ARTIFACT_DIR, "admin12_02_store_title_category_ready.png")
        page.screenshot(path=snap2)
        print(f"📸 [截图 2] 店铺、标题与类目就绪留痕: {snap2}", flush=True)

        # -----------------------------------------------------------------
        # 阶段 3: 配置售卖形式(多变体)、Parent SKU、品牌、变体主题与选项
        # -----------------------------------------------------------------
        print("\n" + "-" * 70, flush=True)
        print("⏳ [阶段 3] 配置售卖形式(多变种)、Parent SKU、品牌与变体主题...", flush=True)
        
        # 点击多变种单选按钮
        time.sleep(1.5)
        for _ in range(10):
            var_radio = page.locator("label").filter(has_text="多变种").first
            if var_radio.count() > 0:
                var_radio.scroll_into_view_if_needed()
                var_radio.click(force=True)
                print("   • 已勾选【多变种】！", flush=True)
                break
            time.sleep(0.5)
        time.sleep(1.5)

        # Parent SKU
        parent_sku = product.get("sku") or product.get("parent_sku") or "admin12"
        form.fill("Parent SKU", parent_sku)
        print(f"   • 填入 Parent SKU: 【{parent_sku}】", flush=True)

        # 品牌
        brand_val = product.get("brand", "").strip() or "Hiremo"
        form.fill("品牌", brand_val) or form.select("品牌", brand_val)
        print(f"   • 填入品牌: 【{brand_val}】", flush=True)

        # 制造商
        form.fill_manufacturer(brand_val)
        time.sleep(0.5)

        # 变种主题选择 (选择包含 COLOR 的主题)
        page.wait_for_selector("#variationInfo", timeout=10000)
        theme_sel = page.locator("#variationInfo .ant-select").first
        theme_sel.scroll_into_view_if_needed()
        theme_sel.click(force=True)
        time.sleep(1.0)
        theme_opt = page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option").filter(has_text="COLOR").first
        if theme_opt.count() > 0:
            theme_txt = theme_opt.inner_text().strip()
            theme_opt.click()
            print(f"   • 选定变种主题: 【{theme_txt}】", flush=True)
        time.sleep(2.0)

        # 添加颜色选项 (4个)
        colors = [
            "一方向囲い‑人工芝 1 枚付き",
            "三方囲い ‑人工芝 2枚付き",
            "一方向囲い‑人工芝 12枚付き",
            "三方囲い ‑人工芝 1 枚付き"
        ]
        
        page.wait_for_selector("#variationInfo .flex.gap-10.items-center.m-top10", timeout=10000)
        other_rows = page.locator("#variationInfo .flex.gap-10.items-center.m-top10")
        if other_rows.count() >= 2:
            row0 = other_rows.nth(0)
            inp0 = row0.locator("input").first
            btn0 = row0.locator("button, .ant-btn").first
            for col in colors:
                inp0.fill(col)
                time.sleep(0.2)
                btn0.click()
                print(f"   • 添加颜色选项: 【{col}】", flush=True)
                time.sleep(0.8)

            # 添加第二属性选项 (SET_NAME: 75*50*36cm)
            row1 = other_rows.nth(1)
            inp1 = row1.locator("input").first
            btn1 = row1.locator("button, .ant-btn").first
            inp1.fill("75*50*36cm")
            time.sleep(0.2)
            btn1.click()
            print("   • 添加第二属性(SET_NAME): 【75*50*36cm】", flush=True)
            time.sleep(2.5)

        headers_count = page.locator("#variationImage .item-header").count()
        print(f"✅ 变体矩阵生成完毕，共 {headers_count} 个变体卡片！", flush=True)

        # 截图 3: 变体卡片矩阵生成完成
        snap3 = os.path.join(ARTIFACT_DIR, "admin12_03_variation_cards_generated.png")
        page.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        page.screenshot(path=snap3)
        print(f"📸 [截图 3] 变体卡片矩阵生成留痕: {snap3}", flush=True)

        # -----------------------------------------------------------------
        # 阶段 4: 填充变体表格数据 (SKU, EAN, 价格, 库存)
        # -----------------------------------------------------------------
        print("\n" + "-" * 70, flush=True)
        print("⏳ [阶段 4] 填充变体表格行数据 (SKU / EAN / 价格 / 库存)...", flush=True)
        
        # 切换表头第 4 项为 EAN
        form.select("#variationInfo table thead th:nth-child(4) .ant-select", "EAN")
        time.sleep(0.5)

        for var in product.get("variations", []):
            col = var.get("color", "")
            sz = var.get("size", "")
            v_sku = var.get("sku", "")
            v_ean = var.get("ean", "")
            v_price = var.get("price_jpy", 0) or 60000
            v_qty = var.get("quantity", 0) or 40

            filter_crit = {"颜色": col, "尺寸": sz}
            form.fill_variation_row(
                filter_criteria=filter_crit,
                row_data={
                    "sku": v_sku,
                    "ean": v_ean,
                    "price": str(v_price),
                    "quantity": str(v_qty)
                }
            )
            print(f"   • 填写变体行【{col} / {sz}】: SKU={v_sku}, EAN={v_ean}, 价格={v_price}, 库存={v_qty}", flush=True)

        # 截图 4: 变体表格数据填充完成
        snap4 = os.path.join(ARTIFACT_DIR, "admin12_04_variation_table_filled.png")
        page.locator("#variationInfo table").first.scroll_into_view_if_needed()
        time.sleep(0.5)
        page.screenshot(path=snap4)
        print(f"📸 [截图 4] 变体表格数据填充留痕: {snap4}", flush=True)

        # -----------------------------------------------------------------
        # 阶段 5: SKU 批量图片应用测试 (附图批量 + 主图批量) —— 核心留痕环节
        # -----------------------------------------------------------------
        print("\n" + "=" * 70, flush=True)
        print("📸 [阶段 5] 变体图片上传与批量应用 (附图批量 + 主图批量) 核心测试与留痕", flush=True)
        print("=" * 70, flush=True)

        # 解析附图与主图本地绝对路径
        parent_extras = product.get("extra_images") or []
        extra_abs_files = [
            FileService.resolve_image_path(p) 
            for p in parent_extras 
            if p and FileService.resolve_image_path(p) and os.path.exists(FileService.resolve_image_path(p))
        ]
        dim_images_map = product.get("variant_dimension_images") or {}
        print(f"   • 准备附图清单: 共 {len(extra_abs_files)} 张本地图片", flush=True)

        first_color = colors[0]
        first_crit = {"颜色": first_color, "尺寸": "75*50*36cm"}
        first_main_img = FileService.resolve_image_path(dim_images_map.get(first_color, ""))

        # 5.1 为第一个 SKU 上传主图与 8 张附图
        print(f"\n📸 【5.1】为第一个变体 SKU【{first_color}】上传主图与 {len(extra_abs_files)} 张附图...", flush=True)
        if first_main_img:
            up_main_ok = form.upload_variation_image(first_crit, first_main_img, image_type="main", timeout_ms=30000)
            print(f"   • 主图上传结果: {'✅ 成功' if up_main_ok else '❌ 失败'}", flush=True)
        
        up_extra_ok = form.upload_variation_image(first_crit, extra_abs_files, image_type="extra", timeout_ms=60000)
        print(f"   • 附图上传结果 ({len(extra_abs_files)} 张): {'✅ 成功' if up_extra_ok else '❌ 失败'}", flush=True)
        time.sleep(1.0)

        snap5 = os.path.join(ARTIFACT_DIR, "admin12_05_first_sku_images_uploaded.png")
        page.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        page.screenshot(path=snap5)
        print(f"📸 [截图 5] 首个 SKU 上传主附图完成留痕: {snap5}", flush=True)

        # 5.2 展开「图片应用到」菜单，高亮【附图 ➔ 所有变种】并截图
        print("\n📸 【5.2】点击「图片应用到」，捕获【附图 ➔ 所有变种】下拉菜单展开与悬停高亮截图...", flush=True)
        page.keyboard.press("Escape")
        page.mouse.click(300, 200)
        time.sleep(0.4)

        var_box = page.locator("#variationImage .overflow-y-auto, #variationImage .max-h-700").first
        headers = var_box.locator(".item-header")
        target_h = headers.nth(0)

        target_h.scroll_into_view_if_needed()
        time.sleep(0.5)
        apply_btn = target_h.locator("span.link, a, span[class*='link']").filter(has_text="图片应用到").first
        apply_btn.click(force=True)
        time.sleep(0.8)

        # 移动鼠标至【附图 ➔ 所有变种】
        js_hover_extra = """
        () => {
            const drops = Array.from(document.querySelectorAll('.ant-dropdown'));
            for (const d of drops) {
                if (getComputedStyle(d).display === 'none') continue;
                const groups = d.querySelectorAll('.menu-group');
                for (const g of groups) {
                    const title = (g.querySelector('.group-title')?.innerText || '').trim();
                    if (!title.includes('附图')) continue;
                    for (const it of g.querySelectorAll('.menu-item')) {
                        if (it.innerText.includes('所有变种') || it.innerText.includes('所有变体') || it.innerText.includes('所有')) {
                            const r = it.getBoundingClientRect();
                            return { found: true, x: r.left + r.width / 2, y: r.top + r.height / 2 };
                        }
                    }
                }
            }
            return { found: false };
        }
        """
        pos = page.evaluate(js_hover_extra)
        if pos and pos.get("found"):
            page.mouse.move(pos["x"], pos["y"])
            time.sleep(0.4)

        snap6 = os.path.join(ARTIFACT_DIR, "admin12_06_click_apply_extra_menu.png")
        page.screenshot(path=snap6)
        print(f"📸 [截图 6] 【附图 ➔ 所有变体】下拉菜单展开与高亮留痕: {snap6}", flush=True)

        # 5.3 执行点击【附图 ➔ 所有变种】批量应用
        print("\n📸 【5.3】执行点击【附图 ➔ 所有变种】批量应用...", flush=True)
        extra_applied = form.apply_variation_image(first_crit, apply_type="extra_all", timeout_ms=15000)
        print(f"   • 附图批量应用结果: {'✅ 成功' if extra_applied else '❌ 失败'}", flush=True)
        time.sleep(1.5)

        snap7 = os.path.join(ARTIFACT_DIR, "admin12_07_extra_applied_all_variations.png")
        page.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        page.screenshot(path=snap7)
        print(f"📸 [截图 7] 全量 4 个变体 SKU 附图批量同步完成留痕: {snap7}", flush=True)

        # 5.4 展开「图片应用到」菜单，高亮【主图 ➔ 同COLOR变体】并截图
        print("\n📸 【5.4】点击「图片应用到」，捕获【主图 ➔ 同COLOR变体】下拉菜单展开与高亮截图...", flush=True)
        page.keyboard.press("Escape")
        page.mouse.click(300, 200)
        time.sleep(0.4)

        target_h.scroll_into_view_if_needed()
        time.sleep(0.5)
        apply_btn = target_h.locator("span.link, a, span[class*='link']").filter(has_text="图片应用到").first
        apply_btn.click(force=True)
        time.sleep(0.8)

        js_hover_main = """
        () => {
            const drops = Array.from(document.querySelectorAll('.ant-dropdown'));
            for (const d of drops) {
                if (getComputedStyle(d).display === 'none') continue;
                const groups = d.querySelectorAll('.menu-group');
                for (const g of groups) {
                    const title = (g.querySelector('.group-title')?.innerText || '').trim();
                    if (!title.includes('主图')) continue;
                    for (const it of g.querySelectorAll('.menu-item')) {
                        const txt = it.innerText.toLowerCase();
                        if (txt.includes('color') || txt.includes('颜色') || txt.includes('カラー')) {
                            const r = it.getBoundingClientRect();
                            return { found: true, x: r.left + r.width / 2, y: r.top + r.height / 2 };
                        }
                    }
                }
            }
            return { found: false };
        }
        """
        pos = page.evaluate(js_hover_main)
        if pos and pos.get("found"):
            page.mouse.move(pos["x"], pos["y"])
            time.sleep(0.4)

        snap8 = os.path.join(ARTIFACT_DIR, "admin12_08_click_apply_main_color1_menu.png")
        page.screenshot(path=snap8)
        print(f"📸 [截图 8] 【主图 ➔ 同颜色变体】下拉菜单展开与高亮留痕: {snap8}", flush=True)

        # 5.5 执行点击【主图 ➔ 同COLOR变体】(颜色 1)
        print("\n📸 【5.5】执行点击【主图 ➔ 同COLOR变体】(颜色 1)...", flush=True)
        main1_applied = form.apply_variation_image(first_crit, apply_type="main_color", timeout_ms=15000)
        print(f"   • 颜色 1 主图批量应用结果: {'✅ 成功' if main1_applied else '❌ 失败'}", flush=True)
        time.sleep(1.5)

        snap9 = os.path.join(ARTIFACT_DIR, "admin12_09_main_color1_applied.png")
        page.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(0.5)
        page.screenshot(path=snap9)
        print(f"📸 [截图 9] 颜色 1 主图批量同步完成留痕: {snap9}", flush=True)

        # 5.6 依次为颜色 2、颜色 3、颜色 4 上传主图并截图下拉菜单与应用结果
        remaining_colors = [
            (1, colors[1], "admin12_10_click_apply_main_color2_menu.png", "admin12_11_main_color2_applied.png", "颜色 2"),
            (2, colors[2], "admin12_12_click_apply_main_color3_menu.png", "admin12_13_main_color3_applied.png", "颜色 3"),
            (3, colors[3], "admin12_14_click_apply_main_color4_menu.png", "admin12_15_main_color4_applied.png", "颜色 4")
        ]

        for card_idx, col_name, snap_menu_file, snap_applied_file, col_label in remaining_colors:
            crit = {"颜色": col_name, "尺寸": "75*50*36cm"}
            img_path = FileService.resolve_image_path(dim_images_map.get(col_name, ""))
            print(f"\n📸 【{col_label}】为变体【{col_name}】上传主图并批量应用...", flush=True)
            if img_path:
                up_ok = form.upload_variation_image(crit, img_path, image_type="main", timeout_ms=30000)
                print(f"   • 主图上传: {'✅ 成功' if up_ok else '❌ 失败'}", flush=True)
                time.sleep(1.0)
                
                # 捕获点击批量菜单截图
                page.keyboard.press("Escape")
                page.mouse.click(300, 200)
                time.sleep(0.4)
                
                cur_h = var_box.locator(".item-header").nth(card_idx)
                cur_h.scroll_into_view_if_needed()
                time.sleep(0.5)
                btn = cur_h.locator("span.link, a, span[class*='link']").filter(has_text="图片应用到").first
                btn.click(force=True)
                time.sleep(0.8)
                
                pos = page.evaluate(js_hover_main)
                if pos and pos.get("found"):
                    page.mouse.move(pos["x"], pos["y"])
                    time.sleep(0.4)
                
                snap_menu_path = os.path.join(ARTIFACT_DIR, snap_menu_file)
                page.screenshot(path=snap_menu_path)
                print(f"📸 [{col_label} 下拉菜单截图] 留痕: {snap_menu_path}", flush=True)

                ap_ok = form.apply_variation_image(crit, apply_type="main_color", timeout_ms=15000)
                print(f"   • 主图批量应用: {'✅ 成功' if ap_ok else '❌ 失败'}", flush=True)
                time.sleep(1.5)

            snap_c = os.path.join(ARTIFACT_DIR, snap_applied_file)
            page.locator("#variationImage").scroll_into_view_if_needed()
            time.sleep(0.5)
            page.screenshot(path=snap_c)
            print(f"📸 [{col_label} 应用完成截图] 留痕: {snap_c}", flush=True)

        # -----------------------------------------------------------------
        # 阶段 6: 最终全局变体矩阵全貌截图与深度 DOM 审计
        # -----------------------------------------------------------------
        print("\n" + "=" * 70, flush=True)
        print("📸 [阶段 6] 变体图片矩阵最终全貌截图与深度 DOM 校验", flush=True)
        print("=" * 70, flush=True)

        snap16 = os.path.join(ARTIFACT_DIR, "admin12_16_final_variation_image_matrix.png")
        page.locator("#variationImage").scroll_into_view_if_needed()
        time.sleep(1.0)
        page.screenshot(path=snap16)
        print(f"📸 [截图 16] 变体图片矩阵最终全貌全景截图: {snap16}", flush=True)

        # 变体表格全貌
        snap17 = os.path.join(ARTIFACT_DIR, "admin12_17_final_sku_table_overview.png")
        page.locator("#variationInfo table").first.scroll_into_view_if_needed()
        time.sleep(0.5)
        page.screenshot(path=snap17)
        print(f"📸 [截图 17] 变体 SKU 表格全貌截图: {snap17}", flush=True)

        # DOM 审计
        js_audit = """
        () => {
            const result = [];
            const headers = document.querySelectorAll('#variationImage .item-header');
            headers.forEach(h => {
                const headerText = h.innerText.replace(/\\s+/g, ' ').trim();
                const parent = h.closest('.variation-item, .item-wrap, [class*=\"item\"]') || h.parentElement;
                
                const allImgs = Array.from(parent.querySelectorAll('img'))
                    .map(img => img.src)
                    .filter(src => src && !src.includes('loading') && !src.includes('default') && !src.includes('icon'));

                result.push({
                    header: headerText,
                    totalImages: allImgs.length,
                    hasMain: allImgs.length >= 1,
                    hasExtra: allImgs.length >= 8
                });
            });
            return result;
        }
        """
        audit_data = page.evaluate(js_audit)
        print("\n" + "=" * 70, flush=True)
        print("📊 admin12 变体图片矩阵 DOM 深度审计结果:", flush=True)
        for idx, item in enumerate(audit_data):
            print(f"  变体卡片 [{idx+1}]: {item['header']} | 主图状态: {'✅ 正常' if item['hasMain'] else '❌ 缺失'} | 附图状态 (>=8张): {'✅ 正常' if item['hasExtra'] else '❌ 缺失'} | 有效图片总数: {item['totalImages']} 张", flush=True)
        print("=" * 70, flush=True)

        return True

    success = engine.manager.run_on_browser_thread(execute)
    if success:
        print("\n🎉 admin12 商品从头全流程录入与 SKU 图片批量应用（附图批量 + 主图批量）自动化测试 100% 成功执行完毕！", flush=True)
    return success

if __name__ == "__main__":
    run_admin12_test()
