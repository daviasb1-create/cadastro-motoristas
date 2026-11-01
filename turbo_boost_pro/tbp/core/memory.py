"""Liberação de memória RAM.

1) Working sets: pede ao Windows para devolver páginas não usadas de processos em segundo plano
   (EmptyWorkingSet). Não fecha nada; o processo recarrega o que precisar.
2) Standby list: descarta o cache de arquivos em espera (requer administrador).
Ambos são temporários por natureza e não exigem reversão.
"""
from __future__ import annotations

import ctypes
import os

import psutil

from ..config import IS_WINDOWS
from ..utils import log
from . import winapi
from .processes import PROTECTED

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_SET_QUOTA = 0x0100


def ram_status() -> dict:
    vm = psutil.virtual_memory()
    return {"total": vm.total, "available": vm.available, "used": vm.total - vm.available,
            "percent": vm.percent}


def trim_working_sets(exclude_pids: set[int] | None = None, min_ws: int = 20 * 1024 * 1024) -> dict:
    """Reduz o working set de processos em segundo plano. Retorna estatísticas."""
    before = psutil.virtual_memory().available
    exclude = set(exclude_pids or ())
    exclude.add(os.getpid())
    fg = winapi.foreground_pid()
    if fg:
        exclude.add(fg)
    trimmed = 0
    if IS_WINDOWS:
        k32 = winapi.kernel32
        for p in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                if p.pid in exclude or p.pid <= 4 or (p.info["name"] or "").lower() in PROTECTED:
                    continue
                mi = p.info["memory_info"]
                if not mi or mi.rss < min_ws:
                    continue
                h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SET_QUOTA, False, p.pid)
                if h:
                    if k32.K32EmptyWorkingSet(h):
                        trimmed += 1
                    k32.CloseHandle(h)
            except (psutil.Error, OSError):
                continue
    after = psutil.virtual_memory().available
    return {"processes": trimmed, "freed": max(0, after - before)}


def purge_standby_list() -> tuple[bool, str]:
    """Esvazia a lista de memória em espera e a lista modificada (como o RAMMap 'Empty Standby List')."""
    if not IS_WINDOWS:
        return False, "Disponível apenas no Windows."
    if not winapi.is_admin():
        return False, "Requer administrador."
    winapi.enable_privilege("SeProfileSingleProcessPrivilege")
    winapi.enable_privilege("SeIncreaseQuotaPrivilege")
    SystemMemoryListInformation = 80
    ok = True
    for cmd in (3, 4):  # 3 = MemoryFlushModifiedList, 4 = MemoryPurgeStandbyList
        c = ctypes.c_int(cmd)
        status = winapi.ntdll.NtSetSystemInformation(SystemMemoryListInformation, ctypes.byref(c),
                                                     ctypes.sizeof(c))
        if status != 0:
            ok = False
            log.warning("NtSetSystemInformation(%s) status=0x%X", cmd, status & 0xFFFFFFFF)
    # Reduz o cache de arquivos do sistema ao mínimo (o Windows o recompõe sob demanda)
    try:
        winapi.kernel32.SetSystemFileCacheSize(ctypes.c_size_t(-1), ctypes.c_size_t(-1), 0)
    except Exception:
        pass
    return ok, "Cache em espera liberado." if ok else "Falha parcial ao liberar o cache em espera."


def optimize_ram(deep: bool = True, exclude_pids: set[int] | None = None) -> dict:
    before = psutil.virtual_memory().available
    stats = trim_working_sets(exclude_pids)
    msg = []
    if deep and winapi.is_admin():
        ok, m = purge_standby_list()
        msg.append(m)
    after = psutil.virtual_memory().available
    stats["freed"] = max(0, after - before)
    stats["message"] = " ".join(msg)
    log.info("RAM otimizada: %s", stats)
    return stats
