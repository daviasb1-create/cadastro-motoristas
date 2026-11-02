# -*- mode: python ; coding: utf-8 -*-
# Gera dist\TurboBoostPro\TurboBoostPro.exe (modo pasta: inicia mais rápido que arquivo único).
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files("customtkinter") + [("assets/icon.ico", "assets"), ("assets/icon.png", "assets")]
# As páginas são carregadas sob demanda (importlib): listadas explicitamente para entrarem no .exe
PAGES = ["dashboard", "gaming", "cleaner", "performance", "advanced", "ultralite", "diagnostics", "security"]
hidden = (collect_submodules("tbp") + ["tbp.ui", "tbp.ui.pages"] + [f"tbp.ui.pages.{p}" for p in PAGES]
          + ["win32pdh", "win32com.client", "pythoncom", "win32timezone"])

a = Analysis(
    ["main.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=hidden,
    excludes=["matplotlib", "numpy", "pandas", "scipy", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TurboBoostPro",
    icon="assets/icon.ico",
    console=False,
    uac_admin=False,          # pede administrador somente quando necessário (botão no app)
    version="version_info.txt",
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="TurboBoostPro")
