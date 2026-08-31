#!/usr/bin/env python3
# 完整流程重跑：步骤1~5
#   1. 第一个 SKU (颜色11/尺寸aa) 上传主图+附图（等待渲染完成）
#   2. 附图 ➔ 应用「附图-所有变体」
#   3. 颜色11 主图 ➔ 应用「主图-同カラー(颜色)的变种」
#   4. 颜色22 上传主图 sku2.jpg ➔ 应用「主图-同カラー」
#   5. 颜色33 上传主图 12312321.jpg ➔ 应用「主图-同カラー」
import sys
import os

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

UPLOADS = os.path.join(PROJECT_DIR, "data", "uploads")
FIRST_FILTER = {"颜色": "11", "尺寸": "aa"}
EXTRA_IMGS = [os.path.join(UPLOADS, f"PT{i:02d}.jpg") for i in [1, 2, 3, 5, 6, 7, 8]]
COLOR_MAIN_PLAN = [
    ("11", os.path.join(UPLOADS, "sku1.jpg")),
    ("22", os.path.join(UPLOADS, "sku2.jpg")),
    ("33", os.path.join(UPLOADS, "12312321.jpg")),
]


def main():
    for _, f in COLOR_MAIN_PLAN:
        if not os.path.exists(f):
            print("❌ 主图文件不存在:", f)
            return
    for f in EXTRA_IMGS:
        if not os.path.exists(f):
            print("❌ 附图文件不存在:", f)
            return

    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect(activate=False)
    if not ok:
        print("❌ 连接失败:", msg)
        return

    results = {}

    # ===== 步骤 1: 第一个 SKU 上传主图 + 附图 =====
    print("【步骤1】上传第一个 SKU (カラー: 11 / サイズ: aa) 主图与附图 ...")
    main_ok = engine.upload_variation_image(
        filter_criteria=FIRST_FILTER,
        image_path=COLOR_MAIN_PLAN[0][1],
        image_type="main",
        timeout_ms=30000
    )
    print(f"   主图 sku1.jpg: {'✅ 完成并确认渲染' if main_ok else '❌ 失败/超时'}")
    extra_ok = engine.upload_variation_image(
        filter_criteria=FIRST_FILTER,
        image_path=EXTRA_IMGS,
        image_type="extra",
        timeout_ms=60000
    )
    print(f"   附图 {len(EXTRA_IMGS)} 张: {'✅ 完成并确认渲染' if extra_ok else '❌ 失败/超时'}")
    results["1_上传第一个SKU"] = main_ok and extra_ok

    # ===== 步骤 2: 附图 ➔ 所有变体 =====
    if extra_ok:
        print("\n【步骤2】附图 ➔ 图片应用到 ➔ 附图-所有变体 ...")
        apply_extra = engine.apply_variation_image(
            filter_criteria=FIRST_FILTER, apply_type="extra_all", timeout_ms=15000
        )
        print(f"   应用: {'✅ 已应用至所有变体' if apply_extra else '❌ 失败'}")
        results["2_附图应用所有变体"] = apply_extra
    else:
        results["2_附图应用所有变体"] = False

    # ===== 步骤 3/4/5: 各颜色主图上传 + 应用同カラー =====
    for idx, (color, main_img) in enumerate(COLOR_MAIN_PLAN, start=3):
        filter_crit = {"颜色": color, "尺寸": "aa"}
        print(f"\n【步骤{idx}】颜色【{color}】主图 {os.path.basename(main_img)} ➔ 同カラー应用 ...")
        up_ok = engine.upload_variation_image(
            filter_criteria=filter_crit, image_path=main_img,
            image_type="main", timeout_ms=30000
        )
        print(f"   上传: {'✅ 完成并确认渲染' if up_ok else '❌ 失败/超时'}")
        if not up_ok:
            results[f"{idx}_颜色{color}主图"] = False
            continue
        ap_ok = engine.apply_variation_image(
            filter_criteria=filter_crit, apply_type="main_color", timeout_ms=15000
        )
        print(f"   应用同カラー: {'✅ 已应用至同颜色变种' if ap_ok else '❌ 失败'}")
        results[f"{idx}_颜色{color}主图"] = ap_ok

    print("\n=== 全流程执行汇总 ===")
    for k, v in results.items():
        print(f"  {k}: {'✅' if v else '❌'}")
    print("总体:", "✅ 全部成功" if all(results.values()) else "❌ 存在失败项")


if __name__ == "__main__":
    main()
