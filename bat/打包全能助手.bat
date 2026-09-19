@echo off
chcp 65001 >nul
title 打包 ERP 全能助手 (Windows)
cd /d "%~dp0.."
echo ============================================
echo   打包 ERP 全能助手 (onedir 模式)...
echo ============================================
python -m PyInstaller ERP全能助手.spec --noconfirm
if errorlevel 1 (
    echo.
    echo [ERROR] 打包失败, 请检查上方输出
    pause
    exit /b 1
)
echo.
echo [OK] 打包完成: dist\ERP全能助手\ERP全能助手.exe
echo     分发时把整个 dist\ERP全能助手 文件夹拷贝到目标机器即可运行
start "" explorer "dist\ERP全能助手"
pause
