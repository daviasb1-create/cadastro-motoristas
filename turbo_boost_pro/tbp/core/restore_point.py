"""Criação de Ponto de Restauração do Sistema antes de alterações críticas."""
from __future__ import annotations

import time

from ..config import IS_WINDOWS
from ..utils import log, powershell
from . import registry as reg
from .winapi import is_admin

_SR_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\SystemRestore"
_last_ok = 0.0


def create(description: str = "TURBO BOOST PRO - antes das otimizações") -> tuple[bool, str]:
    """Cria ponto de restauração. Contorna temporariamente o limite de 1 ponto/24h do Windows
    (o valor original é restaurado logo em seguida)."""
    global _last_ok
    if not IS_WINDOWS:
        return False, "Disponível apenas no Windows."
    if not is_admin():
        return False, "Requer administrador."
    if time.time() - _last_ok < 600:
        return True, "Ponto de restauração já criado nesta sessão (há menos de 10 min)."
    existed, typ, old = reg.read_value("HKLM", _SR_KEY, "SystemRestorePointCreationFrequency")
    try:
        reg.write_value("HKLM", _SR_KEY, "SystemRestorePointCreationFrequency", reg.REG_DWORD, 0)
        desc = description.replace("'", "")
        r = powershell(f"Checkpoint-Computer -Description '{desc}' -RestorePointType 'MODIFY_SETTINGS'",
                       timeout=300)
    finally:
        if existed:
            reg.write_value("HKLM", _SR_KEY, "SystemRestorePointCreationFrequency", typ, old)
        else:
            reg.delete_value("HKLM", _SR_KEY, "SystemRestorePointCreationFrequency")
    if r.returncode == 0:
        _last_ok = time.time()
        return True, "Ponto de restauração criado com sucesso."
    err = (r.stderr or r.stdout).strip()
    log.warning("Falha no ponto de restauração: %s", err)
    if "disabled" in err.lower() or "desativad" in err.lower() or "0x80042306" in err:
        return False, ("A Proteção do Sistema está desativada no disco C:. Ative em "
                       "'Criar ponto de restauração' > Configurar.")
    return False, f"Não foi possível criar o ponto de restauração: {err[:200]}"


def enable_protection_c() -> tuple[bool, str]:
    r = powershell("Enable-ComputerRestore -Drive \"$env:SystemDrive\\\"")
    return r.returncode == 0, (r.stderr or "Proteção do sistema ativada.").strip()


def open_system_restore():
    if IS_WINDOWS:
        import subprocess
        subprocess.Popen(["rstrui.exe"])


def list_points() -> list[dict]:
    from ..utils import powershell_json
    return powershell_json("Get-ComputerRestorePoint | Select-Object SequenceNumber,Description,CreationTime")

