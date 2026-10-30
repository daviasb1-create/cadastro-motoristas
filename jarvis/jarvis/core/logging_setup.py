"""Configuração de logs com rotação. Nunca registra tokens ou conteúdo de mensagens."""
from __future__ import annotations

import logging
import logging.handlers
import re
import sys

from . import paths

_SECRET_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9\-\._~\+/]+=*", re.I),
    re.compile(r"(sk-ant-[a-z0-9]*-)[A-Za-z0-9_\-]+", re.I),
    re.compile(r"(sk-[a-z]+-)[A-Za-z0-9_\-]{8,}", re.I),  # outras chaves no formato sk-<serviço>-... (ex.: Fish Audio)
    re.compile(r"(FISH_AUDIO_API_KEY\s*[=:]\s*)\S+", re.I),
    re.compile(r"((?:access|refresh|id)_token[\"'=:\s]+)[^\s\"'&,]+", re.I),
]


class RedactingFilter(logging.Filter):
    """Remove credenciais que eventualmente apareçam em mensagens de log."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        redacted = message
        for pattern in _SECRET_PATTERNS:
            redacted = pattern.sub(r"\1***", redacted)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def setup_logging(level: str = "INFO", console: bool = True) -> None:
    root = logging.getLogger()
    if getattr(root, "_jarvis_configured", False):
        return
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(threadName)-14s %(name)s: %(message)s")
    file_handler = logging.handlers.RotatingFileHandler(
        paths.logs_dir() / "jarvis.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler.addFilter(RedactingFilter())
    root.addHandler(file_handler)
    if console and sys.stderr is not None:
        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        stream.addFilter(RedactingFilter())
        root.addHandler(stream)
    for noisy in ("httpx", "httpcore", "msal", "urllib3", "asyncio", "comtypes", "anthropic", "httpx2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    root._jarvis_configured = True  # type: ignore[attr-defined]
