"""Outlook (Microsoft Graph): leitura, pesquisa, resumos, rascunhos e agenda.

Leitura e criação de rascunhos não alteram nada visível para terceiros.
Enviar, responder ou encaminhar SEMPRE passa por confirmação explícita,
com destinatário e conteúdo exibidos antes.
"""
from __future__ import annotations

import html
import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ...actions.base import BOOL, INT, STR, ActionResult, PendingAction, ServiceUnavailable, action, props
from ...nlu.normalize import normalize

log = logging.getLogger(__name__)

SELECT = "id,subject,from,receivedDateTime,bodyPreview,isRead,importance,hasAttachments,webLink,flag,conversationId"


@dataclass
class Mail:
    id: str
    subject: str
    sender_name: str
    sender_email: str
    received: datetime
    preview: str
    is_read: bool
    importance: str
    has_attachments: bool
    web_link: str
    flagged: bool = False

    @classmethod
    def from_graph(cls, data: dict) -> "Mail":
        sender = (data.get("from") or {}).get("emailAddress") or {}
        received = _parse_dt(data.get("receivedDateTime"))
        return cls(
            id=data.get("id", ""), subject=data.get("subject") or "(sem assunto)",
            sender_name=sender.get("name") or sender.get("address") or "remetente desconhecido",
            sender_email=(sender.get("address") or "").lower(), received=received,
            preview=(data.get("bodyPreview") or "").strip(), is_read=bool(data.get("isRead")),
            importance=data.get("importance", "normal"), has_attachments=bool(data.get("hasAttachments")),
            web_link=data.get("webLink", ""), flagged=(data.get("flag") or {}).get("flagStatus") == "flagged",
        )

    def short(self) -> str:
        return f"{self.sender_name}: {self.subject}"


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now()
    value = value.replace("Z", "+00:00")
    if "." in value:
        head, tail = value.split(".", 1)
        tz = re.search(r"[+-]\d\d:\d\d$", tail)
        value = head + (tz.group(0) if tz else "")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().replace(tzinfo=None)


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def first_name(name: str) -> str:
    name = name.split("@")[0]
    parts = [p for p in re.split(r"[\s,]+", name) if p]
    return parts[0].capitalize() if parts else name


