@echo off
chcp 65001 >nul
cd /d %~dp0

echo ============================================
echo   提示: 本地图片服务已合并进 ERP 服务
echo ============================================
echo.
echo  原 db_agent.py (端口 8765) 的接口已内嵌到 ERP 服务中:
echo    GET  /ping             连接测试
echo    GET  /file             商品图片下载
echo    POST /query            只读查询
echo    POST /execute          写操作
echo.
echo  因此无需再单独启动本脚本, 也无需为 8765 单独开隧道。
echo.
echo  桌面上件助手连接方式 (远程模式):
echo    主机: 运行 ERP 服务的机器 IP 或 SakuraFrp 隧道域名
echo    端口: ERP 服务端口 8000 (或隧道对外端口)
echo    令牌: 系统管理页「桌面上件助手远程通道令牌」(默认 erp2024)
echo.
echo  ERP 服务启动: python -m server.app  或  运行「bat\startAll.bat」
echo.
pause
exit /b 0
