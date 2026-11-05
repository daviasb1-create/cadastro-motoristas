"""Classificação e envio de alertas sem repetição (1 alerta por oportunidade e canal)."""
from __future__ import annotations

import html
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Message, Notification, Opportunity
from modules.alerts import email_alert, telegram
from modules.crm.service import contact_channels
from services.textutil import format_phone
from services.timeutil import fmt, now

LEVEL_ICON = {"CRITICO": "🔴", "ALTO": "🟠", "NORMAL": "🔵"}


def classify(opp: Opportunity) -> str:
    n = now()
    short_deadline = opp.deadline is not None and 0 <= (opp.deadline - n).days <= 7
    recent = opp.published_at is None or (n - opp.published_at).days <= 3
    if opp.demand_level == "explicita" and recent and (short_deadline or opp.category == "urgente"):
        return "CRITICO"
    if opp.score >= 80 or (opp.demand_level in ("explicita", "forte") and opp.score >= 70):
        return "ALTO"
    return "NORMAL"


def format_alert(s: Session, opp: Opportunity, level: str) -> str:
    c = opp.company
    ch = contact_channels(c)
    contato = []
    if ch["email"]:
        contato.append("E-mail: " + ", ".join(ch["email"][:2]))
    if ch["phone"]:
        contato.append("Tel: " + ", ".join(format_phone(p) for p in ch["phone"][:2]))
    if ch["whatsapp"]:
        contato.append("WhatsApp: " + format_phone(ch["whatsapp"][0]))
    lead = c.lead
    email_msg = wa_msg = None
    if lead:
        email_msg = s.scalar(select(Message).where(Message.lead_id == lead.id, Message.channel == "email",
                                                   Message.stage == "primeiro_contato"))
        wa_msg = s.scalar(select(Message).where(Message.lead_id == lead.id, Message.channel == "whatsapp",
                                                Message.stage == "primeiro_contato"))
    e = html.escape
    lines = [
        f"{LEVEL_ICON.get(level, '')} <b>ALERTA {level}</b> | Score {opp.score}/100",
        f"<b>{e(c.name)}</b> ({e(c.city or 'cidade n/i')}/{e(c.state or 'UF n/i')})",
        f"Tipo: {e(opp.category)} | {e(opp.priority)}",
        f"Resumo: {e((opp.description or opp.title)[:350])}",
    ]
    if opp.origin and opp.destination:
        lines.append(f"Rota: {e(opp.origin)} → {e(opp.destination)}")
    if opp.deadline:
        lines.append(f"Prazo: {fmt(opp.deadline)}")
    lines.append(f"Contato: {e(' | '.join(contato)) if contato else 'Não identificado'}")
    if lead and lead.recommended_service:
        lines.append(f"Recomendação: oferecer {e(lead.recommended_service)}")
    if opp.next_action:
        lines.append(f"Próxima ação: {e(opp.next_action)}")
    lines.append(f"Fonte: {e(opp.source_url or opp.source_name)}")
    if email_msg:
        lines += ["", f"<b>E-mail pronto</b> (assunto: {e(email_msg.subject or '')})", f"<pre>{e(email_msg.body[:1500])}</pre>"]
    if wa_msg:
        lines += ["<b>WhatsApp pronto</b>", f"<pre>{e(wa_msg.body)}</pre>"]
    lines.append("<i>Revise antes de enviar. Nada foi enviado ao cliente.</i>")
    return "\n".join(lines)


def dispatch(s: Session, opportunities: list[Opportunity], settings: dict) -> tuple[int, list[str]]:
    cfg_alert = settings.get("alertas", {})
    min_score = int(settings.get("score", {}).get("minimo_alerta", 60))
    levels = set(cfg_alert.get("niveis", ["CRITICO", "ALTO", "NORMAL"]))
    max_n = int(cfg_alert.get("max_por_execucao", 15))
    channels = []
    if cfg_alert.get("telegram", True) and telegram.configured():
        channels.append("telegram")
    if cfg_alert.get("email", False) and email_alert.configured():
        channels.append("email")
    sent, errors = 0, []
    if not channels:
        return 0, []
    for opp in sorted(opportunities, key=lambda o: -o.score):
        if sent >= max_n:
            break
        if opp.company.opt_out:
            continue
        level = classify(opp)
        if opp.score < min_score and level != "CRITICO":
            continue
        if level not in levels:
            continue
        for ch in channels:
            prev = s.scalar(select(Notification).where(Notification.opportunity_id == opp.id, Notification.channel == ch))
            if prev and prev.status == "enviado":
                continue
            text = format_alert(s, opp, level)
            row = prev or Notification(opportunity_id=opp.id, channel=ch, level=level, status="erro")
            if not prev:
                s.add(row)
            try:
                if ch == "telegram":
                    telegram.send(text)
                else:
                    email_alert.send(f"[{level}] {opp.company.name} | score {opp.score}",
                                     re.sub(r"<[^>]+>", "", html.unescape(text)))
                row.status, row.error, row.level = "enviado", None, level
                sent += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{ch}: {exc}")
                row.status, row.error = "erro", str(exc)[:500]
        s.flush()
    return sent, errors


def send_daily_summary(text: str, settings: dict) -> list[str]:
    errors = []
    cfg_alert = settings.get("alertas", {})
    if cfg_alert.get("telegram", True) and telegram.configured():
        try:
            telegram.send(text)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"telegram: {exc}")
    if cfg_alert.get("email", False) and email_alert.configured():
        try:
            email_alert.send("Relatório diário: LOGISTICS INTELLIGENCE", re.sub(r"<[^>]+>", "", html.unescape(text)))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"email: {exc}")
    return errors
