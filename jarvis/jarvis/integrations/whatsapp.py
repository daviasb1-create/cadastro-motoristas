"""WhatsApp Business (conta comum, sem API paga).

Método escolhido (gratuito, local e sem burlar autenticação):
1. Ler as notificações que o WhatsApp Desktop (ou o WhatsApp Web no
   navegador) entrega ao Windows -> remetente e prévia da mensagem.
2. Abrir conversas pelos links oficiais ``whatsapp://send?phone=`` e
   ``https://wa.me/`` (o app abre a conversa; o envio é sempre feito por você).
3. Mensagens ditadas são preenchidas na conversa, mas NUNCA enviadas
   automaticamente: você confere e aperta Enter.

A WhatsApp Business Platform (API Cloud) exige um número dedicado, conta
Meta Business verificada e cobra por conversa; além disso não lê o histórico
do aplicativo do celular. Por isso não é usada aqui (ver docs/INTEGRACOES.md).
"""
from __future__ import annotations

import logging
import re
import sys
import threading
import time
from urllib.parse import quote

from ..actions.base import STR, ActionResult, PendingAction, ServiceUnavailable, action, props
from ..nlu.normalize import normalize, similar
from .winnotify import NotificationDbReader, WinNotification

log = logging.getLogger(__name__)

GENERIC_BODIES = ("nova mensagem", "new message", "mensagens novas", "novas mensagens", "messages", "mensagem")


def is_whatsapp(note: WinNotification, matches: list[str]) -> bool:
    haystack = f"{note.handler} {note.attribution} {note.launch}".lower()
    if any(m.lower() in haystack for m in matches):
        return True
    # WhatsApp Web via navegador: o atributo costuma ser "web.whatsapp.com"
    return "web.whatsapp.com" in haystack


def parse_whatsapp(note: WinNotification) -> dict:
    """Converte o toast em remetente/grupo/texto. Formatos observados:
    título = contato ou grupo; corpo = mensagem ou 'Fulano: mensagem' (grupos);
    resumos como '3 novas mensagens'."""
    title = note.title.strip()
    body = note.body.strip()
    if title.lower() in ("whatsapp", "whatsapp business") and note.texts[1:]:
        title, body = note.texts[1], " ".join(note.texts[2:])
    group = ""
    sender = title
    match = re.match(r"^(.{1,40}?):\s+(.+)$", body)
    if match and not re.match(r"^\d", match.group(1)):
        group, sender, body = title, match.group(1), match.group(2)
    content_available = bool(body) and normalize(body) not in GENERIC_BODIES and not re.fullmatch(
        r"\d+ (novas )?mensagens( novas)?", normalize(body))
    return {"sender": sender or "Contato desconhecido", "group": group, "body": body if content_available else "",
            "content_available": content_available}


