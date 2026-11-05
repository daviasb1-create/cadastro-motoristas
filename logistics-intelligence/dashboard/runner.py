"""Disparo da pesquisa manual em segundo plano (não trava a interface)."""
from __future__ import annotations

import subprocess
import sys

from config.settings import BASE_DIR, LOG_DIR


def start_manual_run(mode: str = "completa") -> None:
    log = open(LOG_DIR / "execucao_manual.log", "a", encoding="utf-8")
    kwargs = {}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, str(BASE_DIR / "run_pipeline.py"), "--mode", mode, "--trigger", "manual",
                      "--tentativas", "1"], cwd=str(BASE_DIR), stdout=log, stderr=log, **kwargs)
