"""Contexto recente da conversa (o que "esse e-mail" ou "essa planilha" significam)."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

CONTEXT_TTL = 15 * 60  # segundos


@dataclass
class ConversationContext:
    last_intent: str = ""
    last_params: dict[str, Any] = field(default_factory=dict)
    entities: dict[str, Any] = field(default_factory=dict)
    updated: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def remember(self, **entities: Any) -> None:
        with self._lock:
            self.entities.update(entities)
            self.updated = time.time()

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if time.time() - self.updated > CONTEXT_TTL:
                return default
            return self.entities.get(key, default)

    def set_intent(self, name: str, params: dict[str, Any]) -> None:
        with self._lock:
            self.last_intent = name
            self.last_params = dict(params)
            self.updated = time.time()

    def clear(self) -> None:
        with self._lock:
            self.entities.clear()
            self.last_intent = ""
            self.last_params = {}

    def describe(self) -> str:
        """Resumo textual para a IA (sem conteúdo sensível extenso)."""
        with self._lock:
            if time.time() - self.updated > CONTEXT_TTL:
                return "Sem contexto recente."
            parts = []
            if self.last_intent:
                parts.append(f"Último comando: {self.last_intent} {self.last_params}")
            for key, value in self.entities.items():
                text = str(value)
                parts.append(f"{key}: {text[:400]}")
            return "\n".join(parts) or "Sem contexto recente."
