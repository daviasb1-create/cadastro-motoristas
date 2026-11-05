"""Logs em arquivo + banco, com remoção automática de credenciais."""
from __future__ import annotations

import logging
import os
import re
from logging.handlers import RotatingFileHandler

from config import settings as cfg

_SECRET_KEYS = [k for k in cfg.CREDENTIALS if any(w in k for w in ("KEY", "TOKEN", "SECRET", "PASSWORD", "DATABASE_URL"))]
_TOKEN_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]+"),
    re.compile(r"bot\d+:[A-Za-z0-9_\-]+"),
]


def redact(text: str) -> str:
    if not text:
        return text
    for key in _SECRET_KEYS:
        val = os.getenv(key)
        if val and len(val) >= 6:
            text = text.replace(val, f"[{key} oculto]")
    for pat in _TOKEN_PATTERNS:
        text = pat.sub("[credencial oculta]", text)
    return text


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if record.args:
            record.args = tuple(redact(str(a)) for a in record.args)
        return True


def get_logger(name: str = "li") -> logging.Logger:
    logger = logging.getLogger(name)
    if getattr(logger, "_li_configured", False):
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    fh = RotatingFileHandler(cfg.LOG_DIR / "logistics_intelligence.log", maxBytes=2_000_000,
                             backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.addFilter(_RedactFilter())
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    sh.addFilter(_RedactFilter())
    logger.addHandler(fh)
    logger.addHandler(sh)
    logger.propagate = False
    logger._li_configured = True  # type: ignore[attr-defined]
    return logger


def db_log(run_id: int | None, level: str, component: str, message: str) -> None:
    """Registra no banco (aparece no Histórico de pesquisas) e no arquivo."""
    from database.db import session_scope
    from database.models import ExecutionLog

    message = redact(message)[:4000]
    get_logger(component).log(getattr(logging, level.upper(), logging.INFO), message)
    try:
        with session_scope() as s:
            s.add(ExecutionLog(run_id=run_id, level=level.upper(), component=component, message=message))
    except Exception:  # log nunca pode derrubar a execução
        pass
