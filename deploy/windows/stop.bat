@echo off
chcp 65001 >nul
title ERP 中间件 - 服务停止

set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
    set FOUND=1
    echo [OK] 已停止进程 PID %%a
)
if %FOUND% equ 0 echo [i] 端口 8000 无监听进程, 服务本就未运行
pause
