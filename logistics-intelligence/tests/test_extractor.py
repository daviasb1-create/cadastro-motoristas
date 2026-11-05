from modules.enrichment.extractor import extract, extract_heuristic, is_relevant, validate_item
from modules.search.base import RawResult


def _raw(**kw):
    base = dict(source_key="t", source_name="Teste", title="Móveis Aurora inaugura novo centro de distribuição em Joinville",
                url="https://news.example/abc", snippet="A Móveis Aurora inaugura CD em Joinville para abastecer Rio de Janeiro e São Paulo.",
                kind="noticia")
    base.update(kw)
    return RawResult(**base)


def test_relevance():
    assert is_relevant(_raw())
    assert not is_relevant(_raw(title="Bolsa fecha em alta", snippet="ações sobem"))


def test_heuristic_extracts_company_and_strong_signal():
    ex = extract_heuristic(_raw())
    assert ex is not None
    assert ex.company_name == "Móveis Aurora"
    assert ex.demand_level == "forte"
    assert ex.city == "Joinville" and ex.state == "SC"


def test_validate_rejects_invented_data():
    item = {"empresa_nome": "Empresa Fantasma", "evidencia": "x", "categoria": "empresa"}
    assert validate_item(item, _raw(), "ia") is None
    item = {"empresa_nome": "Móveis Aurora", "contato_email": "diretor@aurora.com.br",
            "contato_telefone": "21999998888", "volume": "500 toneladas", "categoria": "transferencia",
            "evidencia": "inaugura CD em Joinville", "nivel_demanda": "forte", "frequencia": "diaria"}
    ex = validate_item(item, _raw(), "ia")
    assert ex is not None
    assert ex.contacts == []           # e-mail/telefone não estão no texto
    assert ex.volume is None           # volume não está no texto
    assert ex.category == "transferencia"


def test_licitacao_uses_official_data():
    r = _raw(kind="licitacao", title="Pregão: transporte de cargas", snippet="transporte de cargas",
             extra={"orgao": "Prefeitura Teste", "orgao_cnpj": "11222333000181", "uf": "RJ",
                    "municipio": "NITERÓI", "encerramento": "2026-12-01T10:00:00"})
    ex = extract([r], use_ai=False)[0]
    assert ex.company_name == "Prefeitura Teste"
    assert ex.category == "licitacao" and ex.cnpj == "11222333000181" and ex.deadline is not None
