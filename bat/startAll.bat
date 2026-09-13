@echo off
title AmazonListingAssistant 一键启动 (ERP+图片/Sakura/Ollama)

set "PROJ=C:\Users\li'l'y\OneDrive - University of Macau\Desktop\mypro\AmazonListingAssistant"
set "SAKURA_PATH=C:\Program Files\SakuraFrpLauncher\SakuraLauncher.exe"
set "OLLAMA_PATH=%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
set "OLLAMA_CLI=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"

echo ============================================
echo   1/3 启动 ERP+图片 服务 (后台隐藏运行, 端口 8000/8765)...
echo ============================================
if not exist "%PROJ%\server\app.py" (
    echo [ERROR] 未找到项目: %PROJ%
) else (
    powershell -NoProfile -Command "Start-Process cmd -ArgumentList '/k chcp 65001 >nul && title ERP+图片服务 8000/8765 && start /b python -m server.app && start /b python db_agent.py --port 8765 --token erp2024' -WindowStyle Hidden -WorkingDirectory \"%PROJ%\""
    echo [OK] ERP+图片 服务已后台启动, 窗口已隐藏: http://127.0.0.1:8000 与 http://127.0.0.1:8765
)
ping -n 3 127.0.0.1 >nul

echo ============================================
echo   2/3 启动 SakuraFrp 客户端 (后台隐藏运行)...
echo ============================================
if exist "%SAKURA_PATH%" (
    powershell -NoProfile -Command "Start-Process -FilePath \"%SAKURA_PATH%\" -WindowStyle Hidden"
    echo [OK] SakuraFrp 已后台启动
) else (
    echo [WARN] 未找到 %SAKURA_PATH%，请检查安装路径
)
ping -n 3 127.0.0.1 >nul
powershell -NoProfile -Command "Start-Sleep 2; Add-Type -Name W -Namespace N -MemberDefinition '[DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr h, int c);'; $p = Get-Process SakuraLauncher -ErrorAction SilentlyContinue; if ($p -and $p.MainWindowHandle -ne 0) { [void][N.W]::ShowWindow($p.MainWindowHandle, 0) }"
echo [OK] SakuraFrp 窗口已隐藏

echo ============================================
echo   3/3 启动 Ollama (后台隐藏运行)...
echo ============================================
if not exist "%OLLAMA_PATH%" (
    echo [WARN] 未找到 %OLLAMA_PATH%，请检查安装路径。
    goto ollama_done
)
powershell -NoProfile -Command "Start-Process -FilePath \"%OLLAMA_PATH%\" -WindowStyle Hidden"
ping -n 6 127.0.0.1 >nul
curl -s -o nul -m 2 http://127.0.0.1:11434/ >nul 2>&1
if %errorlevel%==0 (
    goto ollama_hide
)
echo [INFO] Ollama 图形界面未及时响应, 改用后台服务模式...
start "Ollama服务" /MIN "%OLLAMA_CLI%" serve
ping -n 4 127.0.0.1 >nul
curl -s -o nul -m 2 http://127.0.0.1:11434/ >nul 2>&1
if %errorlevel%==0 echo [OK] Ollama 后台已启动 (端口 11434)
if not %errorlevel%==0 echo [WARN] Ollama 端口 11434 未就绪, 请手动启动 Ollama
:ollama_hide
powershell -NoProfile -Command "Start-Sleep 2; Add-Type -Name W2 -Namespace N2 -MemberDefinition '[DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr h, int c);'; Get-Process | Where-Object { $_.Name -like 'ollama*' } | ForEach-Object { if ($_.MainWindowHandle -ne 0) { [void][N2.W2]::ShowWindow($_.MainWindowHandle, 0) } }"
echo [OK] Ollama 已启动, 窗口已隐藏
:ollama_done

echo.
echo ============================================
echo   启动完成，正在检查 3 个端口...
echo ============================================
ping -n 3 127.0.0.1 >nul
call :check_port 8000 "ERP服务"
call :check_port 8765 "图片服务"
call :check_port 11434 "Ollama"
echo.
echo 全部启动执行完毕。服务在后台隐藏运行, 停止请用桌面「一键停止服务」。
ping -n 16 127.0.0.1 >nul
exit /b 0

:check_port
curl -s -o nul -m 3 http://127.0.0.1:%1/ >nul 2>&1
if %errorlevel%==0 echo [OK]   端口 %1 %~2 就绪
if not %errorlevel%==0 echo [FAIL] 端口 %1 %~2 未响应
exit /b 0
