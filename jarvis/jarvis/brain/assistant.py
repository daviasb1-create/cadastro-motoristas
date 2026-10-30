"""Orquestrador: texto reconhecido -> intenção -> ação -> resposta.

Ordem de decisão (rápida e segura):
1. Confirmação pendente ("sim"/"não").
2. Informação pedida pela ação anterior ("O que devo responder?").
3. Referências ao contexto ("abre o primeiro", "quais delas são mais antigas").
4. Interpretador local (sem internet, sem custo).
5. Provedor de IA, se configurado.
Reconhecimentos de baixa confiança nunca executam ações direto: o
assistente repete o que entendeu e pede confirmação.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from typing import Any

from ..actions.base import REGISTRY, ActionResult, PendingAction
from ..nlu.intents import Intent, IntentParser, parse_yes_no
from ..nlu.normalize import normalize, recover_original, strip_wake_words
from . import responses
from .llm import LLMError
from .services import Services

log = logging.getLogger(__name__)

# Intenções que só leem informação: podem rodar mesmo com reconhecimento incerto.
READ_ONLY = {
    "ack", "thanks", "greeting", "time", "date", "battery", "system_status", "help", "stop",
    "volume_get", "reminder_list", "email_unread", "email_senders", "email_summary", "email_search",
    "whatsapp_unread", "whatsapp_senders", "whatsapp_summary", "messages_check", "notifications_summary",
    "notifications_history", "calendar", "daily_briefing", "excel_pending", "excel_search",
    "excel_summary", "excel_list", "excel_check", "memory_list", "wake_up",
}
ORDINALS = {"primeiro": 1, "primeira": 1, "segundo": 2, "segunda": 2, "terceiro": 3, "terceira": 3,
            "quarto": 4, "quarta": 4, "quinto": 5, "quinta": 5, "ultimo": -1, "ultima": -1}


@dataclass
class Reply:
    text: str
    display: str | None = None
    expects_reply: bool = False
    ok: bool = True
    intent: str = ""
    speak: bool = True


class Assistant:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.parser = IntentParser(services.settings.get("custom_commands", []) or [])
        self.pending: PendingAction | None = None
        self.follow_up = None
        self.undo_stack: list[tuple[str, Any]] = []
        self._lock = threading.RLock()
        services.settings.on_change(self._on_settings)

    def _on_settings(self, key: str, value: Any) -> None:
        if key in ("custom_commands", "*"):
            self.parser.custom_commands = self.services.settings.get("custom_commands", []) or []

    # ------------------------------------------------------------- entrada
    def handle(self, text: str, source: str = "voice", confidence: float = 1.0) -> Reply:
        with self._lock:
            settings = self.services.settings
            variants = (settings.get("wake.variants", []) or []) + (settings.get("wake.words", []) or [])
            clean = strip_wake_words(normalize(text), variants)
            self.services.bus.publish("transcript", text=text, confidence=confidence, source=source)
            if settings.get("memory.history_enabled", True):
                self.services.storage.add_conversation("user", text)
            reply = self._decide(text, clean, source, confidence)
            reply.text = self._shape(reply.text)
            self.services.bus.publish("reply", text=reply.text, display=reply.display, ok=reply.ok)
            if settings.get("memory.history_enabled", True):
                self.services.storage.add_conversation("assistant", reply.text)
            return reply

    def _shape(self, text: str) -> str:
        state = self.services.state
        if state.game_mode and self.services.settings.get("gaming.short_replies_in_game", True) and not (
                self.pending or self.follow_up):
            return responses.first_sentence(text)
        return text

    def _decide(self, raw: str, clean: str, source: str, confidence: float) -> Reply:
        # 1. Confirmação pendente
        if self.pending is not None:
            answer = parse_yes_no(clean)
            if answer is True:
                pending, self.pending = self.pending, None
                self.services.bus.publish("confirm", id=None)
                result = pending.execute()
                if self.services.llm:
                    self.services.llm.resolve_pending_tool("Usuário confirmou. Resultado: " + result.say)
                return self._finish(result, "confirmed")
            if answer is False:
                self.pending = None
                self.services.bus.publish("confirm", id=None)
                if self.services.llm:
                    self.services.llm.resolve_pending_tool("Usuário cancelou. Nada foi executado.")
                return Reply("Cancelado. Nada foi feito.", intent="cancelled")
            self.pending.attempts += 1
            if self.pending.attempts >= 2 or len(clean.split()) > 3 or self.parser.parse(clean) is not None:
                # Mudou de assunto: descarta a confirmação com segurança e segue
                self.pending = None
                self.services.bus.publish("confirm", id=None)
                if self.services.llm:
                    self.services.llm.resolve_pending_tool("Usuário não confirmou. Nada foi executado.")
            else:
                return Reply("Preciso de um sim ou não. " + self.pending.question, expects_reply=True,
                             intent="confirm_repeat")

        # 2. Resposta a uma pergunta da ação anterior
        if self.follow_up is not None:
            follow, self.follow_up = self.follow_up, None
            if parse_yes_no(clean) is False or clean in ("cancela", "deixa", "esquece"):
                return Reply("Tudo bem, deixei de lado.", intent="cancelled")
            return self._finish(follow(raw.strip()), "follow_up")

        if not clean:
            return Reply(responses.ack(self.services.settings), intent="ack")

        # 3. Contexto
        contextual = self._contextual(clean)
        intent = contextual or self.parser.parse(clean)

        if intent is not None:
            for key in ("text", "fact", "instructions", "query", "contact", "to"):
                value = intent.params.get(key)
                if isinstance(value, str) and value:
                    intent.params[key] = recover_original(raw, value)
            if source == "voice" and intent.name not in READ_ONLY:
                threshold = float(self.services.settings.get("stt.min_confidence", 0.55))
                if confidence < threshold:
                    return self._ask_confirm_low_confidence(intent, clean)
            return self._run_intent(intent)

        # 5. IA
        llm = self.services.llm
        if llm is not None and llm.available():
            return self._ask_llm(clean if len(clean) > len(raw) * 0.5 else raw)
        return Reply(responses.NO_AI_HINT, ok=False, intent="unknown")

    # ------------------------------------------------------------- contexto
    def _contextual(self, t: str) -> Intent | None:
        ctx = self.services.context
        m = re.search(r"\b(abre|abra|abrir|le|leia|mostra)\s+(o|a)\s+(primeir[oa]|segund[oa]|terceir[oa]|quart[oa]|quint[oa]|ultim[oa])\b", t)
        if m:
            index = ORDINALS[m.group(3)]
            if ctx.get("files"):
                return Intent("open_file_result", {"index": index if index > 0 else len(ctx.get("files"))})
            if ctx.get("emails"):
                name = "email_read" if m.group(1) in ("le", "leia") else "email_open"
                return Intent(name, {"index": (index - 1) if index > 0 else len(ctx.get("emails")) - 1})
        if ctx.last_intent == "excel_pending" and re.search(r"\b(mais antig|mais velh)", t):
            return Intent("excel_pending", {**ctx.last_params, "oldest": True})
        if ctx.last_intent == "excel_pending" and re.search(r"\b(atrasad|vencid)", t):
            return Intent("excel_pending", {**ctx.last_params, "overdue": True})
        if re.fullmatch(r"(agora )?(prepara|faz|faca|gera|me da) (um |o )?resumo( disso)?", t):
            if ctx.get("workbook") and not (self.services.llm and self.services.llm.available()):
                return Intent("excel_summary", {"workbook": ""})
        if re.fullmatch(r"(responde|responda|prepara uma resposta)( ele| ela| essa pessoa)?", t) and ctx.get("email"):
            return Intent("email_draft_reply", {"instructions": ""})
        return None

    # --------------------------------------------------------------- execução
    def _ask_confirm_low_confidence(self, intent: Intent, heard: str) -> Reply:
        question = f"Entendi: {heard}. Está certo?"
        self.pending = PendingAction(question=question, execute=lambda: self._execute(intent))
        self.services.bus.publish("confirm", id=self.pending.id, text=question)
        return Reply(question, expects_reply=True, intent="confirm_low_confidence")

    def _run_intent(self, intent: Intent) -> Reply:
        name = intent.name
        self.services.context.set_intent(name, intent.params)
        if name == "ack":
            return Reply(responses.ack(self.services.settings), intent=name)
        if name == "thanks":
            import random

            return Reply(random.choice(responses.THANKS), intent=name)
        if name == "greeting":
            profile = self.services.settings.get("voice.profile", "jarvis")
            return Reply(responses.GREETING.get(profile, ["Olá."])[0], intent=name)
        if name == "stop":
            if self.services.speaker:
                self.services.speaker.stop()
            music = self.services.extras.get("music")
            if music is not None and music.playing:
                music.stop()
            self.pending = None
            self.follow_up = None
            return Reply("", intent=name, speak=False)
        if name == "undo":
            return self._undo()
        if name == "daily_briefing":
            return self._briefing(intent.params.get("day", "hoje"))
        return self._finish(self._execute(intent), name)

    def _execute(self, intent: Intent) -> ActionResult:
        self.services.state.cancel_event.clear()
        return REGISTRY.run(self.services, intent.name, intent.params)

    def _finish(self, result: ActionResult, intent_name: str) -> Reply:
        if result.pending:
            self.pending = result.pending
            self.services.bus.publish("confirm", id=result.pending.id, text=result.pending.question,
                                      details=result.pending.details or result.display or "")
        if result.follow_up:
            self.follow_up = result.follow_up
        if result.undo:
            self.undo_stack.append((result.undo_label or intent_name, result.undo))
            self.undo_stack = self.undo_stack[-10:]
        if result.ok and intent_name not in ("confirm_repeat",):
            self.services.activity(f"{intent_name}: {result.say[:120]}", kind="command")
        return Reply(result.say, display=result.display, expects_reply=result.expects_reply or bool(result.pending)
                     or bool(result.follow_up), ok=result.ok, intent=intent_name)

    def _undo(self) -> Reply:
        if not self.undo_stack:
            return Reply("Não há ação recente que eu possa desfazer.", ok=False, intent="undo")
        label, undo = self.undo_stack.pop()
        try:
            said = undo()
        except Exception as exc:  # noqa: BLE001
            log.exception("Falha ao desfazer")
            return Reply(f"Não consegui desfazer {label}.", display=str(exc), ok=False, intent="undo")
        self.services.activity(f"Desfeito: {label}", kind="command")
        return Reply(said or f"Desfeito: {label}.", intent="undo")

    def _briefing(self, day: str) -> Reply:
        from datetime import datetime

        from ..actions.system import spoken_date
        from ..integrations.msgraph.outlook import daily_briefing_parts

        parts = []
        if day == "hoje":
            parts.append(f"Hoje é {spoken_date(datetime.now())}.")
        parts += daily_briefing_parts(self.services, day)
        if self.services.whatsapp is not None:
            parts.append(self.services.whatsapp.unread_summary(short=True))
        if self.services.reminders is not None:
            pending = self.services.reminders.pending()
            if pending:
                parts.append(f"{len(pending)} lembrete{'s' if len(pending) > 1 else ''} pendente{'s' if len(pending) > 1 else ''}.")
        if self.services.excel is not None:
            for wb in (self.services.settings.get("excel.workbooks", []) or [])[:2]:
                if wb.get("status_column"):
                    result = REGISTRY.run(self.services, "excel_pending", {"workbook": wb.get("alias", "")})
                    if result.ok:
                        parts.append(responses.first_sentence(result.say))
        if len(parts) <= 1:
            parts.append("Conecte o Outlook e configure suas planilhas para eu trazer agenda, e-mails e pendências.")
        return Reply(" ".join(parts), intent="daily_briefing")

    def _ask_llm(self, text: str) -> Reply:
        llm = self.services.llm
        self.services.bus.publish("state", state="processing")

        def execute_tool(name: str, params: dict) -> ActionResult:
            spec = REGISTRY.get(name)
            if spec is None or not spec.llm:
                return ActionResult.fail(f"Ferramenta {name} indisponível.")
            self.services.activity(f"IA solicitou: {name}", kind="ai")
            return REGISTRY.run(self.services, name, params)

        try:
            outcome = llm.chat(text, self.services.context.describe(), REGISTRY.llm_tools(), execute_tool)
        except LLMError as exc:
            return Reply(str(exc), ok=False, intent="ai_error")
        except Exception:  # noqa: BLE001
            log.exception("Falha na IA")
            return Reply("Tive um problema ao consultar a IA. Comandos locais continuam funcionando.", ok=False,
                         intent="ai_error")
        if outcome.pending:
            self.pending = outcome.pending
            self.services.bus.publish("confirm", id=outcome.pending.id, text=outcome.pending.question,
                                      details=outcome.pending.details or outcome.display or "")
        if outcome.follow_up:
            self.follow_up = outcome.follow_up
        if outcome.undo:
            self.undo_stack.append((outcome.undo_label or "ação", outcome.undo))
        return Reply(outcome.text, display=outcome.display, expects_reply=outcome.expects_reply or
                     outcome.text.rstrip().endswith("?"), intent="ai")

    # ---------------------------------------------------- confirmação pela tela
    def confirm_from_ui(self, accepted: bool) -> Reply:
        return self.handle("sim" if accepted else "não", source="ui")
