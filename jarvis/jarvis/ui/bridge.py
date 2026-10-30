"""Ponte entre o barramento de eventos (threads) e a interface Qt (thread principal)."""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class EventBridge(QObject):
    event = Signal(str, dict)

    def __init__(self, bus) -> None:
        super().__init__()
        bus.subscribe("*", self._on_event)

    def _on_event(self, payload: dict) -> None:
        topic = payload.get("topic", "")
        # sinais Qt atravessam threads com segurança (conexão enfileirada)
        self.event.emit(topic, dict(payload))


class _Signals(QObject):
    done = Signal(object, object)  # (resultado, erro)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:  # noqa: BLE001
            self.signals.done.emit(None, exc)
            return
        self.signals.done.emit(result, None)


def run_async(fn: Callable[[], Any], on_done: Callable[[Any, Exception | None], None]) -> None:
    """Executa ``fn`` fora da thread da interface e chama ``on_done`` na thread da interface."""
    task = _Task(fn)
    task.signals.done.connect(on_done)
    task.setAutoDelete(True)
    _keep.append(task)
    task.signals.done.connect(lambda *_: _keep.remove(task) if task in _keep else None)
    QThreadPool.globalInstance().start(task)


_keep: list[_Task] = []
