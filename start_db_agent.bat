@echo off
chcp 65001 >nul
title ERP 数据库代理 (db_agent)
cd /d %~dp0
echo ============================================
echo  ERP 商品数据库代理服务 (供远程桌面上件助手连接)
echo  远程机器请填本机 IP + 端口 8765
echo ============================================
python db_agent.py --port 8765 --token erp2024
pause
