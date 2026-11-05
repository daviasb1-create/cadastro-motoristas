"""Brave Search API (web + notícias). Requer BRAVE_API_KEY."""
from __future__ import annotations

from modules.search.base import BaseSource, RawResult, SearchContext
from modules.search.queries import build_queries
from services import http
from services.textutil import clean_text
from config import settings as cfg

WEB = "https://api.search.brave.com/res/v1/web/search"
NEWS = "https://api.search.brave.com/res/v1/news/search"


def parse_brave(data: dict, query: str, kind: str, key: str, name: str) -> list[RawResult]:
    items = (data.get("web") or {}).get("results") or data.get("results") or []
    out = []
    for it in items:
        out.append(RawResult(
            source_key=key, source_name=name, title=clean_text(it.get("title"), 400),
            url=it.get("url", ""), snippet=clean_text(it.get("description"), 800),
            kind=kind, query=query, extra={"idade": it.get("age") or it.get("page_age")},
        ))
    return out


class BraveSource(BaseSource):
    key = "brave"
    name = "Brave Search API"
    requires = ("BRAVE_API_KEY",)
    description = "Busca web e notícias (inclui vagas e pedidos de cotação públicos)."

    def search(self, ctx: SearchContext) -> list[RawResult]:
        headers = {"X-Subscription-Token": cfg.env("BRAVE_API_KEY"), "Accept": "application/json"}
        n = self.budget(ctx.max_queries)
        results: list[RawResult] = []
        for q in build_queries(ctx.settings, ctx.mode, n, salt=self.key):
            endpoint = NEWS if q["kind"] == "noticia" else WEB
            params = {"q": q["q"], "country": "BR", "search_lang": "pt-br", "count": 20,
                      "freshness": "pw" if ctx.mode == "urgente" else "pm"}
            resp = http.get(endpoint, headers=headers, params=params)
            self.track()
            if resp.status_code in (401, 403):
                raise http.SourceUnavailable("Credencial Brave inválida ou sem plano ativo")
            if resp.status_code == 429:
                raise http.SourceUnavailable("Limite da Brave API atingido")
            if resp.status_code != 200:
                raise http.SourceUnavailable(f"HTTP {resp.status_code}")
            results.extend(parse_brave(resp.json(), q["q"], q["kind"], self.key, self.name))
        return results
