@echo off
chcp 65001 >nul
title ERP 中间件 - 服务启动
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [!] 未找到虚拟环境, 请先运行 install.bat
    pause
    exit /b 1
)

:: 防止重复启动
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING 2^>nul') do (
    echo [!] 端口 8000 已被占用 (PID %%a), 服务可能已在运行
    echo     如需重启请先运行 stop.bat
    pause
    exit /b 1
)

echo ============================================
echo   ERP 中间件启动中... (本窗口最小化即可, 勿关闭)
echo   访问: http://127.0.0.1:8000
echo   局域网: http://%computername%:8000 或本机IP:8000
echo ============================================
.venv\Scripts\python.exe -m uvicorn server.app:app --host 0.0.0.0 --port 8000
pause
