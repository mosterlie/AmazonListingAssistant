#!/usr/bin/env python3
# 补救：颜色11 主图已在卡片[0]，只需执行「主图-同カラー(颜色)的变种」应用
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


def main():
    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect(activate=False)
    if not ok:
        print("❌ 连接失败:", msg)
        return
    print("补救执行: 颜色11 主图 ➔ 应用「主图-同カラー(颜色)的变种」...")
    res = engine.apply_variation_image(
        filter_criteria={"颜色": "11", "尺寸": "aa"},
        apply_type="main_color",
        timeout_ms=15000
    )
    print(f"结果: {'✅ 已应用至颜色11的所有变种' if res else '❌ 应用失败'}")


if __name__ == "__main__":
    main()
