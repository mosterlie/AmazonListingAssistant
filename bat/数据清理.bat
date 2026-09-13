@echo off
title AmazonListingAssistant �������� (��Ʒ/����/���/�����ļ�)

set "PROJ=C:\Users\li'l'y\OneDrive - University of Macau\Desktop\mypro\AmazonListingAssistant"

echo ============================================
echo   ERP ҵ������һ������ (Σ�ղ���)
echo ============================================
echo  ���ν�����:
echo    1. ���ݿ�ҵ���: ��Ʒ��Эͬ���񡢹���������м�¼��
echo       ������ӳ�䡢������־
echo    2. ���ز�Ʒ�鵵Ŀ¼ (ϵͳ���õ� storage_path, Ĭ�� D:\products)
echo    3. ��ʱ�ϴ�Ŀ¼ data\uploads
echo.
echo  �Զ�����: �û��˺š�ϵͳȫ������
echo  �Զ�����: ����ǰ�� data Ŀ¼����ʱ������ݿ����
echo  [��ʾ] �� ERP ������������, ������ִ�С�һ��ֹͣ����������
echo.

set /p CONFIRM=ȷ��Ҫ���ȫ��ҵ��������? ���� y ����, ������ȡ��: 
if /i not "%CONFIRM%"=="y" (
    echo.
    echo ��ȡ��, δ�޸��κ����ݡ�
    pause
    exit /b 0
)

echo.
echo ����ִ������...
pushd "%PROJ%"
python clean_business_data.py --yes
popd

echo.
echo ��������ִ�����, �����ڿɹرա�
pause
exit /b 0
