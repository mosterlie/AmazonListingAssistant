#!/usr/bin/env python3
"""
示例 3：指定任意目标网址直达并进行高精度 DOM 结构化解析
"""
import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLKIT_DIR = os.path.dirname(CURRENT_DIR)
WORKSPACE_DIR = os.path.dirname(TOOLKIT_DIR)
for p in [WORKSPACE_DIR, TOOLKIT_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from browser_engine import BrowserEngine


def main():
    target_url = sys.argv[1] if len(sys.argv) > 1 else "https://news.ycombinator.com"
    print(f"🚀 正在打开并接管目标网址: {target_url}")

    engine = BrowserEngine(port=9222)
    ok, msg = engine.launch_browser()
    if not ok:
        print(f"❌ 启动或接管浏览器失败: {msg}")
        return

    # 打开或切换到目标页面
    page = engine.open_or_focus_url(target_url)
    if not page:
        print("❌ 打开目标页面失败！")
        return

    print(f"\n🎯 正在高精度解析页面 DOM...")
    output_file = os.path.join(CURRENT_DIR, "output_specified_url_dom.json")
    dom_data = engine.parse_and_export_json(output_file, page=page)

    engine.print_dom_summary(dom_data)
    print(f"✅ 完整 DOM 数据已保存至: {output_file}")


if __name__ == "__main__":
    main()
