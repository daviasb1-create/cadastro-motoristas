"""Contêiner de serviços compartilhados pelas ações.

Os serviços são opcionais: em testes ou com integrações desconectadas,
cada ação verifica a disponibilidade e responde com uma mensagem clara.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..core.config import Settings
from ..core.events import EventBus
from ..core.secrets import SecretStore
from ..core.storage import Storage
from .context import ConversationContext


@dataclass
class RuntimeState:
    game_mode: bool = False
    game_mode_reason: str = ""
    game_mode_manual: bool | None = None  # None = automático
    quiet_mode: bool = False
    mic_enabled: bool = True
    sleeping: bool = False
    busy_since: float | None = None
    last_summary_at: float = field(default_factory=time.time)
    cancel_event: threading.Event = field(default_factory=threading.Event)


@dataclass
class Services:
    settings: Settings
    storage: Storage
    bus: EventBus
    secrets: SecretStore
    context: ConversationContext = field(default_factory=ConversationContext)
    state: RuntimeState = field(default_factory=RuntimeState)
    speaker: Any = None  # audio.speaker.Speaker
    apps: Any = None  # actions.apps.AppCatalog
    volume: Any = None  # actions.volume.VolumeController
    reminders: Any = None  # actions.reminders.ReminderService
    graph: Any = None  # integrations.msgraph.auth.GraphAuth
    outlook: Any = None  # integrations.msgraph.outlook.OutlookService
    excel: Any = None  # integrations.msgraph.excel.ExcelService
    whatsapp: Any = None  # integrations.whatsapp.WhatsAppService
    notifications: Any = None  # notifications.center.NotificationCenter
    llm: Any = None  # brain.llm.LLMClient
    pipeline: Any = None  # voice.pipeline.VoicePipeline
    open_url: Callable[[str], None] | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def activity(self, text: str, kind: str = "action", data: dict | None = None) -> None:
        self.bus.publish("activity", text=text, kind=kind)
        if self.settings.get("memory.history_enabled", True):
            self.storage.log_activity(kind, text, data)

    def title(self) -> str:
        """Forma de tratamento configurada ("senhor", nome...)."""
        title = self.settings.get("general.user_title", "") or ""
        return f", {title}" if title else ""
