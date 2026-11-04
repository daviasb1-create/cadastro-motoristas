"""Caminhos de dados do aplicativo (por usuário, sem exigir administrador)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from netvision import APP_ID


def is_windows() -> bool:
    return sys.platform.startswith("win")


def is_frozen() -> bool:
    """True quando rodando como executável gerado pelo PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def data_dir() -> Path:
    override = os.environ.get("NETVISION_DATA_DIR")
    if override:
        base = Path(override)
    elif is_windows():
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_ID
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_ID
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return data_dir() / "netvision.sqlite3"


def config_path() -> Path:
    return data_dir() / "config.json"


def log_path() -> Path:
    return data_dir() / "netvision.log"


def reports_dir() -> Path:
    p = Path.home() / "Documents" / "NetVision Relatorios"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        p = data_dir() / "relatorios"
        p.mkdir(parents=True, exist_ok=True)
    return p


def resource_path(relative: str) -> Path:
    """Localiza arquivos empacotados (assets) tanto no código-fonte quanto no .exe."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / relative
