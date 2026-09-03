@echo off
chcp 65001 >nul
title AmazonListingAssistant 一键启动

echo ============================================
echo   1/3 启动 SakuraFrp 启动器...
echo ============================================
set "SAKURA_PATH=C:\Program Files\SakuraFrpLauncher\SakuraLauncher.exe"
if exist "%SAKURA_PATH%" (
    start "" "%SAKURA_PATH%"
    echo [OK] SakuraFrp 已启动
) else (
    echo [WARN] 未找到 %SAKURA_PATH%，请检查安装路径
)
timeout /t 2 /nobreak >nul

echo ============================================
echo   2/3 启动 Chrome 调试端口 9222...
echo ============================================
set "USER_DATA=C:\ChromeDebugUser"
if not exist "%USER_DATA%" mkdir "%USER_DATA%"

set "CHROME_PATH="
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    set "CHROME_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe"
)
if not defined CHROME_PATH (
    if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
        set "CHROME_PATH=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    )
)
if not defined CHROME_PATH (
    if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" (
        set "CHROME_PATH=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
    )
)

if not defined CHROME_PATH (
    echo [ERROR] 未找到 Google Chrome，请确认已安装！
) else (
    start "" "%CHROME_PATH%" --remote-debugging-port=9222 --user-data-dir="%USER_DATA%" --no-first-run --no-default-browser-check
    echo [OK] Chrome 已启动（调试端口 9222，用户数据: C:\ChromeDebugUser）
)
timeout /t 2 /nobreak >nul

echo ============================================
echo   3/3 启动 AmazonListingAssistant 项目...
echo ============================================
cd /d "D:\myCoding\AmazonListingAssistant"
start "AmazonListingAssistant" cmd /k "python -m server.app"
echo [OK] 项目已启动: http://127.0.0.1:8000

echo.
echo 全部启动完成！等待 5 秒后用 9222 端口浏览器打开项目页面...
timeout /t 5 /nobreak >nul
if defined CHROME_PATH (
    start "" "%CHROME_PATH%" --user-data-dir="%USER_DATA%" "http://127.0.0.1:8000"
) else (
    start "" "http://127.0.0.1:8000"
)
exit /b 0