class WhatsAppService:
    def __init__(self, settings, storage, bus, notifications, open_url=None) -> None:
        self.settings = settings
        self.storage = storage
        self.bus = bus
        self.notifications = notifications
        self.open_url = open_url
        self.reader = NotificationDbReader()
        self._stop = threading.Event()
        self.status = "off"

    # ------------------------------------------------------------ monitor
    def start(self) -> None:
        if not self.settings.get("whatsapp.enabled", True):
            self._set_status("off", "Desativado")
            return
        if not self.reader.available:
            self._set_status("error", "Notificações do Windows inacessíveis")
            return
        try:
            self.reader.prime()
        except Exception:  # noqa: BLE001
            log.exception("Falha ao abrir o banco de notificações")
            self._set_status("error", "Falha ao ler notificações")
            return
        self._set_status("ok", "Lendo notificações")
        threading.Thread(target=self._loop, name="whatsapp-notify", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _set_status(self, status: str, detail: str) -> None:
        self.status = status
        self.bus.publish("connection", service="whatsapp", status=status, detail=detail)

    def _loop(self) -> None:
        while not self._stop.wait(3):
            try:
                self.poll_once()
            except Exception:  # noqa: BLE001
                log.debug("Leitura de notificações falhou", exc_info=True)

    def poll_once(self) -> int:
        matches = self.settings.get("whatsapp.handler_match", ["whatsapp"]) or ["whatsapp"]
        other_apps = [a.lower() for a in self.settings.get("notifications.windows_apps", []) or []]
        count = 0
        for note in self.reader.read_new():
            if is_whatsapp(note, matches):
                info = parse_whatsapp(note)
                self.notifications.add(
                    source="whatsapp", app="WhatsApp", sender=info["sender"],
                    title=info["group"] or info["sender"], body=info["body"],
                    content_available=info["content_available"], key=f"wa:{note.id}",
                    extra={"group": info["group"]}, ts=note.arrival.timestamp())
                count += 1
            elif self.settings.get("notifications.sources.windows", False) and (
                    not other_apps or any(a in note.handler.lower() for a in other_apps)):
                self.notifications.add(
                    source="windows", app=_app_name(note.handler), sender=note.title, title=note.title,
                    body=note.body[:300], key=f"win:{note.id}", ts=note.arrival.timestamp())
        return count

    # ------------------------------------------------------------ consultas
    def recent(self, since: float | None = None, unread_only: bool = False) -> list[dict]:
        since = since if since is not None else time.time() - 24 * 3600
        sql = "SELECT * FROM notifications WHERE source='whatsapp' AND ts>=?"
        if unread_only:
            sql += " AND seen=0"
        return self.storage.query(sql + " ORDER BY ts DESC", (since,))

    def unread_summary(self, short: bool = False) -> str:
        if self.status != "ok":
            return "Não consigo ler as notificações do WhatsApp neste momento."
        items = self.recent(unread_only=True)
        if not items:
            return "Nenhuma mensagem nova no WhatsApp." if not short else "WhatsApp sem mensagens novas."
        senders = _unique([i["sender"] for i in items])
        names = _join(senders[:4])
        return (f"{len(items)} mensage{'ns' if len(items) > 1 else 'm'} nova{'s' if len(items) > 1 else ''} "
                f"no WhatsApp, de {names}.")

    def mark_seen(self, items: list[dict]) -> None:
        for item in items:
            self.storage.execute("UPDATE notifications SET seen=1 WHERE id=?", (item["id"],))

    # ------------------------------------------------------------ contatos
    def contact_number(self, name: str) -> tuple[str, str] | None:
        contacts = self.settings.get("whatsapp.contacts", {}) or {}
        target = normalize(name)
        best = None
        for contact, number in contacts.items():
            score = similar(target, normalize(contact))
            if score >= 0.7 and (best is None or score > best[0]):
                best = (score, contact, number)
        if best:
            return best[1], re.sub(r"\D", "", best[2])
        return None

    def open_app(self) -> ActionResult:
        if sys.platform == "win32":
            import os

            try:
                os.startfile("whatsapp:")  # type: ignore[attr-defined]
                return ActionResult("Abrindo o WhatsApp.")
            except OSError:
                pass
        self._open("https://web.whatsapp.com/")
        return ActionResult("Abrindo o WhatsApp Web.")

    def open_chat(self, number: str, text: str = "") -> None:
        suffix = f"&text={quote(text)}" if text else ""
        if self.settings.get("whatsapp.prefer_app", True) and sys.platform == "win32":
            import os

            try:
                os.startfile(f"whatsapp://send?phone={number}{suffix}")  # type: ignore[attr-defined]
                return
            except OSError:
                pass
        self._open(f"https://wa.me/{number}" + (f"?text={quote(text)}" if text else ""))

    def _open(self, url: str) -> None:
        if self.open_url:
            self.open_url(url)
        else:
            import webbrowser

            webbrowser.open(url)


def _app_name(handler: str) -> str:
    name = handler.split("!")[0].split("_")[0].split(".")[-1]
    return name or "Windows"


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(i for i in items if i))


