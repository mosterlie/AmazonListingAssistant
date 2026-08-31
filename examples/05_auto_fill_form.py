#!/usr/bin/env python3
"""
示例 5：页面表单自动化智能填写（步骤式逐步执行演示）
"""
import os
import sys
import time

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
    print("🔍 正在连接当前 Chrome 浏览器 (端口: 9222)...")
    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect(activate=True)
    if not ok:
        print(f"❌ 连接失败: {msg}")
        return

    test_images_dir = os.path.join(PROJECT_DIR, "test_images")
    img_black_m = os.path.join(test_images_dir, "black_m.jpg")
    img_yellow_l = os.path.join(test_images_dir, "yellow_l.jpg")
    img_blue_m = os.path.join(test_images_dir, "blue_m.jpg")
    img_white_s = os.path.join(test_images_dir, "white_s.jpg")

    target_url = "https://www.dianxiaomi.com/web/amazon/add"
    print(f"🌐 正在打开/重载创建亚马逊产品页面: {target_url} ...")
    engine.open_or_focus_url(target_url)
    engine.manager.run_on_browser_thread(
        lambda: engine.manager._get_active_page_impl().goto(target_url, wait_until="domcontentloaded", timeout=15000)
    )
    time.sleep(2.5)
    active_tab = engine.get_active_tab_info()

    print(f"🎯 正在对前台页面 【{active_tab.title if active_tab else '未知'}】 执行自动化填写操作...")

    # =========================================================================
    # 步骤 1：在【店铺账号】下拉选择框中，选择【金梧汇辰】，并等待【站点选择】自动加载出【日本】
    # =========================================================================
    print("\n⏳ [操作 1] 正在选择【店铺账号】 ➔ 【金梧汇辰】...")
    s1 = engine.select("店铺账号", "金梧汇辰")
    if s1:
        print("   • 成功选中【店铺账号】: 金梧汇辰，正在等待【站点选择】自动加载出【日本】...")
        s1_site = engine.wait_for_value("站点选择", "日本", timeout_ms=10000)
        if s1_site:
            print("✅ [操作 1] 【站点选择】已成功自动加载并显示【日本】，数据准备就绪！")
        else:
            print("⚠️ [操作 1] 等待【站点选择】变为【日本】超时。")
    else:
        print("❌ [操作 1] 选择【金梧汇辰】失败！")
    time.sleep(0.5)

    # =========================================================================
    # 步骤 2：在【产品ID】下拉框选择【EAN】，并在输入框中填入【1111111111111】
    # =========================================================================
    print("\n⏳ [操作 2] 正在设置【产品ID】类型 ➔ 【EAN】，并填入数值 ➔ 【1111111111111】...")
    s2_type = engine.select("产品ID", "EAN")
    s2_val = engine.fill("产品ID", "1111111111111")
    if s2_type or s2_val:
        print("✅ [操作 2] 成功配置【产品ID】！")
    else:
        print("⚠️ [操作 2] 产品ID配置跳过（多变体模式下将在下方变体表格中配置）。")
    time.sleep(0.5)

    # =========================================================================
    # 步骤 3：在【产品标题】输入框中填入标题内容
    # =========================================================================
    title_text = "犬 トイレ トレー 囲い付き人工芝足上げ ガード お飛び散り防止 手入れ簡単洗える はみ出し防止 壁掛け 消臭 小型犬"
    print(f"\n⏳ [操作 3] 正在填入【产品标题】 ➔ 【{title_text[:25]}...】...")
    s3 = engine.fill("产品标题", title_text)
    if s3:
        print("✅ [操作 3] 成功填入【产品标题】！")
    else:
        print("❌ [操作 3] 填入【产品标题】失败！")
    time.sleep(0.5)

    # =========================================================================
    # 步骤 4：点击【自动识别产品类型】，并在弹出的确认框中点击【确定】
    # =========================================================================
    print("\n⏳ [操作 4] 正在点击【自动识别产品类型】...")
    s4_btn = engine.click_button("自动识别产品类型")
    if s4_btn:
        print("   • 成功触发【自动识别产品类型】，正在等待弹窗并确认...")
        s4_modal = engine.confirm_modal("确定", wait_timeout_ms=8000)
        if s4_modal:
            print("✅ [操作 4] 成功在弹出的产品类型推荐框中点击【确定】！")
            time.sleep(2)  # 等待动态分类及表单项加载完成
        else:
            print("⚠️ [操作 4] 弹窗未出现或点击【确定】超时。")
    else:
        print("❌ [操作 4] 未找到【自动识别产品类型】按钮！")
    time.sleep(0.5)

    # =========================================================================
    # 步骤 5：在【售卖形式/类型】单选框中勾选【多变体】（多变种）
    # =========================================================================
    print("\n⏳ [操作 5] 正在勾选【售卖形式】 ➔ 【多变体】...")
    s5 = engine.click_radio("多变体") or engine.click_radio("多变种")
    if s5:
        print("✅ [操作 5] 成功勾选【售卖形式】: 多变体（多变种）！")
    else:
        print("❌ [操作 5] 勾选【多变体】单选框失败！")
    time.sleep(0.5)

    # =========================================================================
    # 步骤 6：在【品牌】输入/选择框中配置【Hiremo】（默认选项）
    # =========================================================================
    print("\n⏳ [操作 6] 正在选择【品牌】 ➔ 【Hiremo】(默认选项)...")
    s6 = engine.fill("品牌", "Hiremo") or engine.select("品牌", "默认选项")
    if s6:
        print("✅ [操作 6] 成功为【品牌】填入/选定: Hiremo！")
    else:
        print("❌ [操作 6] 选定【品牌】默认选项失败！")
    time.sleep(0.5)

    # =========================================================================
    # 步骤 7：在【变种主题】下拉框中选择【カラー/サイズ(颜色/尺寸)】
    # =========================================================================
    print("\n⏳ [操作 7] 正在选择【变种主题】 ➔ 【カラー/サイズ(颜色/尺寸)】...")
    s7 = engine.select("变种主题", "カラー/サイズ(颜色/尺寸)")
    if s7:
        print("✅ [操作 7] 成功选择【变种主题】: カラー/サイズ(颜色/尺寸)！")
    else:
        print("❌ [操作 7] 选择【变种主题】失败！")
    time.sleep(1.0)

    # =========================================================================
    # 步骤 8：在【カラー(颜色)】部分增加“红色”、“ad”与“dd”三项选项
    # =========================================================================
    print("\n⏳ [操作 8] 正在为【カラー(颜色)】添加自定义选项 ➔ 【红色】、【ad】、【dd】...")
    for color_opt in ["红色", "ad", "dd"]:
        ok_color = engine.add_variation_option("カラー", color_opt)
        if ok_color:
            print(f"   • 成功添加颜色选项: {color_opt}")
        time.sleep(0.3)
    print("✅ [操作 8] 成功在【カラー(颜色)】中添加【红色】、【ad】与【dd】！")
    time.sleep(0.5)

    # =========================================================================
    # 步骤 9：在【サイズ(尺寸)】部分分别增加“xx”、“mm”、“tt”与“ss”四项
    # =========================================================================
    print("\n⏳ [操作 9] 正在为【サイズ(尺寸)】添加选项 ➔ 【xx】、【mm】、【tt】、【ss】...")
    for size_opt in ["xx", "mm", "tt", "ss"]:
        ok_size = engine.add_variation_option("サイズ", size_opt)
        if ok_size:
            print(f"   • 成功添加尺寸选项: {size_opt}")
        time.sleep(0.3)
    print("✅ [操作 9] 成功配置【サイズ(尺寸)】的所有自定义选项，下方变体表格已自动生成 12 个变体组合！")
    time.sleep(0.5)

    # =========================================================================
    # 步骤 10：在变种表格表头第 4 项下拉框中选择【EAN】
    # =========================================================================
    print("\n⏳ [操作 10] 正在设置变种表格表头第 4 项 ➔ 【EAN】...")
    s10 = engine.select("#variationInfo table thead th:nth-child(4) .ant-select", "EAN")
    if s10:
        print("✅ [操作 10] 成功将变种表格表头第 4 项切换为: EAN！")
    else:
        print("❌ [操作 10] 切换表头第 4 项为 EAN 失败！")
    time.sleep(0.5)

    # =========================================================================
    # 步骤 11：填写指定变体数据行（颜色 dd / 尺寸 tt）
    # =========================================================================
    print("\n⏳ [操作 11] 正在为变体行【dd / tt】填入 SKU、EAN、价格与数量...")
    s11 = engine.fill_variation_row(
        filter_criteria={"颜色": "dd", "尺寸": "tt"},
        row_data={
            "sku": "xxxx",
            "ean": "2222222222222",
            "price": "4000",
            "quantity": "40"
        }
    )
    if s11:
        print("✅ [操作 11] 成功为变体【dd / tt】填入: SKU=xxxx, EAN=2222222222222, 价格=4000, 数量=40！")
    else:
        print("❌ [操作 11] 填写变体【dd / tt】数据失败！")
    time.sleep(0.5)

    # =========================================================================
    # 步骤 12：为变体【dd / tt】上传主图（本地图片）
    # =========================================================================
    print("\n⏳ [操作 12] 正在为变体【dd / tt】上传主图...")
    if os.path.exists(img_black_m):
        s12 = engine.upload_variation_image(
            filter_criteria={"颜色": "dd", "尺寸": "tt"},
            image_path=img_black_m,
            image_type="main",
            upload_mode="local"
        )
        if s12:
            print(f"✅ [操作 12] 成功为变体【dd / tt】上传主图: {img_black_m}！")
        else:
            print("❌ [操作 12] 上传主图失败！")
    else:
        print(f"⚠️ 图片不存在: {img_black_m}")
    time.sleep(0.5)

    # =========================================================================
    # 步骤 13：为变体【dd / tt】上传 Swatch Image（本地图片）
    # =========================================================================
    print("\n⏳ [操作 13] 正在为变体【dd / tt】上传 Swatch Image...")
    if os.path.exists(img_yellow_l):
        s13 = engine.upload_variation_image(
            filter_criteria={"颜色": "dd", "尺寸": "tt"},
            image_path=img_yellow_l,
            image_type="swatch",
            upload_mode="local"
        )
        if s13:
            print(f"✅ [操作 13] 成功为变体【dd / tt】上传 Swatch Image: {img_yellow_l}！")
        else:
            print("❌ [操作 13] 上传 Swatch Image 失败！")
    time.sleep(0.5)

    # =========================================================================
    # 步骤 14：为变体【dd / tt】上传两张附图（本地图片）
    # =========================================================================
    print("\n⏳ [操作 14] 正在为变体【dd / tt】上传 2 张附图...")
    extra_imgs = [p for p in [img_blue_m, img_white_s] if os.path.exists(p)]
    if extra_imgs:
        s14 = engine.upload_variation_image(
            filter_criteria={"颜色": "dd", "尺寸": "tt"},
            image_path=extra_imgs,
            image_type="extra",
            upload_mode="local"
        )
        if s14:
            print(f"✅ [操作 14] 成功为变体【dd / tt】上传 2 张附图！")
        else:
            print("❌ [操作 14] 上传附图失败！")
    time.sleep(0.5)

    # =========================================================================
    # 步骤 15：使用封装方法 set_variation_images 一站式为新变体【红色 / mm】配置全套图片
    # =========================================================================
    print("\n⏳ [操作 15] 正在使用 set_variation_images 为【红色 / mm】一站式配置主图、Swatch 与多张附图...")
    res_bundle = engine.set_variation_images(
        filter_criteria={"颜色": "红色", "尺寸": "mm"},
        main_image=img_black_m if os.path.exists(img_black_m) else None,
        swatch_image=img_yellow_l if os.path.exists(img_yellow_l) else None,
        extra_images=[p for p in [img_blue_m, img_white_s] if os.path.exists(p)]
    )
    if res_bundle.get("all_success"):
        print(f"✅ [操作 15] 成功一站式为【红色 / mm】配置主图、Swatch与2张附图: {res_bundle}！")
    else:
        print(f"❌ [操作 15] 一站式配置图片失败: {res_bundle}")

    print("\n" + "=" * 60)
    print("🎉 【演示完成】所有步骤已在当前有头 Chrome 浏览器中全自动执行完毕！")
    print("=" * 60)


if __name__ == "__main__":
    main()
