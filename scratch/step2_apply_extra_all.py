#!/usr/bin/env python3
# 步骤2：将第一个 SKU (カラー: 11 / サイズ: aa) 的附图应用到所有变体
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

FILTER = {"颜色": "11", "尺寸": "aa"}


def main():
    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect(activate=False)
    if not ok:
        print("❌ 连接失败:", msg)
        return

    print("执行: 第一个 SKU 附图 ➔ 图片应用到 ➔ 附图-所有变体 ...")
    res = engine.apply_variation_image(
        filter_criteria=FILTER,
        apply_type="extra_all",
        timeout_ms=15000
    )
    print(f"结果: {'✅ 已将附图应用至所有变体' if res else '❌ 应用失败'}")


if __name__ == "__main__":
    main()
