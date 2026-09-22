@echo off
chcp 65001 >nul
title ERP 中间件 - 卸载自启

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] 请右键此脚本, 选择【以管理员身份运行】
    pause
    exit /b 1
)

schtasks /Delete /TN "ERP-Middleware" /F
echo [OK] 开机自启已取消
call "%~dp0stop.bat"
pause
