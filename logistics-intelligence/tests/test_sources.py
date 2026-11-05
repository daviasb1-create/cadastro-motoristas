from pathlib import Path

from modules.search.brave import parse_brave
from modules.search.google_news import parse_feed
from modules.search.pncp import is_cargo_object, parse_pncp
from modules.search.queries import build_queries
from modules.search.serper import parse_serper
from config.defaults import DEFAULT_SETTINGS

FIX = Path(__file__).parent / "fixtures"


def test_google_news_rss():
    items = parse_feed((FIX / "google_news.xml").read_text(encoding="utf-8"), "q", "noticia", "google_news", "GN")
    assert len(items) == 2
    assert items[0].title.startswith("Móveis Aurora inaugura")
    assert items[0].published_at is not None
    assert items[0].extra["publicador"] == "Jornal Exemplo"


def test_brave_and_serper():
    b = parse_brave({"web": {"results": [{"title": "T", "url": "https://a.com", "description": "<b>d</b>"}]}}, "q", "web", "brave", "B")
    assert b[0].snippet == "d"
    s = parse_serper({"organic": [{"title": "T", "link": "https://b.com", "snippet": "s"}]}, "q", "web", "serper", "S")
    assert s[0].url == "https://b.com"


def test_pncp_filters_cargo_objects():
    data = {"data": [
        {"objetoCompra": "Contratação de serviço de transporte de cargas e mudança de mobiliário",
         "orgaoEntidade": {"cnpj": "11222333000181", "razaoSocial": "Prefeitura Teste"},
         "unidadeOrgao": {"ufSigla": "RJ", "municipioNome": "Niterói"}, "anoCompra": 2026, "sequencialCompra": 7,
         "dataEncerramentoProposta": "2026-11-20T10:00:00", "modalidadeNome": "Pregão - Eletrônico",
         "valorTotalEstimado": 150000.0},
        {"objetoCompra": "Contratação de transporte escolar", "orgaoEntidade": {}, "unidadeOrgao": {}},
    ], "paginasRestantes": 0}
    out = parse_pncp(data, ["transporte", "frete"], "pncp", "PNCP")
    assert len(out) == 1
    assert out[0].url == "https://pncp.gov.br/app/editais/11222333000181/2026/7"
    assert out[0].extra["uf"] == "RJ"
    assert not is_cargo_object("aquisição de passagens aéreas", ["transporte"])


def test_queries_rotate_and_cover_modes():
    q = build_queries(DEFAULT_SETTINGS, "completa", 10)
    assert len(q) == 10 and all("q" in x and "kind" in x for x in q)
    u = build_queries(DEFAULT_SETTINGS, "urgente", 5)
    assert all(x["kind"] == "cotacao" for x in u)