class OutlookService:
    def __init__(self, client, auth, settings, storage, bus, notifications=None, llm=None) -> None:
        self.client = client
        self.auth = auth
        self.settings = settings
        self.storage = storage
        self.bus = bus
        self.notifications = notifications
        self.llm = llm
        self._stop = threading.Event()

    # ------------------------------------------------------------ estado
    def available(self) -> bool:
        return self.auth.configured and self.settings.get("microsoft.features.mail", True) and self.auth.is_signed_in()

    def _require(self) -> None:
        if not self.auth.configured:
            raise ServiceUnavailable("O Outlook ainda não foi configurado. Abra Configurações > Microsoft 365.")
        if not self.auth.is_signed_in():
            raise ServiceUnavailable("Sua conta Microsoft não está conectada. Use Configurações > Microsoft 365 > Conectar.")

    # ------------------------------------------------------------ consultas
    def unread_count(self) -> int:
        self._require()
        data = self.client.get("/me/mailFolders/inbox", params={"$select": "unreadItemCount"})
        return int(data.get("unreadItemCount", 0))

    def recent(self, hours: float = 24, unread_only: bool = False, top: int = 25) -> list[Mail]:
        self._require()
        since = _iso_utc(datetime.now() - timedelta(hours=hours))
        flt = f"receivedDateTime ge {since}"
        if unread_only:
            flt += " and isRead eq false"
        data = self.client.get("/me/mailFolders/inbox/messages", params={
            "$filter": flt, "$orderby": "receivedDateTime desc", "$top": top, "$select": SELECT})
        return [Mail.from_graph(m) for m in data.get("value", [])]

    def unread(self, top: int = 15) -> list[Mail]:
        self._require()
        data = self.client.get("/me/mailFolders/inbox/messages", params={
            "$filter": "isRead eq false", "$top": top, "$select": SELECT})
        mails = [Mail.from_graph(m) for m in data.get("value", [])]
        return sorted(mails, key=lambda m: m.received, reverse=True)

    def search(self, sender: str = "", query: str = "", top: int = 10) -> list[Mail]:
        self._require()
        if sender == "@manager":
            sender = self.settings.get("outlook.manager", "")
            if not sender:
                raise ServiceUnavailable("Ainda não sei quem é seu gestor. Informe o nome ou e-mail em Configurações > Outlook.")
        terms = []
        if sender:
            terms.append(f"from:{sender.replace(chr(34), '')}")
        if query:
            terms.append(query.replace('"', ""))
        if not terms:
            return self.recent(hours=72, top=top)
        data = self.client.get("/me/messages", params={"$search": '"' + " ".join(terms) + '"', "$top": top,
                                                      "$select": SELECT})
        mails = [Mail.from_graph(m) for m in data.get("value", [])]
        return sorted(mails, key=lambda m: m.received, reverse=True)

    def body_text(self, mail_id: str) -> str:
        self._require()
        data = self.client.get(f"/me/messages/{mail_id}", params={"$select": "body,uniqueBody"},
                               headers={"Prefer": 'outlook.body-content-type="text"'})
        body = ((data.get("uniqueBody") or data.get("body") or {}).get("content") or "").strip()
        return html.unescape(re.sub(r"\n{3,}", "\n\n", body))

    def attachments(self, mail_id: str) -> list[dict]:
        self._require()
        data = self.client.get(f"/me/messages/{mail_id}/attachments", params={"$select": "name,size,contentType"})
        return data.get("value", [])

    def is_important(self, mail: Mail) -> bool:
        if mail.importance == "high" or mail.flagged:
            return True
        important = [s.lower() for s in self.settings.get("outlook.important_senders", []) or []]
        manager = (self.settings.get("outlook.manager") or "").lower()
        if manager:
            important.append(manager)
        if any(s and (s in mail.sender_email or s in mail.sender_name.lower()) for s in important):
            return True
        text = normalize(f"{mail.subject} {mail.preview[:200]}")
        return any(normalize(k) in text for k in self.settings.get("outlook.urgent_keywords", []) or [])

    # --------------------------------------------------------- rascunhos/envio
    def create_reply_draft(self, mail_id: str, text: str) -> dict:
        self._require()
        return self.client.post(f"/me/messages/{mail_id}/createReply", json={"comment": text})

    def create_draft(self, to: str, subject: str, body: str) -> dict:
        self._require()
        return self.client.post("/me/messages", json={
            "subject": subject, "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to}}]})

    def send_draft(self, draft_id: str) -> None:
        self._require()
        if not self.settings.get("microsoft.features.send_mail", True):
            raise ServiceUnavailable("O envio de e-mails está desativado nas configurações.")
        self.client.post(f"/me/messages/{draft_id}/send")

    # ------------------------------------------------------------- agenda
    def events(self, day: datetime) -> list[dict]:
        self._require()
        start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        data = self.client.get("/me/calendarView", params={
            "startDateTime": _iso_utc(start), "endDateTime": _iso_utc(end), "$orderby": "start/dateTime",
            "$select": "subject,start,end,location,isAllDay,isCancelled,organizer,onlineMeeting,webLink", "$top": 30},
            headers={"Prefer": 'outlook.timezone="UTC"'})
        events = []
        for ev in data.get("value", []):
            if ev.get("isCancelled"):
                continue
            ev["_start"] = _parse_dt((ev.get("start") or {}).get("dateTime", "") + "Z")
            ev["_end"] = _parse_dt((ev.get("end") or {}).get("dateTime", "") + "Z")
            events.append(ev)
        return events

    # ------------------------------------------------------------- frases
    def unread_sentence(self) -> str:
        count = self.unread_count()
        if count == 0:
            return "Nenhum e-mail não lido."
        latest = self.unread(top=3)
        names = _join([first_name(m.sender_name) for m in latest])
        plural = "s" if count > 1 else ""
        return f"Você tem {count} e-mail{plural} não lido{plural}. Os mais recentes são de {names}."

    # -------------------------------------------------------- monitoramento
    def start_polling(self) -> None:
        threading.Thread(target=self._poll_loop, name="outlook-poll", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _poll_loop(self) -> None:
        last_seen = self.storage.kv_get("outlook.last_seen")
        if not last_seen:
            last_seen = _iso_utc(datetime.now() - timedelta(minutes=5))
        while not self._stop.is_set():
            if self.available() and self.settings.get("outlook.notify_new", True):
                try:
                    data = self.client.get("/me/mailFolders/inbox/messages", params={
                        "$filter": f"receivedDateTime gt {last_seen}", "$orderby": "receivedDateTime desc",
                        "$top": 20, "$select": SELECT})
                    values = data.get("value", [])
                    for raw in reversed(values):
                        mail = Mail.from_graph(raw)
                        if self.notifications:
                            self.notifications.add(
                                source="outlook", app="Outlook", sender=mail.sender_name, title=mail.subject,
                                body=mail.preview[:300], important=self.is_important(mail), key=f"outlook:{mail.id}",
                                link=mail.web_link, extra={"mail_id": mail.id})
                    if values:
                        last_seen = values[0]["receivedDateTime"]
                        self.storage.kv_set("outlook.last_seen", last_seen)
                    self.bus.publish("connection", service="outlook", status="ok", detail="Conectado")
                except ServiceUnavailable as exc:
                    self.bus.publish("connection", service="outlook", status="error", detail=str(exc)[:80])
                except Exception:  # noqa: BLE001
                    log.exception("Falha ao verificar e-mails")
            minutes = max(1, int(self.settings.get("microsoft.poll_minutes", 3)))
            self._stop.wait(minutes * 60)


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    unique = list(dict.fromkeys(items))
    if not unique:
        return ""
    if len(unique) == 1:
        return unique[0]
    return ", ".join(unique[:-1]) + " e " + unique[-1]


# =================================================================== ações
def _svc(services) -> OutlookService:
    if services.outlook is None:
        raise ServiceUnavailable("Integração com o Outlook indisponível.")
    return services.outlook


def _mail_listing(mails: list[Mail]) -> str:
    return "\n".join(f"{i + 1}. {m.received:%d/%m %H:%M} - {m.sender_name} - {m.subject}" for i, m in enumerate(mails))


@action("email_unread", "Informa quantos e-mails não lidos existem e de quem são os mais recentes.")
def email_unread(services, params):
    svc = _svc(services)
    mails = svc.unread(top=10)
    services.context.remember(emails=[m.__dict__ for m in mails])
    sentence = svc.unread_sentence()
    return ActionResult(sentence, display=_mail_listing(mails) or None)


@action("email_senders", "Lista quem enviou e-mails hoje (ou ontem).", props(day=STR | {"enum": ["hoje", "ontem"]}))
def email_senders(services, params):
    svc = _svc(services)
    now = datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if params.get("day") == "ontem":
        start -= timedelta(days=1)
    mails = [m for m in svc.recent(hours=(now - start).total_seconds() / 3600, top=50)
             if params.get("day") != "ontem" or m.received < start + timedelta(days=1)]
    if not mails:
        return ActionResult("Nenhum e-mail recebido " + ("ontem." if params.get("day") == "ontem" else "hoje."))
    services.context.remember(emails=[m.__dict__ for m in mails[:10]])
    names = _join([first_name(m.sender_name) for m in mails][:6])
    return ActionResult(f"{len(mails)} e-mail{'s' if len(mails) > 1 else ''}. Remetentes: {names}.",
                        display=_mail_listing(mails))


@action("email_summary", "Resume os e-mails recentes (ou só os importantes).", props(important_only=BOOL))
def email_summary(services, params):
    svc = _svc(services)
    mails = svc.recent(hours=24, top=25)
    if params.get("important_only"):
        mails = [m for m in mails if svc.is_important(m)]
    if not mails:
        return ActionResult("Não há e-mails importantes nas últimas 24 horas." if params.get("important_only")
                            else "Nenhum e-mail nas últimas 24 horas.")
    services.context.remember(emails=[m.__dict__ for m in mails[:10]])
    listing = _mail_listing(mails)
    llm = services.llm
    if llm and llm.available() and services.settings.get("ai.send_content", True):
        text = "\n\n".join(f"De: {m.sender_name} <{m.sender_email}>\nAssunto: {m.subject}\nPrévia: {m.preview[:400]}"
                           for m in mails[:12])
        summary = llm.complete(
            "Resuma estes e-mails em português, em no máximo 4 frases faladas, destacando prazos e pedidos. "
            "Use apenas as informações fornecidas.\n\n" + text)
        if summary:
            return ActionResult(summary, display=listing)
    important = [m for m in mails if svc.is_important(m)]
    say = f"{len(mails)} e-mails nas últimas 24 horas"
    say += f", {len(important)} marcados como importantes. " if important else ". "
    say += "Destaques: " + "; ".join(f"{first_name(m.sender_name)} sobre {m.subject}" for m in (important or mails)[:3]) + "."
    return ActionResult(say, display=listing)


@action("email_search", "Pesquisa e-mails por remetente e/ou palavras. sender='@manager' usa o gestor configurado.",
        props(sender=STR, query=STR, latest=BOOL))
def email_search(services, params):
    svc = _svc(services)
    mails = svc.search(params.get("sender", ""), params.get("query", ""))
    if not mails:
        return ActionResult.fail("Não encontrei e-mails com esses critérios.")
    services.context.remember(emails=[m.__dict__ for m in mails[:10]], email=mails[0].__dict__)
    first = mails[0]
    when = first.received.strftime("%d/%m às %H:%M")
    if params.get("latest") or len(mails) == 1:
        say = f"O último é de {first.sender_name}, {when}, assunto: {first.subject}. Quer que eu leia, abra ou prepare uma resposta?"
    else:
        say = f"Encontrei {len(mails)} e-mails. O mais recente é de {first.sender_name}, assunto: {first.subject}."
    return ActionResult(say, display=_mail_listing(mails), expects_reply=True)


def _context_mail(services, index: int = 0) -> dict | None:
    emails = services.context.get("emails") or []
    if 0 <= index < len(emails):
        return emails[index]
    return services.context.get("email")


@action("email_read", "Lê em voz alta o e-mail em contexto (o último citado).", props(index=INT))
def email_read(services, params):
    svc = _svc(services)
    mail = _context_mail(services, int(params.get("index", 0)))
    if not mail:
        return ActionResult.fail("Qual e-mail? Peça antes para eu procurar ou listar os e-mails.")
    services.context.remember(email=mail)
    body = svc.body_text(mail["id"])
    excerpt = re.sub(r"\s+", " ", body)[:600]
    llm = services.llm
    if len(body) > 700 and llm and llm.available() and services.settings.get("ai.send_content", True):
        summary = llm.complete("Resuma este e-mail em até 3 frases em português, para ser falado:\n\n" + body[:6000])
        if summary:
            return ActionResult(f"E-mail de {mail['sender_name']}: {summary}", display=body[:4000])
    return ActionResult(f"E-mail de {mail['sender_name']}, assunto {mail['subject']}. {excerpt}", display=body[:4000])


@action("email_open", "Abre no navegador o e-mail em contexto.", props(index=INT))
def email_open(services, params):
    mail = _context_mail(services, int(params.get("index", 0)))
    if not mail or not mail.get("web_link"):
        if services.open_url:
            services.open_url("https://outlook.office.com/mail/")
        return ActionResult("Abrindo o Outlook.")
    services.context.remember(email=mail)
    if services.open_url:
        services.open_url(mail["web_link"])
    return ActionResult("Abrindo o e-mail no navegador.")


@action("email_attachments", "Lista os anexos do e-mail em contexto.")
def email_attachments(services, params):
    svc = _svc(services)
    mail = _context_mail(services)
    if not mail:
        return ActionResult.fail("De qual e-mail? Peça antes para eu procurar o e-mail.")
    items = svc.attachments(mail["id"])
    if not items:
        return ActionResult("Esse e-mail não tem anexos.")
    names = [a.get("name", "?") for a in items]
    return ActionResult(f"{len(items)} anexo{'s' if len(items) > 1 else ''}: {_join(names[:4])}.",
                        display="\n".join(f"• {a.get('name')} ({int(a.get('size', 0)) // 1024} KB)" for a in items))


def _compose_reply(services, mail: dict, instructions: str) -> str:
    llm = services.llm
    if llm and llm.available() and services.settings.get("ai.send_content", True):
        svc = _svc(services)
        original = svc.body_text(mail["id"])[:4000]
        name = services.settings.get("general.user_name", "")
        text = llm.complete(
            "Escreva apenas o corpo de uma resposta de e-mail profissional, cordial e objetiva em português do Brasil. "
            f"Assinatura: {name or '(sem assinatura)'}. Instruções do usuário: {instructions or 'responda adequadamente'}.\n\n"
            f"E-mail original de {mail['sender_name']} (assunto: {mail['subject']}):\n{original}")
        if text:
            return text.strip()
    return instructions.strip()


@action("email_draft_reply", "Prepara um rascunho de resposta para o e-mail em contexto. Não envia sem confirmação.",
        props(instructions=STR | {"description": "O que a resposta deve dizer."}))
def email_draft_reply(services, params):
    _svc(services)
    mail = _context_mail(services)
    if not mail:
        return ActionResult.fail("Para qual e-mail? Peça antes para eu procurar ou listar os e-mails.")
    instructions = (params.get("instructions") or "").strip()
    if not instructions and not (services.llm and services.llm.available()):
        return ActionResult("O que devo responder?", expects_reply=True,
                            follow_up=lambda text: email_draft_reply(services, {"instructions": text}))
    body = _compose_reply(services, mail, instructions)
    if not body:
        return ActionResult("O que devo responder?", expects_reply=True,
                            follow_up=lambda text: email_draft_reply(services, {"instructions": text}))
    draft = _svc(services).create_reply_draft(mail["id"], body)
    draft_id = draft.get("id")
    services.activity(f"Rascunho de resposta criado para {mail['sender_name']}", kind="outlook")
    preview = f"Para: {mail['sender_name']} <{mail['sender_email']}>\nAssunto: RE: {mail['subject']}\n\n{body}"
    question = f"Rascunho pronto para {first_name(mail['sender_name'])}. O texto está na tela. Quer que eu envie?"

    def send() -> ActionResult:
        _svc(services).send_draft(draft_id)
        services.activity(f"E-mail enviado para {mail['sender_email']}", kind="outlook")
        return ActionResult("Resposta enviada.")

    return ActionResult(question, display=preview, expects_reply=True,
                        pending=PendingAction(question=question, execute=send, details=preview),
                        data={"draft_id": draft_id, "web_link": draft.get("webLink")})


@action("email_compose", "Prepara um novo e-mail (rascunho) e pede confirmação antes de enviar.",
        props(["to"], to=STR | {"description": "Endereço de e-mail ou nome de contato frequente."},
              subject=STR, instructions=STR))
def email_compose(services, params):
    svc = _svc(services)
    to = (params.get("to") or "").strip()
    address = to if "@" in to else _resolve_address(svc, to)
    if not address:
        return ActionResult.fail(f"Não encontrei o endereço de {to}. Diga o e-mail completo ou escreva na tela.")
    instructions = params.get("instructions", "")
    llm = services.llm
    subject = params.get("subject") or ""
    body = instructions
    if llm and llm.available() and instructions:
        draft = llm.complete(
            "Escreva um e-mail curto e profissional em português do Brasil. Responda no formato:\n"
            "ASSUNTO: ...\nCORPO:\n...\n\nPedido do usuário: " + instructions)
        if draft and "CORPO:" in draft:
            head, body = draft.split("CORPO:", 1)
            subject = subject or head.replace("ASSUNTO:", "").strip()
            body = body.strip()
    if not body:
        return ActionResult("O que o e-mail deve dizer?", expects_reply=True,
                            follow_up=lambda text: email_compose(services, {**params, "instructions": text}))
    subject = subject or "Mensagem"
    draft = svc.create_draft(address, subject, body)
    preview = f"Para: {address}\nAssunto: {subject}\n\n{body}"
    question = f"Rascunho para {address} pronto. Confere o texto na tela. Envio?"

    def send() -> ActionResult:
        svc.send_draft(draft["id"])
        services.activity(f"E-mail enviado para {address}", kind="outlook")
        return ActionResult("E-mail enviado.")

    return ActionResult(question, display=preview, expects_reply=True,
                        pending=PendingAction(question=question, execute=send, details=preview))


def _resolve_address(svc: OutlookService, name: str) -> str | None:
    """Procura o endereço entre remetentes recentes (sem acessar agenda de contatos)."""
    target = normalize(name)
    for mail in svc.search(sender=name, top=5):
        if target in normalize(mail.sender_name) or target in mail.sender_email:
            return mail.sender_email
    return None


@action("calendar", "Lista os compromissos do calendário de hoje ou amanhã.",
        props(day=STR | {"enum": ["hoje", "amanha"]}))
def calendar(services, params):
    svc = _svc(services)
    if not services.settings.get("microsoft.features.calendar", True):
        return ActionResult.fail("A leitura do calendário está desativada nas configurações.")
    day = datetime.now() + timedelta(days=1 if params.get("day") == "amanha" else 0)
    events = svc.events(day)
    label = "amanhã" if params.get("day") == "amanha" else "hoje"
    if not events:
        return ActionResult(f"Nenhum compromisso {label}.")
    now = datetime.now()
    upcoming = [e for e in events if e["_end"] > now] if label == "hoje" else events
    lines = [f"{'Dia inteiro' if e.get('isAllDay') else e['_start'].strftime('%H:%M')} - {e.get('subject')}" for e in events]
    if not upcoming:
        return ActionResult(f"Os compromissos de {label} já terminaram.", display="\n".join(lines))
    spoken = "; ".join(
        f"{'o dia todo' if e.get('isAllDay') else 'às ' + e['_start'].strftime('%H:%M')}, {e.get('subject')}"
        for e in upcoming[:3])
    return ActionResult(f"{len(upcoming)} compromisso{'s' if len(upcoming) > 1 else ''} {label}: {spoken}.",
                        display="\n".join(lines))


def daily_briefing_parts(services, day: str) -> list[str]:
    parts: list[str] = []
    if services.outlook is not None and services.outlook.available():
        try:
            parts.append(calendar(services, {"day": day}).say)
            if day == "hoje":
                parts.append(services.outlook.unread_sentence())
        except ServiceUnavailable as exc:
            parts.append(str(exc))
    return parts


def mail_to_dict(mail: Mail) -> dict[str, Any]:
    return dict(mail.__dict__)
