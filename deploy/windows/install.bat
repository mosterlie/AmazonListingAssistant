@echo off
chcp 65001 >nul
title ERP 中间件 - 环境安装
cd /d "%~dp0"

echo ============================================
echo   ERP 中间件 Windows 环境安装
echo   项目目录: %cd%
echo ============================================
echo.

:: 0. 检查管理员权限 (防火墙/计划任务需要)
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] 请右键此脚本, 选择【以管理员身份运行】
    pause
    exit /b 1
)

:: 1. 检查 Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] 未检测到 Python, 请先安装 Python 3.10+ 并勾选 "Add to PATH"
    echo     下载: https://www.python.org/downloads/
    pause
    exit /b 1
)
python --version
echo.

:: 2. 创建虚拟环境 (已存在则跳过)
if not exist ".venv\Scripts\python.exe" (
    echo [2/5] 创建虚拟环境 .venv ...
    python -m venv .venv
) else (
    echo [2/5] 虚拟环境已存在, 跳过
)
echo.

:: 3. 安装依赖
echo [3/5] 安装 Python 依赖 (首次约 3-5 分钟) ...
.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --upgrade pip -q
if %errorlevel% neq 0 (
    echo [!] 依赖安装失败, 请检查网络后重跑本脚本
    pause
    exit /b 1
)
echo       依赖安装完成
echo.

:: 4. 安装 Playwright Chromium (文档采集用)
echo [4/5] 安装 Chromium 无头浏览器 (约 150MB, 请耐心等待) ...
.venv\Scripts\python.exe -m playwright install chromium
if %errorlevel% neq 0 (
    echo [!] Chromium 安装失败, 文档采集功能不可用 (其余功能不受影响)
)
echo.

:: 5. 防火墙放行 8000 端口 (局域网访问)
echo [5/5] 防火墙放行 8000 端口 ...
netsh advfirewall firewall delete rule name="ERP-Middleware-8000" >nul 2>&1
netsh advfirewall firewall add rule name="ERP-Middleware-8000" dir=in action=allow protocol=TCP localport=8000 >nul
if %errorlevel% equ 0 (
    echo       防火墙规则已添加
) else (
    echo [!] 防火墙规则添加失败, 局域网其他设备可能无法访问
)
echo.

echo ============================================
echo   安装完成! 接下来:
echo   1. 双击 start.bat 启动服务 (测试)
echo   2. 浏览器访问 http://127.0.0.1:8000
echo   3. 正常后运行 install_autostart.bat 设为开机自启
echo ============================================
pause
