"""Central única de notificações (Outlook, WhatsApp, Excel, lembretes e Windows).

* Deduplica (mesma chave ou mesmo remetente+texto em poucos minutos).
* Classifica importância por remetentes e palavras configuradas.
* Agrupa chegadas próximas num único aviso falado.
* Respeita silêncio manual, horário silencioso, modo jogo e modo silencioso
  (registra tudo, só não fala).
* Resumos usam somente o que está disponível; quando o conteúdo não veio na
  notificação, isso é dito explicitamente.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import Counter
from datetime import datetime
from typing import Callable

from ..actions.base import ActionResult
from ..nlu.normalize import normalize

log = logging.getLogger(__name__)

SOURCE_LABEL = {"whatsapp": "WhatsApp", "outlook": "Outlook", "excel": "Excel", "reminder": "lembrete",
                "windows": "Windows"}


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


class NotificationCenter:
    def __init__(self, settings, storage, bus, state=None, announce: Callable[[str, bool], None] | None = None) -> None:
        self.settings = settings
        self.storage = storage
        self.bus = bus
        self.state = state
        self.announce = announce
        self._pending: list[dict] = []
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    # ------------------------------------------------------------- entrada
    def add(self, source: str, sender: str = "", title: str = "", body: str = "", important: bool | None = None,
            content_available: bool = True, key: str | None = None, link: str | None = None,
            app: str = "", extra: dict | None = None, ts: float | None = None, announce: bool = True) -> dict | None:
        if not self.settings.get(f"notifications.sources.{source}", True):
            return None
        ts = ts or time.time()
        key = key or hashlib.sha1(f"{source}|{sender}|{title}|{body}".encode()).hexdigest()
        if self._is_duplicate(source, sender, body, ts):
            return None
        if important is None:
            important = self.is_important(sender, f"{title} {body}")
        else:
            important = important or self.is_important(sender, f"{title} {body}")
        try:
            cur = self.storage.execute(
                "INSERT INTO notifications(key, ts, source, app, sender, title, body, important, content_available, link, extra)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (key, ts, source, app or SOURCE_LABEL.get(source, source), sender, title, body, int(important),
                 int(content_available), link, json.dumps(extra or {}, ensure_ascii=False)))
        except Exception as exc:  # noqa: BLE001 - chave repetida = já registrada
            if "UNIQUE" in str(exc):
                return None
            raise
        item = {"id": cur.lastrowid, "key": key, "ts": ts, "source": source,
                "app": app or SOURCE_LABEL.get(source, source), "sender": sender,
                "title": title, "body": body, "important": important, "content_available": content_available,
                "link": link}
        self.bus.publish("notification", **item)
        if announce:
            self._queue_announcement(item)
        return item

    def _is_duplicate(self, source: str, sender: str, body: str, ts: float) -> bool:
        if not body:
            return False
        window = max(1, int(self.settings.get("notifications.dedupe_minutes", 30))) * 60
        rows = self.storage.query(
            "SELECT 1 FROM notifications WHERE source=? AND sender=? AND body=? AND ts>=? LIMIT 1",
            (source, sender, body, ts - window))
        return bool(rows)

    def is_important(self, sender: str, text: str) -> bool:
        senders = [normalize(s) for s in self.settings.get("notifications.important_senders", []) or [] if s]
        words = [normalize(w) for w in self.settings.get("notifications.important_keywords", []) or [] if w]
        sender_n, text_n = normalize(sender or ""), normalize(text or "")
        return any(s in sender_n for s in senders) or any(w in text_n for w in words)

    # ------------------------------------------------------- aviso falado
    def should_speak(self, important: bool, now: float | None = None) -> bool:
        now = now or time.time()
        if not self.settings.get("notifications.speak_new", True):
            return False
        muted = self.settings.get("notifications.muted_until")
        if muted == -1 or (isinstance(muted, (int, float)) and muted > now):
            return False
        if self.state is not None:
            if self.state.quiet_mode or self.state.sleeping or not self.state.mic_enabled:
                return False
            if self.state.game_mode and self.settings.get("gaming.silence_notifications_in_game", True):
                return important
        if self.in_quiet_hours(datetime.fromtimestamp(now)):
            return important
        return True

    def in_quiet_hours(self, now: datetime) -> bool:
        quiet = self.settings.get("notifications.quiet_hours", {}) or {}
        if not quiet.get("enabled"):
            return False
        try:
            start = datetime.strptime(quiet.get("start", "22:00"), "%H:%M").time()
            end = datetime.strptime(quiet.get("end", "07:00"), "%H:%M").time()
        except ValueError:
            return False
        current = now.time()
        return start <= current < end if start < end else (current >= start or current < end)

    def _queue_announcement(self, item: dict) -> None:
        if not self.should_speak(bool(item["important"])):
            return
        with self._lock:
            self._pending.append(item)
            if self._timer is None:
                delay = float(self.settings.get("notifications.batch_seconds", 6))
                self._timer = threading.Timer(delay, self._flush)
                self._timer.daemon = True
                self._timer.start()

    def _flush(self) -> None:
        with self._lock:
            items, self._pending, self._timer = self._pending, [], None
        if not items or not self.announce:
            return
        text = self.compose_announcement(items)
        important = any(i["important"] for i in items)
        try:
            self.announce(text, important)
        except Exception:  # noqa: BLE001
            log.exception("Falha ao anunciar notificação")
        for item in items:
            self.storage.execute("UPDATE notifications SET spoken=1 WHERE id=?", (item["id"],))

    def compose_announcement(self, items: list[dict]) -> str:
        game = bool(self.state and self.state.game_mode)
        if len(items) == 1:
            item = items[0]
            if item["source"] == "reminder":
                return f"Lembrete: {item['body'] or item['title']}."
            label = SOURCE_LABEL.get(item["source"], item["source"])
            if item["source"] == "outlook":
                text = f"Novo e-mail de {item['sender']}"
                return text + ("." if game else f": {item['title']}.")
            prefix = "Mensagem importante" if item["important"] else "Nova mensagem"
            if item["source"] == "excel":
                return f"Planilha {item['sender']}: {item['title']}."
            return f"{prefix} no {label} de {item['sender']}."
        by_source = Counter(i["source"] for i in items)
        parts = []
        for source, count in by_source.items():
            senders = list(dict.fromkeys(i["sender"] for i in items if i["source"] == source and i["sender"]))
            if source == "outlook":
                parts.append(_plural(count, "e-mail", "e-mails") + (f" de {', '.join(senders[:2])}" if senders else ""))
            elif source == "whatsapp":
                parts.append(_plural(count, "mensagem no WhatsApp", "mensagens no WhatsApp")
                             + (f" de {', '.join(senders[:2])}" if senders else ""))
            else:
                parts.append(_plural(count, f"aviso do {SOURCE_LABEL.get(source, source)}",
                                     f"avisos do {SOURCE_LABEL.get(source, source)}"))
        return "Chegaram " + " e ".join(parts) + "."

    # -------------------------------------------------------------- consulta
    def recent(self, limit: int = 50) -> list[dict]:
        return self.storage.query("SELECT * FROM notifications ORDER BY ts DESC LIMIT ?", (limit,))

    def since(self, ts: float) -> list[dict]:
        return self.storage.query("SELECT * FROM notifications WHERE ts>=? ORDER BY ts DESC", (ts,))

    @staticmethod
    def format_line(n: dict) -> str:
        when = datetime.fromtimestamp(n["ts"]).strftime("%d/%m %H:%M")
        mark = "★ " if n.get("important") else ""
        body = n.get("body") if n.get("content_available") else "(conteúdo indisponível)"
        title = f" - {n['title']}" if n.get("title") and n.get("title") != n.get("sender") else ""
        return f"{mark}{when} [{n.get('app') or n['source']}] {n.get('sender') or ''}{title}: {body or ''}".strip()

    def summary(self, since: float) -> ActionResult:
        items = [i for i in self.since(since) if i["source"] != "reminder" or i["body"]]
        if not items:
            return ActionResult("Nada novo enquanto você estava ocupado.")
        counts = Counter(i["source"] for i in items)
        parts = []
        if counts.get("whatsapp"):
            parts.append(_plural(counts["whatsapp"], "mensagem", "mensagens") + " no WhatsApp")
        if counts.get("outlook"):
            parts.append(_plural(counts["outlook"], "e-mail", "e-mails") + " no Outlook")
        if counts.get("excel"):
            parts.append(_plural(counts["excel"], "aviso de planilha", "avisos de planilhas"))
        if counts.get("reminder"):
            parts.append(_plural(counts["reminder"], "lembrete", "lembretes"))
        if counts.get("windows"):
            parts.append(_plural(counts["windows"], "notificação do Windows", "notificações do Windows"))
        say = "Você recebeu " + _join(parts) + "."
        important = [i for i in items if i["important"]]
        if important:
            first = important[0]
            say += f" {_plural(len(important), 'item marcado', 'itens marcados')} como importante"
            say += f", o primeiro de {first['sender']}." if first.get("sender") else "."
        senders = list(dict.fromkeys(i["sender"] for i in items if i["sender"] and i["source"] in ("whatsapp", "outlook")))
        if senders:
            say += f" Remetentes: {_join(senders[:5])}."
        hidden = sum(1 for i in items if not i["content_available"])
        if hidden:
            say += (f" Em {_plural(hidden, 'mensagem', 'mensagens')}, o conteúdo não estava disponível "
                    "na notificação.")
        for item in items:
            self.storage.execute("UPDATE notifications SET seen=1 WHERE id=?", (item["id"],))
        return ActionResult(say, display="\n".join(self.format_line(i) for i in items[:40]))


def _join(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " e " + items[-1]
