#!/usr/bin/env python3
"""
示例 2：一键高精度解析当前浏览器中正在浏览的前台页面，并导出完整 DOM 字典
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
    print("🔍 正在连接当前打开的 Chrome 浏览器...")
    engine = BrowserEngine(port=9222)

    ok, msg = engine.connect(activate=False)
    if not ok:
        print(f"⚠️ {msg}，正在尝试自动启动浏览器...")
        ok, msg = engine.launch_browser()
        if not ok:
            print("❌ 无法连接或启动浏览器，请确认已安装 Chrome！")
            return

    # 1. 深度扫描当前前台页面 DOM、表单、按钮、表格与结构化元数据
    print("⏳ 正在深度扫描全页 DOM、表单、按钮、表格与结构化元数据...")
    output_file = os.path.join(CURRENT_DIR, "output_active_page_dom.json")
    dom_data = engine.parse_and_export_json(output_file)

    # 2. 打印可视化摘要报告
    engine.print_dom_summary(dom_data)

    print(f"✅ 完整高精度 DOM 结构字典已保存至: {output_file}")


if __name__ == "__main__":
    main()
