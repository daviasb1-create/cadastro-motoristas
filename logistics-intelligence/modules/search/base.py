"""Contrato comum das fontes de pesquisa."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from config import settings as cfg
from services import usage
from services.textutil import canonical_url, sha


@dataclass
class RawResult:
    source_key: str
    source_name: str
    title: str
    url: str
    snippet: str = ""
    published_at: datetime | None = None
    kind: str = "web"  # noticia | vaga | licitacao | web | cotacao | ia
    query: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        return sha(canonical_url(self.url) or self.title)


@dataclass
class SearchContext:
    settings: dict
    mode: str = "completa"  # completa | urgente
    run_id: int | None = None
    max_queries: int = 10


class BaseSource:
    key: str = ""
    name: str = ""
    requires: tuple[str, ...] = ()
    description: str = ""

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    def missing_credentials(self) -> list[str]:
        return [k for k in self.requires if not cfg.is_configured(k)]

    def budget(self, wanted: int) -> int:
        return min(wanted, usage.remaining_today(self.key))

    def track(self, calls: int = 1, **kw) -> None:
        usage.record(self.key, calls=calls, **kw)

    def search(self, ctx: SearchContext) -> list[RawResult]:  # pragma: no cover - interface
        raise NotImplementedError
