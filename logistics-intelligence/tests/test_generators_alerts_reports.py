from modules.email_generator.generator import (LeadFacts, choose_template, generate_email, outlook_web_link)
from modules.whatsapp_generator.generator import generate_whatsapp, wa_link
from config.defaults import DEFAULT_SETTINGS, DEFAULT_TEMPLATES

TPL = {t["key"]: {"subject": t["assunto"], "body": t["corpo"], "channel": t["canal"]} for t in DEFAULT_TEMPLATES}


def _facts(**kw):
    base = dict(empresa="Móveis Aurora", segmento="Móveis", categoria="transferencia",
                servico="transferências recorrentes entre unidades", contato_nome=None, contato_cargo=None,
                email="logistica@aurora.com.br", telefone="47998765432", whatsapp=None, fonte_kind="noticia",
                fonte_nome="GN", fonte_titulo="Móveis Aurora inaugura CD em Joinville", fonte_url="https://x",
                publicador=None, prazo=None, origem="SP", destino="SC", demand_level="forte",
                evidencia="inaugura CD")
    base.update(kw)
    return LeadFacts(**base)


def test_template_choice():
    assert choose_template(_facts()) == "transferencias"
    assert choose_template(_facts(categoria="licitacao", origem=None, destino=None, demand_level="explicita")) == "resposta_cotacao"
    assert choose_template(_facts(categoria="urbana", origem=None, destino=None, fonte_titulo="e-commerce cresce")) == "ecommerce"
    assert choose_template(_facts(categoria="empresa", origem=None, destino=None, contato_cargo="Gerente de Logística")) == "gestor_logistica"


def test_email_generation_without_ai():
    settings = {**DEFAULT_SETTINGS, "comercial": {**DEFAULT_SETTINGS["comercial"], "nome": "Ana Souza",
                                                   "telefone": "(21) 90000-0000", "email": "ana@icaro.com.br"}}
    out = generate_email(_facts(), TPL, settings, use_ai=False)
    assert out["generated_by"] == "modelo"
    assert "Móveis Aurora" in out["subject"] + out["body"]
    assert "Ana Souza" in out["body"]
    assert "{" not in out["body"] and "—" not in out["body"]
    assert "conversamos" not in out["body"].lower()  # não simula relacionamento prévio
    link = outlook_web_link(out["recipient"], out["subject"], out["body"])
    assert link.startswith("https://outlook.office.com/mail/deeplink/compose?to=logistica%40aurora.com.br")


def test_whatsapp_only_for_mobile():
    wa = generate_whatsapp(_facts(), TPL, DEFAULT_SETTINGS)
    assert wa and wa["recipient"] == "5547998765432" and wa["body"].endswith("?")
    assert generate_whatsapp(_facts(telefone="4733334444"), TPL, DEFAULT_SETTINGS) is None
    assert wa_link("47998765432", "oi") == "https://wa.me/5547998765432?text=oi"


def test_alert_dispatch_no_duplicates(db, monkeypatch):
    from sqlalchemy import select

    from database.db import all_settings, session_scope
    from database.models import Opportunity
    from modules.alerts import dispatcher, telegram
    from modules.crm import service

    sent = []
    monkeypatch.setattr(telegram, "configured", lambda: True)
    monkeypatch.setattr(telegram, "send", lambda text: sent.append(text))
    with session_scope() as s:
        c, _ = service.upsert_company(s, name="Aurora", cnpj=None, website=None, segment=None, city="Joinville",
                                      state="SC", source="x")
        opp = Opportunity(company=c, fingerprint="f1", title="Cotação de frete SP-SC", category="urgente",
                          demand_level="explicita", source_name="t", score=85, priority="Oportunidade prioritária")
        s.add(opp)
        s.flush()
        n1, _ = dispatcher.dispatch(s, [opp], all_settings())
        n2, _ = dispatcher.dispatch(s, [opp], all_settings())
    assert n1 == 1 and n2 == 0 and "ALERTA CRITICO" in sent[0]


def test_excel_and_daily_report(db):
    from io import BytesIO

    from openpyxl import load_workbook

    from modules.reports.daily import build_daily_report
    from modules.reports.excel import build_workbook

    wb = load_workbook(BytesIO(build_workbook()))
    for name in ["Todos os leads", "Prioritárias", "Transferências", "Entregas urbanas", "Contatos identificados",
                 "Follow-ups", "Pipeline comercial", "Desempenho"]:
        assert name in wb.sheetnames
    assert "Resumo executivo" in build_daily_report()


def test_logs_redact_secrets(monkeypatch):
    from services.logger import redact

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:SECRETVALUEabc")
    assert "SECRETVALUE" not in redact("erro com token 123456:SECRETVALUEabc")
    assert "sk-ant-" not in redact("chave sk-ant-api03-xyz")
