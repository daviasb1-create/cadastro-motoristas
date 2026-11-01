"""Armazenamento: detecção SSD/HDD, TRIM, otimização de volume e ajustes NTFS reversíveis."""
from __future__ import annotations

import re

from ..utils import powershell, powershell_json, run
from .journal import Journal


def list_volumes() -> list[dict]:
    rows = powershell_json(
        "Get-Partition | Where-Object DriveLetter | ForEach-Object { $p=$_; "
        "$d = Get-PhysicalDisk | Where-Object DeviceId -eq $p.DiskNumber | Select-Object -First 1; "
        "$v = Get-Volume -DriveLetter $p.DriveLetter; "
        "[pscustomobject]@{Letter=[string]$p.DriveLetter; Media=[string]$d.MediaType; Bus=[string]$d.BusType; "
        "Model=$d.FriendlyName; Size=$v.Size; Free=$v.SizeRemaining; FS=$v.FileSystem} }", timeout=60)
    out = []
    for r in rows:
        media = (r.get("Media") or "").upper()
        bus = (r.get("Bus") or "").upper()
        kind = "SSD" if media == "SSD" or bus == "NVME" else ("HDD" if media == "HDD" else "Desconhecido")
        out.append({"letter": r.get("Letter"), "kind": kind, "bus": r.get("Bus"), "model": r.get("Model"),
                    "size": r.get("Size") or 0, "free": r.get("Free") or 0, "fs": r.get("FS")})
    return out


def _fsutil_query(setting: str) -> str:
    out = run(["fsutil", "behavior", "query", setting]).stdout
    m = re.search(r"=\s*(\d+)", out)
    return m.group(1) if m else ""


def trim_enabled() -> bool | None:
    out = run(["fsutil", "behavior", "query", "DisableDeleteNotify"]).stdout
    m = re.search(r"NTFS DisableDeleteNotify\s*=\s*(\d)", out) or re.search(r"=\s*(\d)", out)
    return None if not m else m.group(1) == "0"


def enable_trim(journal: Journal) -> str:
    if trim_enabled():
        return "TRIM já está ativado."
    gid = "storage:trim"
    journal.group(gid, "TRIM ativado para SSD", "armazenamento")
    journal.add_action(gid, {"kind": "cmd", "cmd": ["fsutil", "behavior", "set", "DisableDeleteNotify", "1"],
                             "desc": "Restaurar configuração de TRIM"})
    run(["fsutil", "behavior", "set", "DisableDeleteNotify", "0"])
    return "TRIM ativado."


def set_last_access_off(journal: Journal) -> str:
    """Desativa a atualização do 'último acesso' em arquivos NTFS (menos escritas em disco)."""
    prev = _fsutil_query("disablelastaccess")
    if prev in ("1", "3"):
        return "Atualização de último acesso já está desativada."
    gid = "storage:lastaccess"
    journal.group(gid, "NTFS: último acesso desativado", "armazenamento")
    journal.add_action(gid, {"kind": "cmd", "cmd": ["fsutil", "behavior", "set", "disablelastaccess",
                                                    prev or "2"], "desc": "Restaurar último acesso NTFS"})
    run(["fsutil", "behavior", "set", "disablelastaccess", "1"])
    return "Atualização de último acesso NTFS desativada."


def optimize_volume(letter: str, kind: str) -> str:
    """SSD: ReTrim (informa ao SSD os blocos livres). HDD: desfragmentação. Nunca desfragmenta SSD."""
    if kind == "SSD":
        r = powershell(f"Optimize-Volume -DriveLetter {letter} -ReTrim -Verbose", timeout=1800)
        return f"Unidade {letter}: TRIM executado." if r.returncode == 0 else f"Falha no TRIM: {r.stderr[:150]}"
    if kind == "HDD":
        r = powershell(f"Optimize-Volume -DriveLetter {letter} -Defrag -Verbose", timeout=7200)
        return f"Unidade {letter}: desfragmentada." if r.returncode == 0 else f"Falha: {r.stderr[:150]}"
    r = powershell(f"Optimize-Volume -DriveLetter {letter}", timeout=3600)
    return f"Unidade {letter}: otimizada pelo Windows." if r.returncode == 0 else "Falha ao otimizar."


def hibernation_info() -> dict:
    import os
    path = os.path.join(os.environ.get("SystemDrive", "C:") + os.sep, "hiberfil.sys")
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    return {"enabled": size > 0, "size": size}
