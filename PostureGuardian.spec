# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('pose_landmarker.task', '.')]
binaries = []
hiddenimports = ['mediapipe.tasks.c']

# Collect all of mediapipe (includes libmediapipe.dll and mediapipe.tasks.c)
mp_datas, mp_binaries, mp_hidden = collect_all('mediapipe')
datas += mp_datas
binaries += mp_binaries
hiddenimports += mp_hidden

# Collect all of pystray
ps_datas, ps_binaries, ps_hidden = collect_all('pystray')
datas += ps_datas
binaries += ps_binaries
hiddenimports += ps_hidden

# Collect all of customtkinter
ctk_datas, ctk_binaries, ctk_hidden = collect_all('customtkinter')
datas += ctk_datas
binaries += ctk_binaries
hiddenimports += ctk_hidden

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    a.binaries,
    a.datas,
    [],
    name='PostureGuardian',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
