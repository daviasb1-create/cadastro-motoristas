"""Pasta de roteirização: subpastas por tipo de relatório e escolha das planilhas recentes.

A leitura das planilhas em si é feita pelo código da ferramenta (SheetJS), em jsengine.
"""
from __future__ import annotations

import time
from pathlib import Path

EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".csv"}

# Uma subpasta por campo de upload da ferramenta (todas aceitam o mesmo modelo de planilha)
FOLDERS = {
    "chegando": "1 - Fretes chegando",
    "no_rj": "2 - Cargas ja no Rio",
    "agendado": "3 - Agendamentos",
    "saida": "Rotas geradas",
}


def ensure_folders(base: Path) -> None:
    for name in FOLDERS.values():
        (base / name).mkdir(parents=True, exist_ok=True)


def recent_files(folder: Path, max_age_hours: float) -> tuple[list[Path], list[Path]]:
    """(planilhas recentes, planilhas antigas ignoradas). Ignora temporários do Excel (~$)."""
    if not folder.exists():
        return [], []
    files = sorted(p for p in folder.iterdir()
                   if p.is_file() and p.suffix.lower() in EXTENSIONS and not p.name.startswith("~$"))
    if not max_age_hours:
        return files, []
    limit = time.time() - max_age_hours * 3600
    return [p for p in files if p.stat().st_mtime >= limit], [p for p in files if p.stat().st_mtime < limit]
