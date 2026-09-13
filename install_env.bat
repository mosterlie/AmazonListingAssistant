@echo off
chcp 65001 >nul
title AmazonListingAssistant - 环境一键安装配置
cd /d "%~dp0"

echo =======================================================
echo   AmazonListingAssistant 运行环境安装向导 (Windows)
echo =======================================================
echo.

:: 1. 检查 Python 是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10 或更高版本！
    echo 重要提示：安装 Python 时请务必勾选 "Add python.exe to PATH"（添加到系统环境变量）。
    echo 官方下载地址: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version') do set PYTHON_VER=%%i
echo [1/3] 已检测到 Python: %PYTHON_VER%

:: 2. 安装 Python 依赖包 (默认使用国内清华源加速)
echo.
echo [2/3] 正在安装项目所需的 Python 依赖库...
python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo [重试] 清华源安装出现异常，尝试使用官方源重试...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络连接或手动执行 pip install -r requirements.txt！
        pause
        exit /b 1
    )
)
echo [OK] Python 依赖安装完成！

:: 3. 安装 Playwright Chromium 驱动
echo.
echo [3/3] 正在安装 Playwright 驱动组件...
python -m playwright install chromium
if errorlevel 1 (
    echo [提示] Playwright chromium 驱动下载跳过或有警告（如果本机已安装 Chrome 并使用 start_all.bat 接管模式，不影响正常使用）。
) else (
    echo [OK] Playwright 组件就绪！
)

echo.
echo =======================================================
echo   部署准备就绪！
echo =======================================================
echo  使用说明：
echo  1. 请确保系统已安装 Google Chrome 浏览器；
echo  2. 双击运行 start_all.bat 即可一键启动服务并在 Chrome 中打开；
echo  3. 在弹出的 Chrome (9222端口) 中登录一次店小秘 ERP 保持登录态；
echo  4. 默认登录账号：admin ，密码：admin
echo =======================================================
echo.
pause
