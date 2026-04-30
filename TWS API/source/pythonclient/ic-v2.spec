# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

numpy_datas, numpy_binaries, numpy_hiddenimports = collect_all('numpy')
pandas_datas, pandas_binaries, pandas_hiddenimports = collect_all('pandas')
openpyxl_datas, openpyxl_binaries, openpyxl_hiddenimports = collect_all('openpyxl')

a = Analysis(
    ['ic-v2.py'],
    pathex=[],
    binaries=numpy_binaries + pandas_binaries + openpyxl_binaries,
    datas=numpy_datas + pandas_datas + openpyxl_datas,
    hiddenimports=numpy_hiddenimports + pandas_hiddenimports + openpyxl_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ic-v2',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
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
    upx=True,
    upx_exclude=[],
    name='ic-v2',
)
