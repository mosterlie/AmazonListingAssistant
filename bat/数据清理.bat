@echo off
title AmazonListingAssistant 数据清理 (商品/任务/广告/本地文件)

set "PROJ=C:\Users\li'l'y\OneDrive - University of Macau\Desktop\mypro\AmazonListingAssistant"

echo ============================================
echo   ERP 业务数据一键清理 (危险操作)
echo ============================================
echo  本次将清理:
echo    1. 数据库业务表: 商品、协同任务、广告任务及运行记录、
echo       条形码映射、刊登日志
echo    2. 本地产品归档目录 (系统配置的 storage_path, 默认 D:\products)
echo    3. 临时上传目录 data\uploads
echo.
echo  自动保留: 用户账号、系统全局配置
echo  自动备份: 清理前在 data 目录生成时间戳数据库快照
echo  [提示] 若 ERP 服务正在运行, 建议先执行「一键停止服务」再清理
echo.

set /p CONFIRM=确认要清空全部业务数据吗? 输入 y 继续, 其它键取消: 
if /i not "%CONFIRM%"=="y" (
    echo.
    echo 已取消, 未修改任何数据。
    pause
    exit /b 0
)

echo.
echo 正在执行清理...
pushd "%PROJ%"
python clean_business_data.py --yes
popd

echo.
echo 清理流程执行完毕, 本窗口可关闭。
pause
exit /b 0
