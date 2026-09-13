@echo off
title AmazonListingAssistant һ������ (ERP+ͼƬ/Sakura/Ollama)

set "PROJ=C:\Users\li'l'y\OneDrive - University of Macau\Desktop\mypro\AmazonListingAssistant"
set "SAKURA_PATH=C:\Program Files\SakuraFrpLauncher\SakuraLauncher.exe"
set "OLLAMA_PATH=%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
set "OLLAMA_CLI=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"

echo ============================================
echo   1/3 ���� ERP+ͼƬ ���� (��̨��������, �˿� 8000/8765)...
echo ============================================
if not exist "%PROJ%\server\app.py" (
    echo [ERROR] δ�ҵ���Ŀ: %PROJ%
) else (
    powershell -NoProfile -Command "Start-Process cmd -ArgumentList '/k chcp 65001 >nul && title ERP+ͼƬ���� 8000/8765 && start /b python -m server.app && start /b python db_agent.py --port 8765 --token erp2024' -WindowStyle Hidden -WorkingDirectory \"%PROJ%\""
    echo [OK] ERP+ͼƬ �����Ѻ�̨����, ����������: http://127.0.0.1:8000 �� http://127.0.0.1:8765
)
ping -n 3 127.0.0.1 >nul

echo ============================================
echo   2/3 ���� SakuraFrp �ͻ��� (��̨��������)...
echo ============================================
if exist "%SAKURA_PATH%" (
    powershell -NoProfile -Command "Start-Process -FilePath \"%SAKURA_PATH%\" -WindowStyle Hidden"
    echo [OK] SakuraFrp �Ѻ�̨����
) else (
    echo [WARN] δ�ҵ� %SAKURA_PATH%�����鰲װ·��
)
ping -n 3 127.0.0.1 >nul
powershell -NoProfile -Command "Start-Sleep 2; Add-Type -Name W -Namespace N -MemberDefinition '[DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr h, int c);'; $p = Get-Process SakuraLauncher -ErrorAction SilentlyContinue; if ($p -and $p.MainWindowHandle -ne 0) { [void][N.W]::ShowWindow($p.MainWindowHandle, 0) }"
echo [OK] SakuraFrp ����������

echo ============================================
echo   3/3 ���� Ollama (��̨��������)...
echo ============================================
if not exist "%OLLAMA_PATH%" (
    echo [WARN] δ�ҵ� %OLLAMA_PATH%�����鰲װ·����
    goto ollama_done
)
powershell -NoProfile -Command "Start-Process -FilePath \"%OLLAMA_PATH%\" -WindowStyle Hidden"
ping -n 6 127.0.0.1 >nul
curl -s -o nul -m 2 http://127.0.0.1:11434/ >nul 2>&1
if %errorlevel%==0 (
    goto ollama_hide
)
echo [INFO] Ollama ͼ�ν���δ��ʱ��Ӧ, ���ú�̨����ģʽ...
start "Ollama����" /MIN "%OLLAMA_CLI%" serve
ping -n 4 127.0.0.1 >nul
curl -s -o nul -m 2 http://127.0.0.1:11434/ >nul 2>&1
if %errorlevel%==0 echo [OK] Ollama ��̨������ (�˿� 11434)
if not %errorlevel%==0 echo [WARN] Ollama �˿� 11434 δ����, ���ֶ����� Ollama
:ollama_hide
powershell -NoProfile -Command "Start-Sleep 2; Add-Type -Name W2 -Namespace N2 -MemberDefinition '[DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr h, int c);'; Get-Process | Where-Object { $_.Name -like 'ollama*' } | ForEach-Object { if ($_.MainWindowHandle -ne 0) { [void][N2.W2]::ShowWindow($_.MainWindowHandle, 0) } }"
echo [OK] Ollama ������, ����������
:ollama_done

echo.
echo ============================================
echo   ������ɣ����ڼ�� 3 ���˿�...
echo ============================================
ping -n 3 127.0.0.1 >nul
call :check_port 8000 "ERP����"
call :check_port 8765 "ͼƬ����"
call :check_port 11434 "Ollama"
echo.
echo ȫ������ִ����ϡ������ں�̨��������, ֹͣ�������桸һ��ֹͣ���񡹡�
ping -n 16 127.0.0.1 >nul
exit /b 0

:check_port
curl -s -o nul -m 3 http://127.0.0.1:%1/ >nul 2>&1
if %errorlevel%==0 echo [OK]   �˿� %1 %~2 ����
if not %errorlevel%==0 echo [FAIL] �˿� %1 %~2 δ��Ӧ
exit /b 0
