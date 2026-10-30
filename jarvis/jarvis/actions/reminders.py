"""Lembretes locais (SQLite) com aviso falado e notificação na bandeja."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

from ..nlu.timeparse import describe
from .base import STR, ActionResult, action, props

log = logging.getLogger(__name__)


class ReminderService:
    def __init__(self, storage, bus, on_due=None) -> None:
        self.storage = storage
        self.bus = bus
        self.on_due = on_due
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="reminders", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def add(self, due: datetime, text: str) -> int:
        cur = self.storage.execute(
            "INSERT INTO reminders(created, due, text) VALUES (?,?,?)", (time.time(), due.timestamp(), text))
        return int(cur.lastrowid)

    def pending(self) -> list[dict]:
        return self.storage.query("SELECT * FROM reminders WHERE done=0 ORDER BY due")

    def cancel(self, reminder_id: int | None = None) -> int:
        if reminder_id is None:
            cur = self.storage.execute("UPDATE reminders SET done=1 WHERE done=0")
        else:
            cur = self.storage.execute("UPDATE reminders SET done=1 WHERE id=? AND done=0", (reminder_id,))
        return cur.rowcount

    def check_due(self, now: float | None = None) -> list[dict]:
        now = now or time.time()
        due = self.storage.query("SELECT * FROM reminders WHERE done=0 AND due<=? ORDER BY due", (now,))
        for item in due:
            self.storage.execute("UPDATE reminders SET done=1 WHERE id=?", (item["id"],))
            if self.on_due:
                try:
                    self.on_due(item)
                except Exception:  # noqa: BLE001
                    log.exception("Erro ao disparar lembrete")
        return due

    def _loop(self) -> None:
        while not self._stop.wait(5):
            self.check_due()


@action("reminder_create", "Cria um lembrete local. 'when' em ISO 8601 (horário local).",
        props(["text"], text=STR, when=STR | {"description": "Data/hora ISO, ex.: 2026-05-10T15:30:00"}))
def reminder_create(services, params):
    when = params.get("when")
    text = params.get("text") or "Lembrete"
    if not when:
        return ActionResult.fail("Para quando é o lembrete? Diga, por exemplo, em 10 minutos ou às 15 horas.",
                                 display=None)
    due = datetime.fromisoformat(when)
    if due.timestamp() <= time.time():
        return ActionResult.fail("Esse horário já passou. Pode repetir com outro horário?")
    reminder_id = services.reminders.add(due, text)
    services.activity(f"Lembrete criado: {text} ({due:%d/%m %H:%M})", kind="reminder")

    def undo() -> str:
        services.reminders.cancel(reminder_id)
        return "Lembrete cancelado."

    return ActionResult(f"Combinado. Vou lembrar {describe(due)}: {text}.", undo=undo, undo_label="lembrete")


@action("reminder_list", "Lista os lembretes pendentes.")
def reminder_list(services, params):
    items = services.reminders.pending()
    if not items:
        return ActionResult("Você não tem lembretes pendentes.")
    lines = [f"{datetime.fromtimestamp(r['due']):%d/%m %H:%M} — {r['text']}" for r in items]
    first = items[0]
    say = (f"Você tem {len(items)} lembrete{'s' if len(items) > 1 else ''}. "
           f"O próximo é {describe(datetime.fromtimestamp(first['due']))}: {first['text']}.")
    return ActionResult(say, display="\n".join(lines))


@action("reminder_cancel", "Cancela o próximo lembrete ou todos.", props(all={"type": "boolean"}),
        risk="safe")
def reminder_cancel(services, params):
    items = services.reminders.pending()
    if not items:
        return ActionResult("Não há lembretes para cancelar.")
    if params.get("all"):
        count = services.reminders.cancel()
        return ActionResult(f"{count} lembretes cancelados.")
    services.reminders.cancel(items[0]["id"])
    return ActionResult(f"Cancelei o lembrete: {items[0]['text']}.")
