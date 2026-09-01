import sys
import os
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
from core.form_operator import FormOperator

def test_optimized_flow():
    print("=" * 80)
    print("🚀 【优化后的 SKU 变体图片上传策略测试】")
    print(" 1. 先上传第 1 个 SKU 的附图")
    print(" 2. 将第 1 个附图批量应用到所有 SKU (extra_all)")
    print(" 3. 检查第 2 个 SKU 的附图是否已上传 (确认批量应用生效)")
    print(" 4. 从第 1 个 SKU 开始循环检查主图是否为空：上传主图 -> 批量应用到同颜色/尺寸 -> 检查结果 -> 直到所有 SKU 完毕")
    print("=" * 80, flush=True)

    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect(activate=False)
    if not ok:
        print(f"❌ 连接失败: {msg}")
        return

    def run():
        page = engine.manager._get_active_page_impl()
        form = FormOperator(page)
        print(f"📄 当前页面: {page.url}", flush=True)

        if "dianxiaomi.com/web/amazon/add" not in page.url:
            print("ℹ️ 当前页面不是店小秘添加页面，请确认已打开店小秘草稿/新建页面。")
            return

        headers_count = page.locator("#variationImage .item-header").count()
        print(f"✅ 当前变体卡片数量: {headers_count}", flush=True)
        if headers_count == 0:
            print("⚠️ 未找到变体卡片，跳过。")
            return

        test_imgs_dir = os.path.join(PROJECT_DIR, "test_images")
        extra_imgs = [
            os.path.join(test_imgs_dir, "blue_s.jpg"),
            os.path.join(test_imgs_dir, "yellow_s.jpg")
        ]
        color_imgs = {
            "11": os.path.join(test_imgs_dir, "black_s.jpg"),
            "22": os.path.join(test_imgs_dir, "white_s.jpg")
        }

        # 1. 提取第 1 个变体卡片头部信息
        first_header = page.locator("#variationImage .item-header").first
        first_text = first_header.inner_text().replace("\n", " ")
        print(f"\n[步骤 1/4] 正在为第 1 个 SKU【{first_text}】上传附图 ({len(extra_imgs)} 张)...", flush=True)
        
        # 查找第 1 个卡片属性
        first_crit = {}
        if "11" in first_text:
            first_crit["颜色"] = "11"
        if "aa" in first_text:
            first_crit["尺寸"] = "aa"

        # 1. 上传附图
        up_extra_ok = form.upload_variation_image(
            filter_criteria=first_crit,
            image_path=extra_imgs,
            image_type="extra",
            timeout_ms=30000
        )
        print(f"  ➔ 第 1 个 SKU 附图上传结果: {'✅ 成功' if up_extra_ok else '❌ 失败'}", flush=True)

        # 2 & 3. 批量应用附图并检查第 2 个 SKU
        print("\n[步骤 2/4 & 3/4] 正在执行【附图 ➔ 所有变体】批量应用并核验第 2 个 SKU...", flush=True)
        apply_extra_ok = form.apply_variation_image(
            filter_criteria=first_crit,
            apply_type="extra_all",
            timeout_ms=15000,
            verify_success=True,
            log_callback=print
        )
        print(f"  ➔ 附图批量应用核验结果: {'✅ 成功' if apply_extra_ok else '❌ 失败'}", flush=True)

        # 4. 从第 1 个到最后逐个遍历 SKU 主图状态
        print(f"\n[步骤 4/4] 正在逐个遍历所有 SKU (共 {headers_count} 个) 主图状态并上传/批量应用...", flush=True)
        for card_idx in range(headers_count):
            h = page.locator("#variationImage .item-header").nth(card_idx)
            c_text = h.inner_text().replace("\n", " ")

            crit = {}
            if "11" in c_text:
                c_col = "11"
                crit["颜色"] = "11"
            elif "22" in c_text:
                c_col = "22"
                crit["颜色"] = "22"
            else:
                c_col = "11"

            if "aa" in c_text:
                c_sz = "aa"
                crit["尺寸"] = "aa"
            elif "bb" in c_text:
                c_sz = "bb"
                crit["尺寸"] = "bb"
            else:
                c_sz = ""

            print(f"\n   -------------------------------------------------------------")
            print(f"   📌 [SKU {card_idx + 1}/{headers_count}] 变体属性: 【颜色={c_col} / 尺寸={c_sz}】", flush=True)

            # 检查该卡片主图是否已存在
            is_up = form.is_variation_card_main_uploaded(filter_criteria=crit, card_idx=card_idx)
            if is_up:
                print(f"      ➔ 当前主图状态: 【已上传】（已存在/同颜色批量应用已同步）➔ 直接跳过，处理下一个 SKU", flush=True)
                continue
            else:
                print(f"      ➔ 当前主图状态: 【未上传】➔ 准备执行上传...", flush=True)

            main_img_file = color_imgs.get(c_col, os.path.join(test_imgs_dir, "black_s.jpg"))
            print(f"      ➔ 执行上传: 正在上传对应【颜色: {c_col}】的主图文件: {os.path.basename(main_img_file)} ...", flush=True)
            up_m_ok = form.upload_variation_image(crit, main_img_file, "main", timeout_ms=30000)
            if up_m_ok:
                print(f"      ➔ 上传后的结果: ✅ 上传成功", flush=True)
                print(f"      ➔ 执行批量应用: 正在批量应用【主图 ➔ 同颜色变种】(不检查批量结果)...", flush=True)
                form.apply_variation_image(crit, "main_color", timeout_ms=10000, verify_success=False, log_callback=print)
                print(f"      ➔ 批量应用已执行完毕 ➔ 进行下一条处理", flush=True)
            else:
                print(f"      ➔ 上传后的结果: ❌ 上传失败（未通过校验）➔ 进行下一条处理", flush=True)

        # 5. 最终体检报告
        summary = form.verify_all_variation_images_summary()
        print("\n" + "=" * 60)
        print(f"📊 最终变体图片装配统计: 总数 {summary['total']} 个，主图 {summary['withMain']}/{summary['total']}，附图 {summary['withExtra']}/{summary['total']}")
        print("=" * 60, flush=True)

    engine.manager.run_on_browser_thread(run)

if __name__ == "__main__":
    test_optimized_flow()
