#!/usr/bin/env python3
# 核验：同颜色卡片的主图 src 是否一致
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
        main_srcs = {}
        for i in range(headers.count()):
            h = headers.nth(i)
            txt = h.inner_text()
            color = ""
            for seg in txt.replace(chr(10), " ").split():
                if "カラー(颜色):" in seg:
                    color = seg.split(":")[1]
            body = h.locator("xpath=following-sibling::div[1]")
            main_box = body.locator(".p8").nth(0)
            src = main_box.evaluate(
                "el => { const i = el.querySelector('img'); return i ? i.src.slice(-30) : 'none'; }"
            )
            main_srcs.setdefault(color, []).append(f"卡片[{i}]={src}")

        print("各颜色主图分布:")
        ok_all = True
        for color, cards in main_srcs.items():
            srcs = {c.split("=")[1] for c in cards}
            same = len(srcs) == 1
            ok_all = ok_all and same
            print(f"  颜色【{color}】: {', '.join(cards)} {'✅ 一致' if same else '❌ 不一致!'}")
        print("\n结论:", "✅ 同颜色变种共享同一主图，全部正确！" if ok_all else "❌ 存在不一致")

    engine.manager.run_on_browser_thread(check)


if __name__ == "__main__":
    main()
