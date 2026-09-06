# -*- mode: python ; coding: utf-8 -*-
# 赛狐广告批量投放助手 (mac) 打包配置
# 构建: python3 -m PyInstaller sellfox_ad_gui.spec --noconfirm
# 产物: dist/赛狐广告投放助手.app  (onedir, 双击启动, 无终端残留, 秒开)
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

a = Analysis(
    ['sellfox_ad_gui.py'],
    pathex=[os.getcwd()],
    binaries=[],
    # playwright 的 node 驱动与浏览器驱动清单必须完整收集 (CDP 连接必需)
    datas=collect_data_files('playwright', include_py_files=False) +
         [('gui/index.html', 'gui')],
    hiddenimports=[
        'core.browser_manager',
        'core.cdp_proxy',
        'core.sellfox_ad_operator',
        'websockets',
        'webview',
        'webview.platforms.cocoa',
        'webview.platforms.winforms',
    ] + collect_submodules('playwright') + collect_submodules('webview'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['server', 'desktop_app', 'db_agent', 'matplotlib', 'numpy', 'pandas', 'PIL'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# onedir 模式: 免去 onefile 每次启动解压 51MB 的等待 (启动秒开)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='赛狐广告投放助手',
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
    name='赛狐广告投放助手',
)

# .app 包: 双击启动不经过终端 (无 exec/终端残留窗口), Launchpad 可见
app = BUNDLE(
    coll,
    name='赛狐广告投放助手.app',
    icon=None,
    bundle_identifier='com.browsertoolkit.sellfox-ad',
)
