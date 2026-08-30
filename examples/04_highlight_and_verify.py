#!/usr/bin/env python3
"""
示例 4：DOM 视觉核验工具 —— 在当前打开的浏览器页面上实时绘制高亮框与编号浮标，1秒直观核验 100% 捕获率
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
    print("🔍 正在连接 Chrome 浏览器...")
    engine = BrowserEngine(port=9222)
    ok, msg = engine.connect(activate=False)
    if not ok:
        print(f"❌ 连接失败: {msg}")
        return

    active_tab = engine.get_active_tab_info()
    tab_title = active_tab.title if active_tab else "未知"
    print(f"\n🎯 正在为前台页面 【{tab_title}】 注入视觉核验透视层...")

    # 1. 实时在浏览器页面上绘制高亮与编号徽标
    res = engine.highlight_and_verify()

    print("\n" + "=" * 65)
    print("🎉 【DOM 视觉核验层已成功渲染至浏览器页面！】")
    print(f"  🟢 绿色高亮框标记表单输入项 : {res.get('highlighted_fields')} 个")
    print(f"  🔵 蓝色高亮框标记操作按钮   : {res.get('highlighted_buttons')} 个")
    print("=" * 65)
    print("\n👉 请切回 Chrome 浏览器查看：")
    print("   1. 页面上所有被捕获的输入框都会带有【绿色边框】和【字段序号标签】；")
    print("   2. 页面右上角会出现【DOM 视觉核验看板】；")
    print("   3. 如需退出高亮模式，点击看板中的【一键清除高亮】按钮即可。")


if __name__ == "__main__":
    main()
