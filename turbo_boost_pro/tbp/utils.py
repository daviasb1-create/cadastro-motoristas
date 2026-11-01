"""Utilitários: execução de comandos, PowerShell, formatação e log."""
from __future__ import annotations

import json
import logging
import subprocess
from logging.handlers import RotatingFileHandler

from .config import IS_WINDOWS, LOG_DIR

CREATE_NO_WINDOW = 0x08000000

log = logging.getLogger("tbp")
if not log.handlers:
    log.setLevel(logging.INFO)
    _h = RotatingFileHandler(LOG_DIR / "turbo_boost_pro.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    log.addHandler(_h)


def run(cmd, timeout: int = 120, check: bool = False) -> subprocess.CompletedProcess:
    """Executa um comando sem abrir janela de console."""
    kwargs = dict(capture_output=True, text=True, timeout=timeout, errors="replace")
    if IS_WINDOWS:
        kwargs["creationflags"] = CREATE_NO_WINDOW
    try:
        res = subprocess.run(cmd, **kwargs)
    except FileNotFoundError as e:
        res = subprocess.CompletedProcess(cmd, 127, "", str(e))
    except subprocess.TimeoutExpired:
        res = subprocess.CompletedProcess(cmd, 124, "", "timeout")
    log.info("CMD %s -> %s", cmd if isinstance(cmd, str) else " ".join(map(str, cmd)), res.returncode)
    if check and res.returncode != 0:
        raise RuntimeError(f"Falha ao executar {cmd}: {res.stderr.strip() or res.stdout.strip()}")
    return res


def powershell(script: str, timeout: int = 120) -> subprocess.CompletedProcess:
    if not IS_WINDOWS:
        return subprocess.CompletedProcess(script, 1, "", "PowerShell indisponível neste sistema")
    prefix = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;$ProgressPreference='SilentlyContinue';"
    return run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-Command", prefix + script], timeout=timeout)


def powershell_json(script: str, timeout: int = 120):
    """Executa PowerShell e converte a saída (ConvertTo-Json) em objeto Python. Retorna lista."""
    res = powershell(f"{script} | ConvertTo-Json -Depth 4 -Compress", timeout=timeout)
    out = (res.stdout or "").strip()
    if res.returncode != 0 or not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else [data]


def fmt_bytes(n: float) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_rate(n: float) -> str:
    return fmt_bytes(n) + "/s"
