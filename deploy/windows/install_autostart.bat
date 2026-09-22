@echo off
chcp 65001 >nul
title ERP 中间件 - 注册开机自启
cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] 请右键此脚本, 选择【以管理员身份运行】
    pause
    exit /b 1
)

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo [!] 未找到虚拟环境, 请先运行 install.bat
    pause
    exit /b 1
)

schtasks /Create /TN "ERP-Middleware" /TR "wscript.exe \"%~dp0start_hidden.vbs\"" /SC ONSTART /RU SYSTEM /RL HIGHEST /F
if %errorlevel% equ 0 (
    echo.
    echo [OK] 开机自启已注册 (任务名: ERP-Middleware, 隐藏窗口运行)
    echo      崩溃恢复建议: 服务异常时手动运行 stop.bat 后再执行
    echo      schtasks /Run /TN "ERP-Middleware"
    schtasks /Run /TN "ERP-Middleware" >nul 2>&1
    echo [OK] 已立即启动一次
) else (
    echo [!] 注册失败, 请检查是否以管理员运行
)
pause
