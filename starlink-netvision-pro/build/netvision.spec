# -*- mode: python ; coding: utf-8 -*-
# Gera dist/StarlinkNetVisionPro.exe (arquivo único, sem console).
# Uso: pyinstaller build/netvision.spec --noconfirm
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
hidden = (
    collect_submodules("netvision")
    + collect_submodules("grpc_reflection")
    + collect_submodules("scapy.layers")
    + collect_submodules("scapy.arch")
    + ["scapy.libs.manuf", "starlink_grpc", "yagrc.reflector", "yagrc.importer", "dnslib", "icmplib"]
)
excludes = ["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
            "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtPdf", "matplotlib",
            "IPython", "pytest", "spacex", "starlink_client"]

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "assets" / "icon.ico"), "assets"), (str(ROOT / "assets" / "icon.png"), "assets")],
    hiddenimports=hidden,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="StarlinkNetVisionPro",
    console=False,
    icon=str(ROOT / "assets" / "icon.ico"),
    version=str(ROOT / "build" / "version_info.txt") if sys.platform.startswith("win") else None,
    uac_admin=False,          # NÃO pede administrador ao abrir; elevação só sob demanda
    upx=False,
)
