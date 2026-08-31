#!/usr/bin/env python3
# 步骤1：给第一个 SKU (カラー: 11 / サイズ: aa) 上传主图 + 附图
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

# 第一个 SKU: カラー(颜色): 11 / サイズ(尺寸): aa
FILTER = {"颜色": "11", "尺寸": "aa"}
MAIN_IMG = os.path.join(UPLOADS, "sku1.jpg")       # SKU 主图
EXTRA_IMGS = [os.path.join(UPLOADS, f"PT{i:02d}.jpg") for i in [1, 2, 3, 5, 6, 7, 8]]  # PT04 不存在，用其余 7 张


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

    # 1. 上传主图（内部会等待图片渲染完成）
    print("① 上传第一个 SKU 主图: sku1.jpg ...")
    main_ok = engine.upload_variation_image(
        filter_criteria=FILTER,
        image_path=MAIN_IMG,
        image_type="main",
        timeout_ms=30000
    )
    print(f"   主图上传: {'✅ 完成并确认渲染' if main_ok else '❌ 失败/超时'}")

    # 2. 上传附图（PT01~PT08，8 张一次性多选）
    print(f"② 上传第一个 SKU 附图: PT01~PT08 ({len(EXTRA_IMGS)} 张) ...")
    extra_ok = engine.upload_variation_image(
        filter_criteria=FILTER,
        image_path=EXTRA_IMGS,
        image_type="extra",
        timeout_ms=60000
    )
    print(f"   附图上传: {'✅ 完成并确认渲染' if extra_ok else '❌ 失败/超时'}")

    print("\n=== 第一步执行完毕 ===")
    print(f"主图: {'✅' if main_ok else '❌'}  附图: {'✅' if extra_ok else '❌'}")


if __name__ == "__main__":
    main()
