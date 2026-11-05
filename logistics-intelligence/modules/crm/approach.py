"""Central de abordagem: gera e guarda os rascunhos de e-mail e WhatsApp por lead.

- Um rascunho por lead + canal + etapa (sem duplicidade).
- Mensagem já marcada como enviada nunca é sobrescrita.
- Nada é enviado: o usuário revisa, copia/abre e registra o envio.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from config.defaults import FOLLOWUP_STAGES
from database.models import Lead, Message, Opportunity, Template
from modules.crm.service import best_contact, contact_channels
from modules.email_generator.generator import LeadFacts, generate_email
from modules.whatsapp_generator.generator import generate_whatsapp
from services.textutil import sha


def load_templates(s: Session) -> dict[str, dict]:
    return {t.key: {"name": t.name, "channel": t.channel, "subject": t.subject, "body": t.body}
            for t in s.scalars(select(Template))}


def best_opportunity(s: Session, lead: Lead) -> Opportunity | None:
    return s.scalar(select(Opportunity).where(Opportunity.company_id == lead.company_id)
                    .order_by(Opportunity.score.desc(), Opportunity.found_at.desc()))


def facts_for(s: Session, lead: Lead) -> LeadFacts:
    company = lead.company
    opp = best_opportunity(s, lead)
    contact = best_contact(company)
    ch = contact_channels(company)
    raw = (opp.raw or {}) if opp else {}
    return LeadFacts(
        empresa=company.name, segmento=company.segment, categoria=opp.category if opp else "empresa",
        servico=lead.recommended_service or "transporte rodoviário de cargas e distribuição regional",
        contato_nome=contact.name if contact else None, contato_cargo=contact.role if contact else None,
        email=(contact.email if contact and contact.email else (ch["email"][0] if ch["email"] else None)),
        telefone=(contact.phone if contact and contact.phone else (ch["phone"][0] if ch["phone"] else None)),
        whatsapp=(contact.whatsapp if contact and contact.whatsapp else (ch["whatsapp"][0] if ch["whatsapp"] else None)),
        fonte_kind=raw.get("kind"), fonte_nome=opp.source_name if opp else None,
        fonte_titulo=opp.title if opp else None, fonte_url=opp.source_url if opp else None,
        publicador=raw.get("publicador"), prazo=opp.deadline if opp else None,
        origem=opp.origin if opp else None, destino=opp.destination if opp else None,
        demand_level=opp.demand_level if opp else None, evidencia=opp.evidence if opp else None,
        orgao=raw.get("orgao"),
    )


def _save(s: Session, lead: Lead, channel: str, stage: str, data: dict, opp_id: int | None,
          force: bool) -> Message | None:
    content_hash = sha(channel, data.get("subject"), data["body"])
    existing = s.scalar(select(Message).where(Message.lead_id == lead.id, Message.channel == channel,
                                              Message.stage == stage))
    if existing:
        if existing.status != "rascunho" or not force:
            return None
        if existing.content_hash == content_hash:
            return None
    # mesmo texto já usado em outra etapa deste lead? não repete
    dup = s.scalar(select(Message).where(Message.lead_id == lead.id, Message.content_hash == content_hash))
    if dup and (not existing or dup.id != existing.id):
        return None
    msg = existing or Message(lead=lead, channel=channel, stage=stage)
    msg.opportunity_id = opp_id
    msg.template_key = data.get("template_key")
    msg.recipient = data.get("recipient")
    msg.recipient_name = data.get("recipient_name")
    msg.recipient_role = data.get("recipient_role")
    msg.subject = data.get("subject")
    msg.body = data["body"]
    msg.content_hash = content_hash
    msg.generated_by = data.get("generated_by", "modelo")
    msg.status = "rascunho"
    if not existing:
        s.add(msg)
    s.flush()
    return msg


def generate_for_lead(s: Session, lead: Lead, settings: dict, stage: str = "primeiro_contato",
                      use_ai: bool = True, force: bool = False, template_key: str | None = None) -> list[Message]:
    if lead.company.opt_out:
        return []
    templates = load_templates(s)
    facts = facts_for(s, lead)
    opp = best_opportunity(s, lead)
    tkey = template_key or FOLLOWUP_STAGES.get(stage, {}).get("template")
    created: list[Message] = []
    has_email_draft = s.scalar(select(Message.id).where(Message.lead_id == lead.id, Message.channel == "email",
                                                       Message.stage == stage))
    if force or not has_email_draft:
        email = generate_email(facts, templates, settings, use_ai=use_ai, template_key=tkey)
        m = _save(s, lead, "email", stage, email, opp.id if opp else None, force)
        if m:
            created.append(m)
    wa_stage = "primeiro_contato" if stage == "primeiro_contato" else "followup"
    wa = generate_whatsapp(facts, templates, settings, stage=wa_stage)
    if wa:
        m = _save(s, lead, "whatsapp", stage, wa, opp.id if opp else None, force)
        if m:
            created.append(m)
    return created


def messages_of(s: Session, lead: Lead, stage: str | None = None) -> list[Message]:
    q = select(Message).where(Message.lead_id == lead.id)
    if stage:
        q = q.where(Message.stage == stage)
    return list(s.scalars(q.order_by(Message.created_at.desc())))
