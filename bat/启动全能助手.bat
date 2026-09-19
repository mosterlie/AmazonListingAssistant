@echo off
chcp 65001 >nul
title ERP 全能助手 (商品上件 + 广告投放)
cd /d "%~dp0.."
echo ============================================
echo   启动 ERP 全能助手 (上件 + 广告投放)...
echo ============================================
python unified_app.py
if errorlevel 1 (
    echo.
    echo [ERROR] 启动失败, 请检查上方输出 (依赖安装: pip install -r requirements.txt)
    pause
)
