"""Feeds RSS adicionais configurados pelo usuário (portais de logística, associações etc.)."""
from __future__ import annotations

from modules.search.base import BaseSource, RawResult, SearchContext
from modules.search.google_news import parse_feed
from services import http
from services.textutil import strip_accents

SIGNALS = ("centro de distribuicao", " cd ", "fabrica", "inaugura", "expansao", "amplia", "nova unidade",
           "transportadora", "frete", "logistic", "armazem", "galpao", "distribuicao", "e-commerce")


class CustomRSSSource(BaseSource):
    key = "rss_custom"
    name = "Feeds RSS personalizados"
    description = "Adicione URLs de feeds em Configurações > Fontes (campo 'feeds')."

    def search(self, ctx: SearchContext) -> list[RawResult]:
        feeds: list[str] = self.config.get("feeds", [])
        results: list[RawResult] = []
        for url in feeds[: self.budget(len(feeds))]:
            resp = http.get(url)
            self.track()
            if resp.status_code != 200:
                continue
            for r in parse_feed(resp.text, url, "noticia", self.key, self.name):
                t = " " + strip_accents((r.title + " " + r.snippet).lower()) + " "
                if any(sig in t for sig in SIGNALS):
                    results.append(r)
        return results
