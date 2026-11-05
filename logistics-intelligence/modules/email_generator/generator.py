"""Geração de e-mails comerciais personalizados.

1. Escolhe o modelo mais adequado da biblioteca (editável no painel).
2. Preenche com fatos verificados do lead (nada inventado).
3. Se a Claude estiver configurada, reescreve de forma natural mantendo as
   mesmas informações, sem acrescentar fatos.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote

from modules.ai import claude
from services.textutil import no_dash, strip_accents
from services.timeutil import fmt


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


@dataclass
class LeadFacts:
    empresa: str
    segmento: str | None
    categoria: str
    servico: str
    contato_nome: str | None
    contato_cargo: str | None
    email: str | None
    telefone: str | None
    whatsapp: str | None
    fonte_kind: str | None
    fonte_nome: str | None
    fonte_titulo: str | None
    fonte_url: str | None
    publicador: str | None
    prazo: object | None
    origem: str | None
    destino: str | None
    demand_level: str | None
    evidencia: str | None
    orgao: str | None = None


def choose_template(f: LeadFacts) -> str:
    t = strip_accents(f"{f.fonte_titulo or ''} {f.evidencia or ''} {f.segmento or ''}".lower())
    role = strip_accents((f.contato_cargo or "").lower())
    if any(k in t for k in ("cadastro de transportadora", "homologacao de transportadora", "cadastro de fornecedor")):
        return "cadastro_transportadora"
    if f.categoria in ("urgente", "licitacao") or f.demand_level == "explicita":
        return "resposta_cotacao"
    if f.categoria == "transferencia" or (f.origem and f.destino):
        return "transferencias"
    if any(k in role for k in ("logistic", "transporte", "supply", "operac", "expedic")):
        return "gestor_logistica"
    if any(k in t for k in ("e-commerce", "ecommerce", "loja virtual", "marketplace", "varejo online")):
        return "ecommerce"
    if f.categoria == "urbana":
        return "distribuicao_urbana"
    if "dedicad" in t:
        return "operacao_dedicada"
    if any(k in t for k in ("industria", "fabrica", "fabricante", "manufatura", "planta")):
        return "industria"
    return "apresentacao_inicial"


def _short(text: str | None, n: int = 110) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0] + "..."


def build_context(f: LeadFacts) -> str:
    """Frase de abertura baseada SOMENTE na fonte. Vazia quando não há fato útil."""
    title = _short(f.fonte_titulo)
    if f.publicador and title.endswith(f" - {f.publicador}"):
        title = title[: -len(f" - {f.publicador}")]
    if f.fonte_kind == "licitacao":
        prazo = f", com propostas até {fmt(f.prazo, with_time=False)}" if f.prazo else ""
        return f"Vi no Portal Nacional de Contratações Públicas o processo \"{_short(f.evidencia, 120)}\"{prazo}. "
    if f.demand_level == "explicita" and title:
        return f"Vi a publicação \"{title}\" e gostaria de apresentar uma alternativa de transporte. "
    if f.fonte_kind in ("noticia", "ia", "web") and f.demand_level == "forte" and title:
        onde = f" em {f.publicador}" if f.publicador else ""
        return f"Acompanhei a notícia{onde} \"{title}\". Com a nova operação, imagino que o transporte seja um ponto importante. "
    return ""


def _greeting(f: LeadFacts) -> str:
    if f.contato_nome:
        return f"Olá, {f.contato_nome.split()[0].title()},"
    return f"Olá, equipe da {f.empresa},"


def signature(settings: dict) -> str:
    c = settings.get("comercial", {})
    e = settings.get("empresa", {})
    sig = c.get("assinatura") or "{nome}\n{cargo} | {empresa}\n{telefone}\n{email}"
    out = sig.format_map(_SafeDict(nome=c.get("nome") or "", cargo=c.get("cargo") or "",
                                   empresa=e.get("nome") or "", telefone=c.get("telefone") or e.get("telefone") or "",
                                   email=c.get("email") or e.get("email") or "", site=e.get("site") or ""))
    return "\n".join(line for line in out.splitlines() if line.strip(" |"))


def variables(f: LeadFacts, settings: dict) -> dict:
    e = settings.get("empresa", {})
    c = settings.get("comercial", {})
    rota = f"{f.origem} ↔ {f.destino}" if f.origem and f.destino else "RJ, SP e Joinville"
    ctx = build_context(f)
    servico_curto = re.sub(r"\s*\([^)]*\)", "", f.servico).split(",")[0].strip()
    return _SafeDict(
        saudacao=_greeting(f),
        saudacao_curta=(f"Olá, {f.contato_nome.split()[0].title()}, tudo bem?" if f.contato_nome else "Olá, tudo bem?"),
        empresa=f.empresa, servico=f.servico, servico_curto=servico_curto, contexto=ctx,
        contexto_curto=("Vi a notícia sobre a nova operação de vocês. " if f.demand_level == "forte" and ctx else
                        "Vi a demanda de transporte publicada por vocês. " if f.demand_level == "explicita" and ctx else ""),
        rota=rota, regioes="Rio de Janeiro, São Paulo e Joinville",
        remetente_empresa=e.get("nome") or "nossa empresa", apresentacao=e.get("apresentacao_curta") or "",
        diferenciais=e.get("diferenciais") or "", remetente_nome=c.get("nome") or "",
        assinatura=signature(settings), cargo_contato=f.contato_cargo or "",
        quem_fala=(f"Aqui é {c.get('nome')}, da {e.get('nome') or 'nossa empresa'}" if c.get("nome")
                   else f"Aqui é da equipe comercial da {e.get('nome') or 'nossa empresa'}"),
    )


def fill(template: dict, f: LeadFacts, settings: dict) -> tuple[str, str]:
    v = variables(f, settings)
    subject = (template.get("subject") or "").format_map(v)
    body = template["body"].format_map(v)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return no_dash(subject.strip()), no_dash(body)


SYSTEM_EMAIL = """Você revisa e-mails comerciais B2B de uma transportadora brasileira. Reescreva o \
rascunho para soar natural, humano, direto e profissional, em português do Brasil.

