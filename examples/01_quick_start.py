#!/usr/bin/env python3
"""
示例 1：极速启动或接管 Chrome 浏览器并列出当前所有标签页
"""
import os
import sys

# 确保能正确导入上级 browser_toolkit 模块
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLKIT_DIR = os.path.dirname(CURRENT_DIR)
WORKSPACE_DIR = os.path.dirname(TOOLKIT_DIR)
for p in [WORKSPACE_DIR, TOOLKIT_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from browser_engine import BrowserEngine


def main():
    print("🚀 正在启动 / 连接 Chrome 浏览器 (端口 9222)...")
    engine = BrowserEngine(port=9222)

    ok, msg = engine.launch_browser("https://www.baidu.com")
    print(f"状态: {msg}")

    if not ok:
        print("❌ 启动失败，请检查 Chrome 是否已安装。")
        return

    tabs = engine.get_tabs()
    print(f"\n📑 当前打开的标签页数量: {len(tabs)}")
    for t in tabs:
        print(f"  {t.display_text()}")

    active_tab = engine.get_active_tab_info()
    if active_tab:
        print(f"\n👁 当前前台活动页面标题: {active_tab.title} ({active_tab.url})")


if __name__ == "__main__":
    main()
