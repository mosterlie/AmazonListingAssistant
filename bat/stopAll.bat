@echo off
title AmazonListingAssistant һ��ֹͣ (ERP+ͼƬ/Sakura/Chrome/Ollama)

echo ============================================
echo   1/4 ֹͣ ERP+ͼƬ ���� (�˿� 8000/8765)...
echo ============================================
:: 1) �������о�ȷ���� python �������, ��Ӱ������ python
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'server\.app|db_agent\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
:: 2) �ر�����ʱ�򿪵ķ��� cmd ���� (��һ������������)
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | Where-Object { $_.CommandLine -match 'startAll\.bat|server\.app|db_agent\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
:: 3) ����: ���˿ڽ�����������
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000 " ^| findstr "LISTENING"') do taskkill /F /T /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8765 " ^| findstr "LISTENING"') do taskkill /F /T /PID %%a >nul 2>&1
echo [OK] ERP+ͼƬ ������ֹͣ, ����ʱ�򿪵� cmd ������ͬ���ر�

echo ============================================
echo   2/4 ֹͣ SakuraFrp...
echo ============================================
taskkill /F /IM SakuraLauncher.exe >nul 2>&1
taskkill /F /IM SakuraFrpService.exe >nul 2>&1
taskkill /F /IM frpc.exe >nul 2>&1
echo [OK] SakuraFrp ��ֹͣ

echo ============================================
echo   3/4 ֹͣ���� Chrome (9222, �� C:\ChromeDebugUser ʵ��)...
echo ============================================
powershell -NoProfile -Command "$c = Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | Where-Object {$_.CommandLine -like '*ChromeDebugUser*'}; if ($c) { $c | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } }"
echo [OK] ���� Chrome ��ֹͣ, ��Ӱ���ճ������

echo ============================================
echo   4/4 ֹͣ Ollama ���� llama ģ�ͽ���...
echo ============================================
taskkill /F /T /IM "ollama app.exe" >nul 2>&1
taskkill /F /T /IM ollama.exe >nul 2>&1
taskkill /F /T /IM ollama_llama_server.exe >nul 2>&1
taskkill /F /T /IM llama-server.exe >nul 2>&1
:: ����: ���������������� ollama / llama ��ؽ��� (���°� Ollama �� llama-server.exe ��������)
powershell -NoProfile -Command "Get-Process | Where-Object { $_.Name -match 'ollama|llama' } | Stop-Process -Force -ErrorAction SilentlyContinue"
echo [OK] Ollama �� llama ��ؽ�����ȫ��ֹͣ

echo.
echo ============================================
echo   ֹͣ��ɣ�����ȷ�� 4 ���˿��ѹر�...
echo ============================================
ping -n 3 127.0.0.1 >nul
call :check_down 8000 "ERP����"
call :check_down 8765 "ͼƬ����"
call :check_down 9222 "Chrome����"
call :check_down 11434 "Ollama"
echo.
echo ȫ��ִֹͣ����ϡ�
ping -n 6 127.0.0.1 >nul
exit /b 0

:check_down
netstat -aon | findstr ":%1 " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 echo [FAIL] �˿� %1 %~2 ��������
if not %errorlevel%==0 echo [OK]   �˿� %1 %~2 �ѹر�
exit /b 0
