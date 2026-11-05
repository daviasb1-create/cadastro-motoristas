from datetime import timedelta

import pytest
from sqlalchemy import func, select

from modules.search.base import BaseSource, RawResult
from services.timeutil import now, today


class FakeSource(BaseSource):
    key = "google_news"
    name = "Fonte de teste"

    def search(self, ctx):
        self.track()
        return [
            RawResult(source_key=self.key, source_name=self.name, kind="noticia",
                      title="Móveis Aurora inaugura novo centro de distribuição em Joinville",
                      url="https://www.moveisaurora.com.br/noticias/cd-joinville",
                      snippet="A Móveis Aurora inaugura CD em Joinville. Contato comercial: logistica@moveisaurora.com.br, (47) 99876-5432.",
                      published_at=now()),
            RawResult(source_key=self.key, source_name=self.name, kind="licitacao",
                      title="Pregão: contratação de serviço de transporte de cargas",
                      url="https://pncp.gov.br/app/editais/11222333000181/2026/7",
                      snippet="Contratação de serviço de transporte de cargas entre Rio de Janeiro e São Paulo",
                      extra={"orgao": "Prefeitura Teste", "orgao_cnpj": "11222333000181", "uf": "RJ",
                             "municipio": "NITERÓI", "encerramento": (now() + timedelta(days=5)).isoformat()}),
            RawResult(source_key=self.key, source_name=self.name, kind="noticia",
                      title="Bolsa fecha em alta", url="https://news.example/bolsa", snippet="ações"),
        ]


@pytest.fixture()
def fake_sources(db, monkeypatch):
    from database.db import session_scope
    from database.models import Source
    from modules.search import registry
    from modules.scheduler import pipeline

    monkeypatch.setitem(registry.SOURCE_CLASSES, "google_news", FakeSource)
    monkeypatch.setattr(pipeline, "SOURCE_CLASSES", registry.SOURCE_CLASSES)
    with session_scope() as s:
        for src in s.scalars(select(Source)):
            src.enabled = src.key == "google_news"
    return db


def test_full_pipeline_and_dedup(fake_sources):
    from database.db import session_scope
    from database.models import Company, Lead, Message, Opportunity, SearchRun
    from modules.scheduler.pipeline import run_pipeline

    r1 = run_pipeline(trigger="manual")
    assert r1["status"] in ("ok", "parcial"), r1
    assert r1["novas_oportunidades"] == 2
    with session_scope() as s:
        assert s.scalar(select(func.count(Company.id))) == 2
        aurora = s.scalar(select(Company).where(Company.name == "Móveis Aurora"))
        assert aurora.domain == "moveisaurora.com.br"
        assert any(c.email == "logistica@moveisaurora.com.br" for c in aurora.contacts)
        lead = aurora.lead
        assert lead.status == "Contato identificado"
        msgs = s.scalars(select(Message).where(Message.lead_id == lead.id)).all()
        channels = {m.channel for m in msgs}
        assert channels == {"email", "whatsapp"}
        email = next(m for m in msgs if m.channel == "email")
        assert "Móveis Aurora" in email.body and "—" not in email.body
        assert email.status == "rascunho"
        tender = s.scalar(select(Opportunity).where(Opportunity.category == "licitacao"))
        assert tender.score > 0 and tender.score_breakdown
        assert s.scalar(select(SearchRun).order_by(SearchRun.id.desc())).status in ("ok", "parcial")

    # segunda execução: nada duplicado
    r2 = run_pipeline(trigger="manual")
    assert r2["novas_oportunidades"] == 0
    with session_scope() as s:
        assert s.scalar(select(func.count(Company.id))) == 2
        assert s.scalar(select(func.count(Opportunity.id))) == 2
        assert s.scalar(select(func.count(Lead.id))) == 2
        assert s.scalar(select(func.count(Message.id))) == 3  # 2 e-mails + 1 WhatsApp (só Aurora tem celular)


