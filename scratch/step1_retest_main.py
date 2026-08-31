#!/usr/bin/env python3
# 重传第一个 SKU 的主图，验证 src 集合检测不再误报超时
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

UPLOADS = os.path.join(PROJECT_DIR, "data", "uploads")
FILTER = {"颜色": "11", "尺寸": "aa"}
MAIN_IMG = os.path.join(UPLOADS, "sku1.jpg")


def main():
    if not os.path.exists(MAIN_IMG):
        print("❌ 文件不存在:", MAIN_IMG)
        return

    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect(activate=False)
    if not ok:
        print("❌ 连接失败:", msg)
        return

    print("① 重新上传第一个 SKU 主图: sku1.jpg ...")
    t0 = time.time()
    main_ok = engine.upload_variation_image(
        filter_criteria=FILTER,
        image_path=MAIN_IMG,
        image_type="main",
        timeout_ms=30000
    )
    elapsed = time.time() - t0
    print(f"   主图上传: {'✅ 完成并确认渲染' if main_ok else '❌ 失败/超时'} (耗时 {elapsed:.1f}s)")


if __name__ == "__main__":
    main()
