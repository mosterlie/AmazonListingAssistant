#!/usr/bin/env python3
# 步骤1+2 连续执行：上传第一个 SKU 主图+附图，然后将附图应用到所有变体
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
FILTER = {"颜色": "11", "尺寸": "aa"}
MAIN_IMG = os.path.join(UPLOADS, "sku1.jpg")
EXTRA_IMGS = [os.path.join(UPLOADS, f"PT{i:02d}.jpg") for i in [1, 2, 3, 5, 6, 7, 8]]


def main():
    for f in [MAIN_IMG] + EXTRA_IMGS:
        if not os.path.exists(f):
            print("❌ 文件不存在:", f)
            return

    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect(activate=False)
    if not ok:
        print("❌ 连接失败:", msg)
        return

    # ===== 步骤 1: 上传第一个 SKU 主图 + 附图 =====
    print("【步骤1】上传第一个 SKU (カラー: 11 / サイズ: aa) 主图与附图 ...")
    print("  ① 主图 sku1.jpg ...")
    main_ok = engine.upload_variation_image(
        filter_criteria=FILTER, image_path=MAIN_IMG, image_type="main", timeout_ms=30000
    )
    print(f"     主图: {'✅ 完成并确认渲染' if main_ok else '❌ 失败/超时'}")

    print(f"  ② 附图 PT01~PT08 共 {len(EXTRA_IMGS)} 张 ...")
    extra_ok = engine.upload_variation_image(
        filter_criteria=FILTER, image_path=EXTRA_IMGS, image_type="extra", timeout_ms=60000
    )
    print(f"     附图: {'✅ 完成并确认渲染' if extra_ok else '❌ 失败/超时'}")

    if not (main_ok and extra_ok):
        print("⚠️ 上传未全部成功，中止后续应用")
        return

    # ===== 步骤 2: 附图应用到所有变体 =====
    print("\n【步骤2】将第一个 SKU 的附图应用到 ➔ 附图-所有变体 ...")
    apply_ok = engine.apply_variation_image(
        filter_criteria=FILTER, apply_type="extra_all", timeout_ms=15000
    )
    print(f"   应用: {'✅ 已将附图应用至所有变体' if apply_ok else '❌ 应用失败'}")

    print("\n=== 执行完毕 ===")
    print(f"主图上传: {'✅' if main_ok else '❌'}  附图上传: {'✅' if extra_ok else '❌'}  附图应用所有变体: {'✅' if apply_ok else '❌'}")


if __name__ == "__main__":
    main()
