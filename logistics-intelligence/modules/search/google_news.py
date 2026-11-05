"""Google Notícias via RSS público (gratuito, sem chave).

Fonte de sinais de expansão: novos CDs, fábricas, inaugurações, contratos.
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote_plus

import feedparser

from modules.search.base import BaseSource, RawResult, SearchContext
from modules.search.queries import build_queries
from services import http
from services.textutil import clean_text
from services.timeutil import to_local

FEED = "https://news.google.com/rss/search?q={q}+when:{days}d&hl=pt-BR&gl=BR&ceid=BR:pt-419"


def parse_feed(xml: str, query: str, kind: str, key: str, name: str) -> list[RawResult]:
    feed = feedparser.parse(xml)
    out: list[RawResult] = []
    for e in feed.entries:
        published = None
        if getattr(e, "published_parsed", None):
            published = to_local(datetime(*e.published_parsed[:6], tzinfo=timezone.utc))
        publisher = ""
        if getattr(e, "source", None):
            publisher = e.source.get("title", "")
        out.append(RawResult(
            source_key=key, source_name=name, title=clean_text(e.get("title", ""), 400),
            url=e.get("link", ""), snippet=clean_text(e.get("summary", ""), 800),
            published_at=published, kind=kind, query=query, extra={"publicador": publisher},
        ))
    return out


class GoogleNewsSource(BaseSource):
    key = "google_news"
    name = "Google Notícias (RSS)"
    description = "Notícias de expansão, novos CDs e operações. Gratuito, sem chave."

    def search(self, ctx: SearchContext) -> list[RawResult]:
        n = self.budget(ctx.max_queries)
        days = 3 if ctx.mode == "urgente" else 14
        results: list[RawResult] = []
        queries = [q for q in build_queries(ctx.settings, ctx.mode, n * 2, salt=self.key) if q["kind"] != "vaga"][:n]
        for q in queries:
            resp = http.get(FEED.format(q=quote_plus(q["q"]), days=days))
            self.track()
            if resp.status_code != 200:
                raise http.SourceUnavailable(f"HTTP {resp.status_code}")
            results.extend(parse_feed(resp.text, q["q"], q["kind"] if q["kind"] != "cotacao" else "noticia",
                                      self.key, self.name)[:15])
        return results
