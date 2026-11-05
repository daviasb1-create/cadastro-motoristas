"""Caminhos com IA usando respostas simuladas da Claude (sem rede e sem custo)."""
from modules.ai import claude
from modules.enrichment import extractor
from modules.search.base import RawResult, SearchContext
from config.defaults import DEFAULT_SETTINGS


def _item(**kw):
    base = {k: "" for k in extractor.ITEM_SCHEMA["properties"]}
    base.update(index=0, relevante=True, categoria="urgente", frequencia="semanal", nivel_demanda="explicita")
    base.update(kw)
    return base


def test_ai_extraction_validates_output(monkeypatch):
    monkeypatch.setattr(claude, "available", lambda: True)
    raw = [RawResult("brave", "Brave", "Eletro Sul busca transportadora para fretes SP x Joinville", "https://eletrosul.com.br/cotacao",
                     "Eletro Sul busca transportadora: fretes semanais de São Paulo para Joinville. compras@eletrosul.com.br",
                     kind="cotacao"),
           RawResult("brave", "Brave", "Mercado logístico cresce", "https://portal.com/x", "setor cresce", kind="noticia")]

    def fake_call_json(system, user, schema, **kw):
        assert "Não use o caractere travessão" in system
        return {"itens": [
            _item(index=0, empresa_nome="Eletro Sul", contato_email="compras@eletrosul.com.br",
                  contato_telefone="11999990000", origem="São Paulo", destino="Joinville",
                  evidencia="busca transportadora: fretes semanais de São Paulo para Joinville", prazo="2026-11-20"),
            _item(index=1, empresa_nome="Empresa Inventada SA"),
            _item(index=7, empresa_nome="Fora do lote"),
        ]}

    monkeypatch.setattr(claude, "call_json", fake_call_json)
    out = extractor.extract(raw, use_ai=True)
    assert len(out) == 1
    ex = out[0]
    assert ex.method == "ia" and ex.company_name == "Eletro Sul"
    assert ex.contacts[0]["email"] == "compras@eletrosul.com.br"
    assert ex.contacts[0]["phone"] is None  # telefone não estava na fonte
    assert ex.origin == "São Paulo" and ex.deadline is not None


def test_ai_failure_falls_back_to_heuristic(monkeypatch):
    monkeypatch.setattr(claude, "available", lambda: True)

    def boom(*a, **k):
        raise claude.AIUnavailable("limite")

    monkeypatch.setattr(claude, "call_json", boom)
    raw = [RawResult("g", "G", "Móveis Aurora inaugura novo CD em Joinville", "https://n.com/a",
                     "Móveis Aurora inaugura centro de distribuição", kind="noticia")]
    errors = []
    out = extractor.extract(raw, use_ai=True, on_error=errors.append)
    assert out and out[0].method == "heuristica" and errors


def test_claude_web_discards_unverified_sources(db, monkeypatch):
    from modules.search import claude_web

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-teste")
    data = {"itens": [
        _item(index=0, empresa_nome="Casa Forte Distribuidora", fonte_url="https://casaforte.com.br/noticia",
              fonte_titulo="Casa Forte abre CD em Itajaí", fonte_trecho="Casa Forte Distribuidora abre CD em Itajaí",
              evidencia="Casa Forte Distribuidora abre CD em Itajaí", nivel_demanda="forte", categoria="empresa"),
        _item(index=1, empresa_nome="Fantasma Ltda", fonte_url="https://inventado.com/x", fonte_trecho="Fantasma Ltda"),
    ]}
    monkeypatch.setattr(claude, "web_research", lambda *a, **k: (data, {"https://www.casaforte.com.br/noticia/"}))
    res = claude_web.ClaudeWebSource().search(SearchContext(settings=DEFAULT_SETTINGS))
    assert [r.url for r in res] == ["https://casaforte.com.br/noticia"]
    ex = extractor.extract(res, use_ai=False)
    assert ex and ex[0].company_name == "Casa Forte Distribuidora" and ex[0].method == "ia"


def test_email_ai_rewrite_guardrails(monkeypatch):
    from modules.email_generator import generator as g
    from tests.test_generators_alerts_reports import TPL, _facts

    monkeypatch.setattr(claude, "available", lambda: True)
    settings = {**DEFAULT_SETTINGS, "comercial": {**DEFAULT_SETTINGS["comercial"], "nome": "Ana", "email": "ana@icaro.com.br"}}
    # IA tenta inserir e-mail novo: rascunho original é mantido
    monkeypatch.setattr(claude, "call_json", lambda *a, **k: {"assunto": "X", "corpo": "Fale com vendas@outro.com\nana@icaro.com.br"})
    out = g.generate_email(_facts(), TPL, settings, use_ai=True)
    assert out["generated_by"] == "modelo"
    # IA reescreve corretamente mantendo assinatura: aceito, sem travessão
    def good(*a, **k):
        body = a[1].split("Rascunho:\n", 1)[1].split("\n\n", 1)[1]
        return {"assunto": "Transferências para a Móveis Aurora", "corpo": "Olá — equipe,\n\n" + body}
    monkeypatch.setattr(claude, "call_json", good)
    out = g.generate_email(_facts(), TPL, settings, use_ai=True)
    assert out["generated_by"] == "ia" and "—" not in out["body"]
