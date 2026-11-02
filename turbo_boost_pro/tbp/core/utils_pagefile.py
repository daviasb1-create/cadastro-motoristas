"""Leitura do modo de paginação (separado para evitar importações circulares)."""
from __future__ import annotations

from ..config import IS_WINDOWS
from ..utils import powershell_json


def pagefile_is_auto() -> bool | None:
    if not IS_WINDOWS:
        return None
    rows = powershell_json("Get-CimInstance Win32_ComputerSystem | Select-Object AutomaticManagedPagefile")
    return bool(rows[0].get("AutomaticManagedPagefile")) if rows else None