def test_crm_followups_response_and_optout(fake_sources):
    from database.db import all_settings, session_scope
    from database.models import Company, FollowUp, Message
    from modules.crm import service
    from modules.scheduler.pipeline import run_pipeline

    run_pipeline(trigger="manual")
    settings = all_settings()
    with session_scope() as s:
        lead = s.scalar(select(Company).where(Company.name == "Móveis Aurora")).lead
        msg = s.scalar(select(Message).where(Message.lead_id == lead.id, Message.channel == "email"))
        service.register_contact_made(s, lead, "email", settings, message_id=msg.id)
        assert lead.status == "Aguardando resposta"
        fus = {f.stage: f for f in s.scalars(select(FollowUp).where(FollowUp.lead_id == lead.id))}
        assert set(fus) == {"fu_1", "fu_2", "fu_3", "reativacao_1", "reativacao_2"}
        assert fus["fu_1"].due_date == today() + timedelta(days=3)
        assert msg.status == "enviado"
        lead_id = lead.id

    # follow-up vencido gera nova mensagem automaticamente (sem duplicar)
    with session_scope() as s:
        f = s.scalar(select(FollowUp).where(FollowUp.lead_id == lead_id, FollowUp.stage == "fu_1"))
        f.due_date = today()
    run_pipeline(trigger="manual")
    with session_scope() as s:
        fu_msgs = s.scalars(select(Message).where(Message.lead_id == lead_id, Message.stage == "fu_1")).all()
        assert len([m for m in fu_msgs if m.channel == "email"]) == 1
        lead = s.get(Company, s.scalar(select(Company.id).where(Company.name == "Móveis Aurora"))).lead
        service.register_response(s, lead, "Pediu cotação SP-Joinville")
        assert lead.status == "Em negociação"
        assert all(f.status != "pendente" for f in lead.followups)
        service.opt_out(s, lead.company, "Solicitou não receber contatos")
        assert lead.status == "Perdido" and lead.company.opt_out


def test_status_validation(db):
    from database.db import session_scope
    from modules.crm import service

    with session_scope() as s:
        c, _ = service.upsert_company(s, name="Teste SA", cnpj=None, website=None, segment=None, city=None,
                                      state="SP", source="manual")
        lead, _ = service.ensure_lead(s, c)
        with pytest.raises(ValueError):
            service.change_status(s, lead, "Inventado")
        service.change_status(s, lead, "Perdido", loss_reason="Preço")
        assert lead.loss_reason == "Preço"


def test_company_dedup_by_cnpj_domain_name(db):
    from database.db import session_scope
    from modules.crm import service

    with session_scope() as s:
        a, created = service.upsert_company(s, name="Aurora Móveis LTDA", cnpj="11.222.333/0001-81", website=None,
                                            segment=None, city=None, state="SC", source="x")
        b, created2 = service.upsert_company(s, name="Outro nome", cnpj="11222333000181", website=None,
                                             segment=None, city=None, state=None, source="y")
        assert a.id == b.id and created and not created2
        c, _ = service.upsert_company(s, name="Site Co", cnpj=None, website="https://www.siteco.com.br",
                                      segment=None, city=None, state=None, source="z")
        d, created4 = service.upsert_company(s, name="Site Company", cnpj=None, website="http://siteco.com.br/contato",
                                             segment=None, city=None, state=None, source="z")
        assert c.id == d.id and not created4
        e, _ = service.upsert_company(s, name="AURORA MOVEIS S.A.", cnpj=None, website=None, segment=None,
                                      city=None, state="SC", source="w")
        assert e.id == a.id


def test_long_strings_are_truncated(db):
    from database.db import session_scope
    from database.models import Company, Opportunity

    with session_scope() as s:
        c = Company(name="X" * 400, normalized_name="x")
        s.add(c)
        s.flush()
        o = Opportunity(company=c, fingerprint="z", title="t", category="empresa", source_name="s",
                        source_url="https://a.com/" + "p" * 2000)
        s.add(o)
        s.flush()
        assert len(c.name) == 255 and len(o.source_url) == 1000
