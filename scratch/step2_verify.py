#!/usr/bin/env python3
# 验证全部卡片的附图同步结果
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

    def check():
        headers = page.locator("#variationImage .item-header")
        n = headers.count()
        print(f"卡片总数: {n}")
        for i in range(n):
            h = headers.nth(i)
            body = h.locator("xpath=following-sibling::div[1]")
            boxes = body.locator(".p8")
            info = []
            for j in range(boxes.count()):
                box = boxes.nth(j)
                # 统计真实图片数（排除占位图）
                real = box.evaluate(
                    "el => Array.from(el.querySelectorAll('img')).filter(i => !/addimg|kong-|\\/assets\\//i.test(i.src)).length"
                )
                labels = ["主图", "Swatch", "附图"]
                info.append(f"{labels[j] if j < 3 else j}={real}张")
            name = h.inner_text().replace(chr(10), " ").split("图片应用到")[0].strip()[:50]
            print(f"  [{i}] {name} => {', '.join(info)}")

    engine.manager.run_on_browser_thread(check)


if __name__ == "__main__":
    main()
