"""Medições antes/depois para provar (ou não) o ganho real de cada otimização."""
from __future__ import annotations

import json
import os
import threading
import time

import psutil

from ..config import DATA_DIR, IS_WINDOWS
from ..utils import log, powershell

SNAP_FILE = DATA_DIR / "snapshots.json"
_lock = threading.Lock()

METRICS = [
    # chave, rótulo, unidade, menor é melhor?
    ("ram_used", "RAM em uso", "bytes", True),
    ("processes", "Processos", "n", True),
    ("services_running", "Serviços em execução", "n", True),
    ("cpu_idle", "CPU em repouso (média 8 s)", "%", True),
    ("boot_ms", "Tempo de inicialização (último boot)", "ms", True),
    ("disk_free", "Espaço livre no disco do sistema", "bytes", False),
    ("startup_items", "Apps na inicialização", "n", True),
    ("changes", "Alterações do TURBO BOOST PRO ativas", "n", None),
]


def boot_time_ms() -> int | None:
    """Duração do último boot pelo log Diagnostics-Performance (evento 100). Requer administrador."""
    if not IS_WINDOWS:
        return None
    r = powershell("$e = Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-Diagnostics-Performance/"
                   "Operational'; Id=100} -MaxEvents 1 -ErrorAction SilentlyContinue; if ($e) { "
                   "([xml]$e.ToXml()).Event.EventData.Data | Where-Object Name -eq 'BootTime' | "
                   "ForEach-Object { $_.'#text' } }", timeout=60)
    try:
        return int(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def capture(label: str, cpu_seconds: int = 8, journal=None) -> dict:
    """Mede o estado atual do sistema."""
    psutil.cpu_percent(None)
    samples = []
    for _ in range(cpu_seconds):
        time.sleep(1)
        samples.append(psutil.cpu_percent(None))
    vm = psutil.virtual_memory()
    sys_drive = os.environ.get("SystemDrive", "C:") + os.sep if IS_WINDOWS else "/"
    running = 0
    if IS_WINDOWS:
        try:
            running = sum(1 for s in psutil.win_service_iter() if s.status() == "running")
        except Exception:
            running = 0
    try:
        from . import startup
        startup_items = sum(1 for e in startup.list_entries() if e["enabled"])
    except Exception:
        startup_items = 0
    snap = {
        "id": int(time.time() * 1000), "label": label, "time": time.time(),
        "ram_used": vm.total - vm.available, "ram_total": vm.total, "processes": len(psutil.pids()),
        "services_running": running, "cpu_idle": round(sum(samples) / len(samples), 1) if samples else None,
        "boot_ms": boot_time_ms(), "disk_free": psutil.disk_usage(sys_drive).free,
        "startup_items": startup_items, "changes": len(journal.describe()) if journal else 0,
        "uptime_min": int((time.time() - psutil.boot_time()) / 60), "boot_at": psutil.boot_time(),
    }
    with _lock:
        data = load()
        data.append(snap)
        _save(data[-60:])
    log.info("SNAPSHOT %s: %s", label, {k: snap[k] for k in ("ram_used", "processes", "cpu_idle", "boot_ms")})
    return snap


def load() -> list[dict]:
    try:
        return json.loads(SNAP_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(data):
    tmp = SNAP_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, SNAP_FILE)


def clear():
    with _lock:
        _save([])


def compare(a: dict, b: dict) -> list[dict]:
    """Diferença entre duas medições. 'better' = True se melhorou."""
    rows = []
    for key, label, unit, lower_better in METRICS:
        va, vb = a.get(key), b.get(key)
        if va is None or vb is None:
            rows.append({"key": key, "label": label, "unit": unit, "a": va, "b": vb, "delta": None, "better": None,
                         "pct": None})
            continue
        delta = vb - va
        pct = (delta / va * 100) if va else None
        better = None if lower_better is None or delta == 0 else (delta < 0) == lower_better
        rows.append({"key": key, "label": label, "unit": unit, "a": va, "b": vb, "delta": delta, "better": better,
                     "pct": pct})
    return rows


def same_boot(a: dict, b: dict) -> bool:
    return abs((a.get("boot_at") or 0) - (b.get("boot_at") or 0)) < 60
