# -*- mode: python ; coding: utf-8 -*-
# 赛狐广告批量投放助手 (mac) 打包配置
# 构建: pyinstaller sellfox_ad_gui.spec --noconfirm
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

a = Analysis(
    ['sellfox_ad_gui.py'],
    pathex=[os.getcwd()],
    binaries=[],
    # playwright 的 node 驱动与浏览器驱动清单必须完整收集 (CDP 连接必需)
    datas=collect_data_files('playwright', include_py_files=False),
    hiddenimports=[
        'core.browser_manager',
        'core.cdp_proxy',
        'core.sellfox_ad_operator',
        'websockets',
    ] + collect_submodules('playwright'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['server', 'desktop_app', 'db_agent', 'matplotlib', 'numpy', 'pandas', 'PIL'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# 注: macOS 不支持 Splash 启动画面, 此处不使用
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='赛狐广告投放助手',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
