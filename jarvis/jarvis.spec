# -*- mode: python ; coding: utf-8 -*-
# Gera o executável do JARVIS:  .venv\Scripts\pyinstaller jarvis.spec --noconfirm
# Resultado: dist\Jarvis\Jarvis.exe (pasta portátil). O modelo de voz fica em dist\Jarvis\models.
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

binaries = collect_dynamic_libs("vosk") + collect_dynamic_libs("sounddevice")
datas = collect_data_files("_sounddevice_data") + collect_data_files("certifi") + collect_data_files("edge_tts")
hiddenimports = (
    collect_submodules("jarvis")
    + collect_submodules("pycaw")
    + collect_submodules("comtypes")
    + collect_submodules("keyring.backends")
    + ["win32timezone", "miniaudio", "_cffi_backend"]
)

a = Analysis(
    ["run_jarvis.pyw"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "PySide6.QtWebEngineCore", "PySide6.Qt3DCore", "PySide6.QtQuick"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="Jarvis", icon="assets/jarvis.ico",
    console=False, upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Jarvis")
