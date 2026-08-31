#!/usr/bin/env python3
# 步骤检查：查看当前店小秘页面变体图片区状态
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
    page = engine.manager._get_active_page_impl()

    def look():
        print("URL:", page.url)
        print("页面标题:", page.title()[:60])
        headers = page.locator("#variationImage .item-header")
        n = headers.count()
        print(f"\n变体图片卡片数: {n}")
        for i in range(n):
            print(f"  [{i}] {headers.nth(i).inner_text().replace(chr(10), ' | ')[:100]}")

        # 检查每个卡片内的图片状态（主图/Swatch/附图）
        if n > 0:
            body = headers.nth(0).locator("xpath=following-sibling::div[1]")
            boxes = body.locator(".p8")
            print(f"\n卡片[0] 图片块数: {boxes.count()}")
            for j in range(boxes.count()):
                imgs = boxes.nth(j).locator("img")
                label = boxes.nth(j).inner_text().replace("\n", " ")[:40]
                print(f"  图片块[{j}] (img数={imgs.count()}): {label}")

    engine.manager.run_on_browser_thread(look)


if __name__ == "__main__":
    main()
