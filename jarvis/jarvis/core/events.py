"""Barramento de eventos simples e thread-safe.

Os módulos de voz, integrações e ações publicam eventos; a interface gráfica
assina e recebe via ponte Qt (ver ui/bridge.py). Nenhum módulo do núcleo
depende da interface.

Tópicos usados:
    state          {"state": idle|listening|processing|speaking|suspended|sleeping}
    audio_level    {"level": 0..1}
    transcript     {"text": str, "confidence": float, "source": voice|text}
    reply          {"text": str}
    activity       {"text": str, "kind": str}
    notification   {notificação da central}
    connection     {"service": str, "status": ok|off|error|pending, "detail": str}
    confirm        {"id": str, "text": str} ou {"id": None} para limpar
    game_mode      {"active": bool, "reason": str}
    settings       {"key": str}
    toast          {"title": str, "text": str}
    login_code     {"message": str, "url": str, "code": str}
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any, Callable

log = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], None]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, topic: str, handler: Handler) -> None:
        with self._lock:
            self._subs[topic].append(handler)

    def unsubscribe(self, topic: str, handler: Handler) -> None:
        with self._lock:
            if handler in self._subs.get(topic, []):
                self._subs[topic].remove(handler)

    def publish(self, topic: str, **payload: Any) -> None:
        with self._lock:
            handlers = list(self._subs.get(topic, [])) + list(self._subs.get("*", []))
        for handler in handlers:
            try:
                handler({"topic": topic, **payload})
            except Exception:  # noqa: BLE001 - um assinante com erro não derruba o barramento
                log.exception("Erro ao tratar evento %s", topic)
