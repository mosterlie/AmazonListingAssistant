@echo off
set "USER_DATA=D:\ChromeDebugUser"
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
    echo [ERROR] Google Chrome not found! Please make sure Chrome is installed.
    pause
    exit /b 1
)

echo Starting Chrome with remote debugging on port 9222...
start "" "%CHROME_PATH%" --remote-debugging-port=9222 --user-data-dir="%USER_DATA%" --no-first-run --no-default-browser-check "https://www.dianxiaomi.com/web/amazon/add"

echo Chrome launched successfully on port 9222!
