#!/usr/bin/env python3
# 检查主图框实际状态：图片是否实际已上传
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
        headers = page.locator("#variationImage .item-header")
        h = headers.nth(0)
        print("卡片[0]:", h.inner_text().replace(chr(10), " | ")[:80])
        body = h.locator("xpath=following-sibling::div[1]")
        boxes = body.locator(".p8")
        for j in range(boxes.count()):
            box = boxes.nth(j)
            imgs = box.locator("img")
            label = box.inner_text().replace("\n", " ")[:50]
            # 输出每张 img 的 src 判断是占位图还是真实上传图
            srcs = box.evaluate("el => Array.from(el.querySelectorAll('img')).map(i => i.src.slice(-60))")
            print(f"图片块[{j}] ({label})")
            for s in srcs:
                print(f"    img src: ...{s}")

    engine.manager.run_on_browser_thread(look)


if __name__ == "__main__":
    main()
