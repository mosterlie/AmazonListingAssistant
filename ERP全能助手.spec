# -*- mode: python ; coding: utf-8 -*-
# ERP 全能助手 (Windows 桌面版) 打包配置
# 构建: python -m PyInstaller ERP全能助手.spec --noconfirm
# 产物: dist/ERP全能助手/ERP全能助手.exe  (onedir, 双击启动, 无终端残留, 秒开)
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

a = Analysis(
    ['unified_app.py'],
    pathex=[os.getcwd()],
    binaries=[],
    # playwright 的 node 驱动与驱动清单必须完整收集 (CDP 连接必需)
    datas=collect_data_files('playwright', include_py_files=False) +
          [('gui/app.html', 'gui')],
    hiddenimports=[
        'desktop_app',                    # 上件助手常量与工具 (unified_app 复用)
        'sellfox_ad_gui',                 # 广告桥接 (mac 独立版复刻)
        'config',                         # 项目根 config.py
        'server.config',
        'server.database',
        'server.services.erp_bridge',
        'core.driver_guard',
        'core.browser_manager',
        'core.cdp_proxy',
        'core.sellfox_ad_operator',
        'websockets',
        'webview',
        'webview.platforms.winforms',     # Windows 后端 (pythonnet + WebView2)
        'clr_loader',
        'pythonnet',
    ] + collect_submodules('playwright') + collect_submodules('webview'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'numpy', 'pandas', 'scipy', 'PIL', 'notebook', 'IPython'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# onedir 模式: 免去 onefile 每次启动解压的等待 (启动秒开)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ERP全能助手',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ERP全能助手',
)
