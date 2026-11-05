"""Mensagens curtas de WhatsApp (nunca enviadas automaticamente)."""
from __future__ import annotations

from urllib.parse import quote

from modules.email_generator.generator import LeadFacts, variables
from services.textutil import no_dash, whatsapp_number


def generate_whatsapp(f: LeadFacts, templates: dict[str, dict], settings: dict,
                      stage: str = "primeiro_contato") -> dict | None:
    number = whatsapp_number(f.whatsapp) or whatsapp_number(f.telefone)
    if not number:
        return None
    key = "whatsapp_inicial" if stage == "primeiro_contato" else "whatsapp_followup"
    tpl = templates.get(key)
    if not tpl:
        return None
    text = tpl["body"].format_map(variables(f, settings))
    text = " ".join(text.split())
    return {"template_key": key, "subject": None, "body": no_dash(text), "generated_by": "modelo",
            "recipient": number, "recipient_name": f.contato_nome, "recipient_role": f.contato_cargo}


def wa_link(number: str | None, text: str) -> str | None:
    n = whatsapp_number(number)
    if not n:
        return None
    return f"https://wa.me/{n}?text={quote(text)}"
