#!/usr/bin/env python3
# 最终验证：三连应用模拟真实发布流程
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
from core.form_operator import FormOperator


def main():
    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect(activate=False)
    if not ok:
        print("❌ 连接失败:", msg)
        return
    page = engine.manager._get_active_page_impl()

    def run():
        op = FormOperator(page)
        r1 = op.apply_variation_image({"颜色": "一方向囲い"}, "extra_all", timeout_ms=12000)
        print("1. 附图-所有变种 (卡片0):", "✅" if r1 else "❌")
        r2 = op.apply_variation_image({"颜色": "一方向囲い"}, "main_color", timeout_ms=12000)
        print("2. 主图-同カラー (卡片0):", "✅" if r2 else "❌")
        r3 = op.apply_variation_image({"颜色": "三方囲い"}, "main_color", timeout_ms=12000)
        print("3. 主图-同カラー (卡片1):", "✅" if r3 else "❌")
        r4 = op.apply_variation_image({"颜色": "一方向囲い"}, "main_color", timeout_ms=12000)
        print("4. 主图-同カラー (卡片0 再来一次):", "✅" if r4 else "❌")

    engine.manager.run_on_browser_thread(run)


if __name__ == "__main__":
    main()
