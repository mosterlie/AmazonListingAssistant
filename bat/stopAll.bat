@echo off
title AmazonListingAssistant 一键停止 (ERP+图片/Sakura/Chrome/Ollama)

echo ============================================
echo   1/4 停止 ERP+图片 服务 (端口 8000/8765)...
echo ============================================
:: 1) 按命令行精确结束 python 服务进程, 不影响其它 python
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'server\.app|db_agent\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
:: 2) 关闭启动时打开的服务 cmd 窗口 (含一键启动主窗口)
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | Where-Object { $_.CommandLine -match 'startAll\.bat|server\.app|db_agent\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
:: 3) 兜底: 按端口结束残留进程
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000 " ^| findstr "LISTENING"') do taskkill /F /T /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8765 " ^| findstr "LISTENING"') do taskkill /F /T /PID %%a >nul 2>&1
echo [OK] ERP+图片 服务已停止, 启动时打开的 cmd 窗口已同步关闭

echo ============================================
echo   2/4 停止 SakuraFrp...
echo ============================================
taskkill /F /IM SakuraLauncher.exe >nul 2>&1
taskkill /F /IM SakuraFrpService.exe >nul 2>&1
taskkill /F /IM frpc.exe >nul 2>&1
echo [OK] SakuraFrp 已停止

echo ============================================
echo   3/4 停止调试 Chrome (9222, 仅 C:\ChromeDebugUser 实例)...
echo ============================================
powershell -NoProfile -Command "$c = Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | Where-Object {$_.CommandLine -like '*ChromeDebugUser*'}; if ($c) { $c | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } }"
echo [OK] 调试 Chrome 已停止, 不影响日常浏览器

echo ============================================
echo   4/4 停止 Ollama 及其 llama 模型进程...
echo ============================================
taskkill /F /T /IM "ollama app.exe" >nul 2>&1
taskkill /F /T /IM ollama.exe >nul 2>&1
taskkill /F /T /IM ollama_llama_server.exe >nul 2>&1
taskkill /F /T /IM llama-server.exe >nul 2>&1
:: 兜底: 按进程名结束所有 ollama / llama 相关进程 (含新版 Ollama 的 llama-server.exe 推理进程)
powershell -NoProfile -Command "Get-Process | Where-Object { $_.Name -match 'ollama|llama' } | Stop-Process -Force -ErrorAction SilentlyContinue"
echo [OK] Ollama 与 llama 相关进程已全部停止

echo.
echo ============================================
echo   停止完成，正在确认 4 个端口已关闭...
echo ============================================
ping -n 3 127.0.0.1 >nul
call :check_down 8000 "ERP服务"
call :check_down 8765 "图片服务"
call :check_down 9222 "Chrome调试"
call :check_down 11434 "Ollama"
echo.
echo 全部停止执行完毕。
ping -n 6 127.0.0.1 >nul
exit /b 0

:check_down
netstat -aon | findstr ":%1 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 echo [FAIL] 端口 %1 %~2 仍在运行
if not %errorlevel%==0 echo [OK]   端口 %1 %~2 已关闭
exit /b 0
