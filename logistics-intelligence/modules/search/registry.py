"""Registro das fontes. Para adicionar uma nova fonte: crie a classe (herdando de
BaseSource), importe aqui e acrescente em SOURCE_DEFINITIONS."""
from __future__ import annotations

from modules.search.base import BaseSource
from modules.search.brave import BraveSource
from modules.search.claude_web import ClaudeWebSource
from modules.search.google_news import GoogleNewsSource
from modules.search.pncp import PNCPSource
from modules.search.rss_custom import CustomRSSSource
from modules.search.serper import SerperSource

SOURCE_CLASSES: dict[str, type[BaseSource]] = {
    c.key: c for c in (GoogleNewsSource, PNCPSource, BraveSource, SerperSource, ClaudeWebSource, CustomRSSSource)
}

SOURCE_DEFINITIONS = [
    {"key": "google_news", "name": GoogleNewsSource.name, "daily_limit": 60, "enabled": True},
    {"key": "pncp", "name": PNCPSource.name, "daily_limit": 120, "enabled": True,
     "config": {"paginas_por_uf": 3}},
    {"key": "brave", "name": BraveSource.name, "daily_limit": 60, "enabled": True},
    {"key": "serper", "name": SerperSource.name, "daily_limit": 60, "enabled": True},
    {"key": "claude_web", "name": ClaudeWebSource.name, "daily_limit": 4, "enabled": True},
    {"key": "rss_custom", "name": CustomRSSSource.name, "daily_limit": 50, "enabled": False,
     "config": {"feeds": []}},
]


def build_source(key: str, config: dict | None = None) -> BaseSource:
    return SOURCE_CLASSES[key](config)
