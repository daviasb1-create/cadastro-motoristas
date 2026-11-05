"""Execução do radar pela linha de comando (usada pelo agendador local e pelo GitHub Actions).

Exemplos:
    python run_pipeline.py                 # pesquisa completa
    python run_pipeline.py --mode urgente  # monitor de urgentes (mais leve)
    python run_pipeline.py --report        # apenas gera o relatório diário
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from database.db import init_db  # noqa: E402
from modules.scheduler.pipeline import run_with_retries  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="LOGISTICS INTELLIGENCE: execução do radar")
    ap.add_argument("--mode", choices=["completa", "urgente"], default="completa")
    ap.add_argument("--trigger", default="agendado", choices=["manual", "agendado", "github"])
    ap.add_argument("--tentativas", type=int, default=None)
    ap.add_argument("--report", action="store_true", help="Somente gerar e salvar o relatório diário")
    ap.add_argument("--excel", type=str, default=None, help="Salvar exportação Excel neste caminho")
    args = ap.parse_args()
    init_db()
    if args.report:
        from modules.reports.daily import build_daily_report, save_daily_report
        print(save_daily_report(build_daily_report()))
        return 0
    result = run_with_retries(mode=args.mode, trigger=args.trigger, max_attempts=args.tentativas)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if args.excel:
        from modules.reports.excel import build_workbook
        Path(args.excel).write_bytes(build_workbook())
    return 1 if result.get("status") == "erro" else 0


if __name__ == "__main__":
    raise SystemExit(main())