def _join(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " e " + items[-1]


# ===================================================================== ações
def _svc(services, reading: bool = False) -> WhatsAppService:
    if services.whatsapp is None:
        raise ServiceUnavailable("A integração com o WhatsApp está desativada.")
    if reading and services.whatsapp.status != "ok":
        raise ServiceUnavailable("Não consigo ler as notificações do WhatsApp agora. Verifique se ele está aberto no "
                                 "computador e com notificações ativas (veja Solução de problemas).")
    return services.whatsapp


def _listing(items: list[dict]) -> str:
    from datetime import datetime

    lines = []
    for item in items[:20]:
        when = datetime.fromtimestamp(item["ts"]).strftime("%d/%m %H:%M")
        body = item["body"] if item["content_available"] else "(conteúdo não disponível na notificação)"
        group = f" [{item['title']}]" if item.get("title") and item["title"] != item["sender"] else ""
        lines.append(f"{when} — {item['sender']}{group}: {body}")
    return "\n".join(lines)


@action("whatsapp_unread", "Informa se chegaram mensagens novas no WhatsApp e de quem.")
def whatsapp_unread(services, params):
    svc = _svc(services, reading=True)
    items = svc.recent(unread_only=True)
    services.context.remember(whatsapp=[{"sender": i["sender"], "body": i["body"][:200]} for i in items[:10]])
    return ActionResult(svc.unread_summary(), display=_listing(items) or None)


@action("whatsapp_senders", "Lista quem mandou mensagem no WhatsApp (hoje ou nas últimas 24 h).",
        props(today={"type": "boolean"}))
def whatsapp_senders(services, params):
    svc = _svc(services, reading=True)
    since = None
    if params.get("today"):
        from datetime import datetime

        since = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    items = svc.recent(since=since)
    if not items:
        return ActionResult("Ninguém te chamou no WhatsApp " + ("hoje." if params.get("today") else "nas últimas 24 horas."))
    senders = _unique([i["sender"] for i in items])
    latest = items[0]
    services.context.remember(contact=latest["sender"],
                              whatsapp=[{"sender": i["sender"], "body": i["body"][:200]} for i in items[:10]])
    return ActionResult(f"Falaram com você: {_join(senders[:5])}. A mais recente foi de {latest['sender']}.",
                        display=_listing(items))


@action("whatsapp_summary", "Resume as mensagens não lidas do WhatsApp com base nas notificações recebidas.")
def whatsapp_summary(services, params):
    svc = _svc(services, reading=True)
    items = svc.recent(unread_only=True)
    if not items:
        return ActionResult("Nenhuma mensagem nova no WhatsApp.")
    with_content = [i for i in items if i["content_available"]]
    hidden = len(items) - len(with_content)
    llm = services.llm
    say = ""
    if with_content and llm and llm.available() and services.settings.get("ai.send_content", True):
        text = "\n".join(f"{i['sender']}: {i['body']}" for i in reversed(with_content[:30]))
        say = llm.complete("Resuma em até 3 frases faladas, em português, estas mensagens de WhatsApp. "
                           "Não invente nada além do texto:\n\n" + text) or ""
    if not say:
        per_sender: dict[str, list[str]] = {}
        for item in reversed(with_content):
            per_sender.setdefault(item["sender"], []).append(item["body"])
        say = " ".join(f"{s} disse: {msgs[-1][:120]}." for s, msgs in list(per_sender.items())[:4])
    if hidden:
        say += f" {hidden} mensage{'ns' if hidden > 1 else 'm'} sem prévia disponível na notificação."
    svc.mark_seen(items)
    services.context.remember(contact=items[0]["sender"])
    return ActionResult(say.strip(), display=_listing(items))


@action("whatsapp_open_chat", "Abre a conversa com um contato cadastrado (ou o WhatsApp, se não houver número).",
        props(contact=STR, latest={"type": "boolean"}))
def whatsapp_open_chat(services, params):
    svc = _svc(services)
    contact = params.get("contact") or ""
    if params.get("latest") or not contact:
        items = svc.recent()
        contact = items[0]["sender"] if items else services.context.get("contact", "")
    found = svc.contact_number(contact) if contact else None
    if not found:
        result = svc.open_app()
        hint = f" A conversa mais recente é de {contact}." if contact else ""
        return ActionResult(result.say + hint + " Para abrir conversas direto, cadastre o número em Configurações > WhatsApp.")
    name, number = found
    svc.open_chat(number)
    services.context.remember(contact=name)
    return ActionResult(f"Abrindo a conversa com {name}.")


def _prepare_message(services, contact: str, text: str) -> ActionResult:
    svc = _svc(services)
    found = svc.contact_number(contact)
    if not found:
        return ActionResult.fail(f"Não tenho o número de {contact}. Cadastre em Configurações > WhatsApp.")
    name, number = found
    if not text:
        return ActionResult(f"O que devo escrever para {name}?", expects_reply=True,
                            follow_up=lambda t: _prepare_message(services, name, t))
    preview = f"Para: {name} (+{number})\n\n{text}"
    question = f"Mensagem para {name}: {text}. Abro a conversa com o texto pronto para você enviar?"

    def execute() -> ActionResult:
        svc.open_chat(number, text)
        services.activity(f"WhatsApp: conversa com {name} aberta com texto preenchido", kind="whatsapp")
        return ActionResult("Pronto. Confira e aperte Enter para enviar.")

    return ActionResult(question, display=preview, expects_reply=True,
                        pending=PendingAction(question=question, execute=execute, details=preview))


@action("whatsapp_compose", "Prepara uma mensagem de WhatsApp para um contato cadastrado. Nunca envia sozinho: abre a conversa com o texto preenchido após confirmação.",
        props(["contact"], contact=STR, text=STR))
def whatsapp_compose(services, params):
    return _prepare_message(services, params.get("contact", ""), (params.get("text") or "").strip())


@action("whatsapp_draft_reply", "Prepara uma resposta para o contato que mandou mensagem por último (ou o indicado).",
        props(contact=STR, text=STR))
def whatsapp_draft_reply(services, params):
    svc = _svc(services)
    contact = params.get("contact") or services.context.get("contact") or ""
    if not contact:
        items = svc.recent()
        contact = items[0]["sender"] if items else ""
    if not contact:
        return ActionResult.fail("Para quem é a resposta?")
    text = (params.get("text") or "").strip()
    llm = services.llm
    if not text and llm and llm.available() and services.settings.get("ai.send_content", True):
        last = [i for i in svc.recent() if normalize(i["sender"]) == normalize(contact) and i["content_available"]]
        if last:
            text = llm.complete(
                "Sugira uma resposta curta, educada e profissional em português do Brasil para esta mensagem de "
                f"WhatsApp de {contact}: \"{last[0]['body']}\". Responda só com o texto da mensagem.") or ""
    return _prepare_message(services, contact, text.strip().strip('"'))
