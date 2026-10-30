"""Registro de ações. Importar este pacote registra todas as ações disponíveis."""
from . import apps, control, music, reminders, system, volume  # noqa: F401
from ..integrations import spotify, whatsapp  # noqa: F401
from ..integrations.msgraph import excel, outlook  # noqa: F401
from .base import REGISTRY, ActionResult, ActionSpec, PendingAction, action  # noqa: F401
