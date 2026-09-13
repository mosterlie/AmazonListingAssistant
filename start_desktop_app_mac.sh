#!/bin/bash
# =======================================================
# ERP 桌面上件助手 (店小秘自动化) - macOS 一键启动脚本
# =======================================================
cd "$(dirname "$0")"

# 检查 Python3
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 python3，请先安装 Python 3.10+ 环境！"
    exit 1
fi

echo "🚀 正在启动 ERP 桌面上件助手 (macOS)..."
python3 desktop_app.py
