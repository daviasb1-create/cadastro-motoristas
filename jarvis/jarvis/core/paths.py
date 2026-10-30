"""Localização dos diretórios de dados, logs, cache e modelos.

No Windows os dados ficam em %APPDATA%\\Jarvis. A variável de ambiente
JARVIS_HOME permite sobrescrever o local (usada nos testes e em instalações
portáteis).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"


def project_root() -> Path:
    """Raiz do projeto (ou pasta do executável quando empacotado)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    env = os.environ.get("JARVIS_HOME")
    if env:
        base = Path(env)
    elif IS_WINDOWS:
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Jarvis"
    else:
        base = Path.home() / ".jarvis"
    base.mkdir(parents=True, exist_ok=True)
    return base


def sub_dir(name: str) -> Path:
    path = data_dir() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    return sub_dir("logs")


def cache_dir() -> Path:
    return sub_dir("cache")


def models_dir() -> Path:
    """Modelos de voz: primeiro procura na pasta do projeto, depois nos dados do usuário."""
    local = project_root() / "models"
    if local.exists():
        return local
    return sub_dir("models")


def settings_path() -> Path:
    return data_dir() / "settings.json"


def database_path() -> Path:
    return data_dir() / "jarvis.db"


def token_cache_path() -> Path:
    return data_dir() / "msal_token_cache.bin"
