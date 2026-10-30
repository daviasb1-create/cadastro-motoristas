"""Leitura do arquivo .env (chaves de API fora do código e fora da interface).

Procura, nesta ordem: <pasta do projeto>/.env e %APPDATA%\\Jarvis\\.env.
Variáveis já definidas no sistema têm prioridade e não são sobrescritas.
Os valores nunca são exibidos na interface nem gravados em log.
"""
from __future__ import annotations

import os
from pathlib import Path

from . import paths


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:]
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].strip()
        if key:
            values[key] = value
    return values


def env_files() -> list[Path]:
    return [paths.project_root() / ".env", paths.data_dir() / ".env"]


def load_env(files: list[Path] | None = None) -> list[Path]:
    """Carrega as variáveis dos arquivos .env existentes. Retorna os arquivos lidos."""
    loaded = []
    for file in files or env_files():
        if file.exists():
            for key, value in parse_env(file.read_text(encoding="utf-8-sig")).items():
                os.environ.setdefault(key, value)
            loaded.append(file)
    return loaded
