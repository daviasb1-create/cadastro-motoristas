"""Serper.dev (resultados do Google via API oficial do serviço). Requer SERPER_API_KEY."""
from __future__ import annotations

from modules.search.base import BaseSource, RawResult, SearchContext
from modules.search.queries import build_queries
from services import http
from services.textutil import clean_text
from config import settings as cfg

WEB = "https://google.serper.dev/search"
NEWS = "https://google.serper.dev/news"


def parse_serper(data: dict, query: str, kind: str, key: str, name: str) -> list[RawResult]:
    items = data.get("news") or data.get("organic") or []
    out = []
    for it in items:
        out.append(RawResult(
            source_key=key, source_name=name, title=clean_text(it.get("title"), 400),
            url=it.get("link", ""), snippet=clean_text(it.get("snippet"), 800), kind=kind,
            query=query, extra={"data": it.get("date"), "publicador": it.get("source")},
        ))
    return out


class SerperSource(BaseSource):
    key = "serper"
    name = "Serper.dev (Google)"
    requires = ("SERPER_API_KEY",)
    description = "Resultados do Google para web e notícias."

    def search(self, ctx: SearchContext) -> list[RawResult]:
        headers = {"X-API-KEY": cfg.env("SERPER_API_KEY"), "Content-Type": "application/json"}
        n = self.budget(ctx.max_queries)
        results: list[RawResult] = []
        for q in build_queries(ctx.settings, ctx.mode, n, salt=self.key):
            endpoint = NEWS if q["kind"] == "noticia" else WEB
            body = {"q": q["q"], "gl": "br", "hl": "pt-br", "num": 20,
                    "tbs": "qdr:w" if ctx.mode == "urgente" else "qdr:m"}
            resp = http.post(endpoint, headers=headers, json=body)
            self.track()
            if resp.status_code in (401, 403):
                raise http.SourceUnavailable("Credencial Serper inválida ou sem créditos")
            if resp.status_code != 200:
                raise http.SourceUnavailable(f"HTTP {resp.status_code}")
            results.extend(parse_serper(resp.json(), q["q"], q["kind"], self.key, self.name))
        return results
