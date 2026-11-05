"""Agendador local (APScheduler). Mantenha esta janela aberta ou registre-o no
Agendador de Tarefas do Windows (ver docs/INSTALACAO_WINDOWS.md).

Horários lidos de Configurações > Agenda (fuso America/Sao_Paulo).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from apscheduler.schedulers.blocking import BlockingScheduler  # noqa: E402
from apscheduler.triggers.cron import CronTrigger  # noqa: E402

from config.settings import TIMEZONE  # noqa: E402
from database.db import all_settings, init_db  # noqa: E402
from modules.scheduler.pipeline import run_with_retries  # noqa: E402
from services.logger import get_logger  # noqa: E402

log = get_logger("agendador")


def _job(mode: str) -> None:
    log.info("Disparando pesquisa %s", mode)
    result = run_with_retries(mode=mode, trigger="agendado")
    log.info("Resultado: %s", result.get("status"))


def main() -> None:
    init_db()
    agenda = all_settings().get("agenda", {})
    sched = BlockingScheduler(timezone=TIMEZONE, job_defaults={"coalesce": True, "max_instances": 1,
                                                                "misfire_grace_time": 3600})
    for hhmm in agenda.get("pesquisas", ["07:00", "12:00", "17:00"]):
        h, m = hhmm.split(":")
        sched.add_job(_job, CronTrigger(hour=int(h), minute=int(m), timezone=TIMEZONE), args=["completa"],
                      id=f"completa_{hhmm}")
    for hhmm in agenda.get("monitor_urgente", []):
        h, m = hhmm.split(":")
        sched.add_job(_job, CronTrigger(hour=int(h), minute=int(m), timezone=TIMEZONE), args=["urgente"],
                      id=f"urgente_{hhmm}")
    for job in sched.get_jobs():
        log.info("Agendado: %s", job.id)
    log.info("Agendador ativo (Ctrl+C para encerrar).")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Agendador encerrado.")


if __name__ == "__main__":
    main()
