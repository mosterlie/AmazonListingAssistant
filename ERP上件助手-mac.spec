# -*- mode: python ; coding: utf-8 -*-
# ERP 桌面上件助手 (macOS) 打包配置
# 构建命令: python3 -m PyInstaller ERP上件助手-mac.spec --noconfirm
# 产物目录: dist/ERP上件助手.app (可直接在 macOS 上双击运行或拖入 Applications 目录)

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

a = Analysis(
    ['desktop_app.py'],
    pathex=[os.getcwd()],
    binaries=[],
    # 收集 Playwright Node 驱动与必需静态资源 (启动画面等)
    datas=collect_data_files('playwright', include_py_files=False) + [
        ('assets/splash.png', 'assets')
    ],
    hiddenimports=[
        'core.browser_manager',
        'core.tab_matcher',
        'core.form_operator',
        'parsers.dom_precision_parser',
        'parsers.table_parser',
        'parsers.data_sniffer',
        'server.services.erp_bridge',
        'server.services.product_service',
        'server.services.file_service',
        'server.services.task_service',
        'server.services.auth_service',
        'server.database',
        'server.config',
        'browser_engine',
        'config',
        'sqlite3',
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'urllib.request',
        'urllib.parse',
    ] + collect_submodules('playwright'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'numpy', 'pandas', 'PIL', 'pytest'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# onedir 模式: 秒开启动，避免单文件解压延迟
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ERP上件助手',
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
    name='ERP上件助手',
)

# macOS .app 应用束：双击直接启动，Dock栏与启动台正常识别
app = BUNDLE(
    coll,
    name='ERP上件助手.app',
    icon=None,
    bundle_identifier='com.browsertoolkit.erp-uploader',
)
