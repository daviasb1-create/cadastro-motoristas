"""CRM: empresas, leads, contatos, histórico, pipeline e follow-ups."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from config.defaults import CRM_STATUSES, FOLLOWUP_STAGES
from database.models import (Company, Contact, FollowUp, History, Lead, Message, Opportunity,
                             PipelineEvent)
from services.textutil import (domain_of, format_phone, is_company_domain, is_mobile,
                               normalize_name, only_digits, valid_cnpj)
from services.timeutil import now, today

AUTO_STATUSES = {"Novo lead", "Pesquisando contato", "Contato identificado"}


# --------------------------------------------------------------------------- empresas

def find_company(s: Session, name: str, cnpj: str | None = None, website: str | None = None,
                 state: str | None = None) -> Company | None:
    """Deduplicação: CNPJ > domínio > nome normalizado (+UF quando conhecida)."""
    if cnpj and valid_cnpj(cnpj):
        c = s.scalar(select(Company).where(Company.cnpj == only_digits(cnpj)))
        if c:
            return c
    dom = domain_of(website)
    if dom and is_company_domain(dom):
        c = s.scalar(select(Company).where(Company.domain == dom))
        if c:
            return c
    norm = normalize_name(name)
    if not norm:
        return None
    candidates = list(s.scalars(select(Company).where(Company.normalized_name == norm)))
    if not candidates:
        return None
    if state:
        for c in candidates:
            if c.state in (None, state):
                return c
        return None
    return candidates[0]


def _set_if_empty(company: Company, field: str, value, source: str | None) -> bool:
    if value in (None, "") or getattr(company, field) not in (None, ""):
        return False
    setattr(company, field, value)
    fs = dict(company.field_sources or {})
    fs[field] = source or "Não identificado"
    company.field_sources = fs
    return True


def upsert_company(s: Session, *, name: str, cnpj: str | None, website: str | None, segment: str | None,
                   city: str | None, state: str | None, source: str | None) -> tuple[Company, bool]:
    company = find_company(s, name, cnpj, website, state)
    created = False
    if company is None:
        company = Company(name=name.strip()[:255], normalized_name=normalize_name(name), field_sources={})
        s.add(company)
        created = True
    dom = domain_of(website)
    if cnpj and valid_cnpj(cnpj):
        clash = s.scalar(select(Company).where(Company.cnpj == only_digits(cnpj), Company.id != company.id)) if company.id else None
        if not clash:
            _set_if_empty(company, "cnpj", only_digits(cnpj), source)
    if dom and is_company_domain(dom):
        _set_if_empty(company, "domain", dom, source)
        _set_if_empty(company, "website", website if website.startswith("http") else f"https://{dom}", source)
    _set_if_empty(company, "segment", segment, source)
    _set_if_empty(company, "city", city, source)
    _set_if_empty(company, "state", state, source)
    s.flush()
    return company, created


def add_contact(s: Session, company: Company, *, name=None, role=None, email=None, phone=None,
                whatsapp=None, linkedin=None, department=None, source_name=None, source_url=None,
                is_corporate=True) -> Contact | None:
    email = (email or "").strip().lower() or None
    phone = only_digits(phone) or None
    whatsapp = only_digits(whatsapp) or None
    if not any([email, phone, whatsapp, name, linkedin]):
        return None
    for c in company.contacts:
        if (email and c.email == email) or (phone and c.phone == phone and not email) or \
                (whatsapp and c.whatsapp == whatsapp and not email and not phone):
            # completa dados que faltavam no contato existente
            c.name = c.name or name
            c.role = c.role or role
            c.phone = c.phone or phone
            c.whatsapp = c.whatsapp or whatsapp
            return c
    if not email and not phone and not whatsapp and name:
        for c in company.contacts:
            if c.name and normalize_name(c.name) == normalize_name(name):
                return c
    c = Contact(company=company, name=name, role=role, email=email, phone=phone, whatsapp=whatsapp,
                linkedin_url=linkedin, department=department, source_name=source_name,
                source_url=source_url, is_corporate=is_corporate)
    s.add(c)
    s.flush()
    return c


def best_contact(company: Company) -> Contact | None:
    """Prioriza contato nominal com e-mail; depois e-mails de logística/compras."""
    from services.textutil import email_rank

    def key(c: Contact):
        return (0 if c.name and c.email else 1, 0 if c.email else 1,
                email_rank(c.email) if c.email else 99, 0 if (c.whatsapp or is_mobile(c.phone)) else 1)

    usable = [c for c in company.contacts if c.email or c.phone or c.whatsapp]
    return sorted(usable, key=key)[0] if usable else None


def contact_channels(company: Company) -> dict:
    emails = [c.email for c in company.contacts if c.email]
    phones = [c.phone for c in company.contacts if c.phone]
    wa = [c.whatsapp for c in company.contacts if c.whatsapp] + [p for p in phones if is_mobile(p)]
    return {"email": emails, "phone": phones, "whatsapp": list(dict.fromkeys(wa))}


# --------------------------------------------------------------------------- leads

def ensure_lead(s: Session, company: Company) -> tuple[Lead, bool]:
    if company.lead:
        return company.lead, False
    lead = Lead(company=company, status="Novo lead")
    s.add(lead)
    s.flush()
    s.add(PipelineEvent(lead_id=lead.id, from_status=None, to_status="Novo lead", changed_by="sistema"))
    return lead, True


def refresh_lead(s: Session, lead: Lead) -> None:
    """Recalcula score/prioridade a partir das oportunidades e ajusta status automático."""
    from modules.lead_scoring.scoring import priority_label, recommended_service

    opps = list(s.scalars(select(Opportunity).where(Opportunity.company_id == lead.company_id)
                          .order_by(Opportunity.score.desc())))
    if opps:
        best = opps[0]
        lead.score = best.score
        lead.priority = priority_label(best.score)
        lead.recommended_service = recommended_service(best.category, f"{best.title} {best.description or ''}",
                                                       lead.company.segment)
        routes = {f"{o.origin} → {o.destination}" for o in opps if o.origin and o.destination}
        if routes and not lead.routes:
            lead.routes = ", ".join(sorted(routes))[:500]
    if lead.status in AUTO_STATUSES and not lead.company.opt_out:
        has = bool(contact_channels(lead.company)["email"] or contact_channels(lead.company)["phone"]
                   or contact_channels(lead.company)["whatsapp"])
        target = "Contato identificado" if has else "Pesquisando contato"
        if lead.status == "Novo lead" and not has:
            target = "Pesquisando contato"
        if target != lead.status:
            change_status(s, lead, target, author="sistema")


def change_status(s: Session, lead: Lead, new_status: str, author: str | None = None,
                  note: str | None = None, loss_reason: str | None = None) -> None:
    if new_status not in CRM_STATUSES:
        raise ValueError(f"Status inválido: {new_status}")
    old = lead.status
    if old == new_status and not note:
        return
    lead.status = new_status
    lead.updated_at = now()
    if new_status == "Perdido" and loss_reason:
        lead.loss_reason = loss_reason
    s.add(PipelineEvent(lead_id=lead.id, from_status=old, to_status=new_status, changed_by=author or "usuário"))
    text = f"Status: {old} → {new_status}"
    if loss_reason:
        text += f" | Motivo da perda: {loss_reason}"
    if note:
        text += f" | {note}"
    s.add(History(lead=lead, kind="status", content=text, author=author or "usuário"))
    if new_status in ("Perdido", "Contrato fechado"):
        cancel_followups(s, lead)
    if new_status in ("Cotação solicitada", "Em negociação", "Cotação enviada", "Teste operacional"):
        lead.responded = True
        cancel_followups(s, lead, only_prefix="fu_")


def add_history(s: Session, lead: Lead, kind: str, content: str, channel: str | None = None,
                author: str | None = None) -> None:
    s.add(History(lead=lead, kind=kind, content=content, channel=channel, author=author or "usuário"))
    lead.updated_at = now()


# --------------------------------------------------------------------------- follow-up

def schedule_followups(s: Session, lead: Lead, settings: dict) -> None:
    fu = settings.get("followup", {"dias": [3, 5, 7], "reativacao": [15, 30]})
    base = (lead.first_contact_at or now()).date()
    stages = [("fu_1", fu["dias"][0] if len(fu["dias"]) > 0 else 3),
              ("fu_2", fu["dias"][1] if len(fu["dias"]) > 1 else 5),
              ("fu_3", fu["dias"][2] if len(fu["dias"]) > 2 else 7)]
    for i, d in enumerate(fu.get("reativacao", [15, 30])[:2]):
        stages.append((f"reativacao_{i + 1}", d))
    existing = {f.stage for f in lead.followups}
    for stage, days in stages:
        if stage not in existing:
            s.add(FollowUp(lead=lead, stage=stage, due_date=base + timedelta(days=int(days))))
    s.flush()


def cancel_followups(s: Session, lead: Lead, only_prefix: str | None = None) -> None:
    for f in lead.followups:
        if f.status == "pendente" and (only_prefix is None or f.stage.startswith(only_prefix)):
            f.status = "cancelado"


def register_contact_made(s: Session, lead: Lead, channel: str, settings: dict,
                          message_id: int | None = None, stage: str = "primeiro_contato",
                          author: str | None = None) -> None:
    """Usuário confirma que ENVIOU a mensagem (o sistema nunca envia sozinho)."""
    ts = now()
    lead.last_approach_at = ts
    if message_id:
        msg = s.get(Message, message_id)
        if msg:
            msg.status = "enviado"
            msg.sent_at = ts
            stage = msg.stage
    label = FOLLOWUP_STAGES.get(stage, {}).get("label", stage)
    add_history(s, lead, "abordagem", f"{label} realizado via {channel}", channel=channel, author=author)
    if stage == "primeiro_contato":
        if not lead.first_contact_at:
            lead.first_contact_at = ts
        if lead.status in AUTO_STATUSES or lead.status == "Reativação futura":
            change_status(s, lead, "Aguardando resposta", author=author or "usuário")
        schedule_followups(s, lead, settings)
    else:
        for f in lead.followups:
            if f.stage == stage and f.status == "pendente":
                f.status = "feito"
                f.done_at = ts
        if lead.status in AUTO_STATUSES | {"Primeiro contato realizado"}:
            change_status(s, lead, "Aguardando resposta", author=author or "usuário")
    lead.next_contact_at = next_due_followup(lead)


def next_due_followup(lead: Lead):
    pend = sorted((f.due_date for f in lead.followups if f.status == "pendente"))
    if not pend:
        return None
    from datetime import datetime
    return datetime.combine(pend[0], datetime.min.time()).replace(hour=9)


def register_response(s: Session, lead: Lead, summary: str, author: str | None = None) -> None:
    lead.responded = True
    cancel_followups(s, lead)
    add_history(s, lead, "conversa", f"Empresa respondeu: {summary}", author=author)
    if lead.status in AUTO_STATUSES | {"Primeiro contato realizado", "Aguardando resposta"}:
        change_status(s, lead, "Em negociação", author=author)
    lead.next_contact_at = None


def opt_out(s: Session, company: Company, reason: str, author: str | None = None) -> None:
    """LGPD: descadastro. Interrompe abordagens e follow-ups; mantém registro mínimo."""
    company.opt_out = True
    company.opt_out_reason = reason[:500]
    if company.lead:
        cancel_followups(s, company.lead)
        for m in company.lead.messages:
            if m.status == "rascunho":
                m.status = "descartado"
        change_status(s, company.lead, "Perdido", author=author, loss_reason=f"Descadastro (LGPD): {reason}")


def due_followups(s: Session):
    return list(s.scalars(
        select(FollowUp).join(Lead).join(Company)
        .where(FollowUp.status == "pendente", FollowUp.due_date <= today(), Company.opt_out.is_(False))
        .order_by(FollowUp.due_date)
    ))


def alert_lists(s: Session) -> dict:
    """Listas para o painel de alertas comerciais."""
    base = select(Lead).join(Company).where(Company.opt_out.is_(False))
    closed = ("Contrato fechado", "Perdido")
    no_approach = list(s.scalars(base.where(Lead.last_approach_at.is_(None), Lead.status.not_in(closed),
                                            Lead.score >= 40).order_by(Lead.score.desc())))
    waiting = list(s.scalars(base.where(Lead.status == "Aguardando resposta", Lead.responded.is_(False))))
    responded = list(s.scalars(base.where(Lead.responded.is_(True), Lead.status.not_in(closed))))
    quotes = list(s.scalars(base.where(Lead.status.in_(["Cotação solicitada"]))))
    reactivation = list(s.scalars(base.where(Lead.status == "Reativação futura")))
    return {"sem_abordagem": no_approach, "aguardando": waiting, "responderam": responded,
            "cotacao": quotes, "reativacao": reactivation, "followups_vencidos": due_followups(s)}


def phone_display(p: str | None) -> str:
    return format_phone(p) if p else "Não identificado"


def search_leads(s: Session, text: str | None = None, statuses: list[str] | None = None,
                 states: list[str] | None = None, min_score: int = 0):
    q = select(Lead).join(Company).where(Lead.score >= min_score)
    if text:
        like = f"%{text.lower()}%"
        q = q.where(or_(func.lower(Company.name).like(like), func.lower(Company.segment).like(like),
                        func.lower(Company.city).like(like)))
    if statuses:
        q = q.where(Lead.status.in_(statuses))
    if states:
        q = q.where(Company.state.in_(states))
    return list(s.scalars(q.order_by(Lead.score.desc(), Lead.updated_at.desc())))