Regras invioláveis:
- Não acrescente fatos, números, clientes, prêmios, prazos ou promessas que não estejam no rascunho ou \
nos fatos fornecidos.
- Não diga ou insinue que já houve contato, conversa ou relacionamento anterior com a empresa.
- Não afirme que a empresa tem uma necessidade que não foi confirmada; use formulações de hipótese.
- Mantenha a assinatura exatamente como está.
- Corpo com no máximo 140 palavras antes da assinatura. Termine com uma pergunta simples.
- Nada de clichês de marketing, emojis, exclamações em excesso ou o caractere travessão."""

EMAIL_SCHEMA = {
    "type": "object",
    "properties": {"assunto": {"type": "string"}, "corpo": {"type": "string"}},
    "required": ["assunto", "corpo"],
    "additionalProperties": False,
}


def personalize_with_ai(subject: str, body: str, f: LeadFacts) -> tuple[str, str] | None:
    facts = (f"Empresa: {f.empresa}\nSegmento: {f.segmento or 'não identificado'}\n"
             f"Serviço recomendado: {f.servico}\nFonte: {f.fonte_titulo or ''} ({f.fonte_url or ''})\n"
             f"Evidência: {f.evidencia or ''}\nContato: {f.contato_nome or 'não identificado'} "
             f"({f.contato_cargo or 'cargo não identificado'})")
    user = f"Fatos verificados:\n{facts}\n\nRascunho:\nAssunto: {subject}\n\n{body}"
    data = claude.call_json(SYSTEM_EMAIL, user, EMAIL_SCHEMA, effort="low", max_tokens=4000)
    if not data or not data.get("corpo"):
        return None
    new_body = no_dash(data["corpo"].strip())
    # proteção: se a IA removeu a assinatura ou incluiu contatos novos, mantém o rascunho
    sig_first = body.strip().splitlines()[-1].strip() if body.strip() else ""
    if sig_first and sig_first not in new_body:
        return None
    allowed = set(re.findall(r"[\w.+-]+@[\w.-]+", body))
    if set(re.findall(r"[\w.+-]+@[\w.-]+", new_body)) - allowed:
        return None
    return no_dash(data["assunto"].strip()) or subject, new_body


def generate_email(f: LeadFacts, templates: dict[str, dict], settings: dict, use_ai: bool,
                   template_key: str | None = None) -> dict:
    key = template_key or choose_template(f)
    tpl = templates.get(key) or templates["apresentacao_inicial"]
    subject, body = fill(tpl, f, settings)
    by = "modelo"
    if use_ai and claude.available():
        try:
            res = personalize_with_ai(subject, body, f)
            if res:
                subject, body = res
                by = "ia"
        except claude.AIUnavailable:
            pass
    return {"template_key": key, "subject": subject, "body": body, "generated_by": by,
            "recipient": f.email, "recipient_name": f.contato_nome, "recipient_role": f.contato_cargo}


def outlook_web_link(to: str | None, subject: str, body: str) -> str:
    """Abre nova mensagem no Outlook Web com destinatário, assunto e corpo preenchidos."""
    base = "https://outlook.office.com/mail/deeplink/compose"
    return f"{base}?to={quote(to or '')}&subject={quote(subject)}&body={quote(body[:1800])}"


def mailto_link(to: str | None, subject: str, body: str) -> str:
    return f"mailto:{quote(to or '')}?subject={quote(subject)}&body={quote(body[:1500])}"
