"""Provedores de IA configuráveis (opcionais).

* none       só comandos locais (sem custo, sem internet).
* anthropic  Claude via API oficial (exige chave própria e é cobrado por uso).
* ollama     modelo local gratuito rodando no seu PC (https://ollama.com).

A IA é chamada apenas quando o interpretador local não entende o pedido,
ou para resumir/redigir textos. As ações continuam passando pelo mesmo
registro com confirmações; a IA não executa nada fora da lista permitida.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)

PROFILE_PERSONA = {
    "jarvis": "Você é JARVIS, assistente pessoal sofisticado, calmo, confiante e cordial, com humor britânico sutil.",
    "friday": "Você é FRIDAY, assistente pessoal tecnológica, direta, confiante e simpática.",
}

SYSTEM_TEMPLATE = """{persona}
Você roda no computador Windows 11 do usuário e conversa por voz em português do Brasil.
Regras:
- Responda de forma natural e {length}. Suas respostas serão faladas: sem markdown, listas, emojis ou URLs.
- Para agir, use somente as ferramentas disponíveis. Se nenhuma ferramenta resolver, diga isso em uma frase.
- Ferramentas que enviam, alteram ou apagam algo pedem confirmação ao usuário automaticamente; não peça confirmação duas vezes.
- Se o pedido estiver ambíguo, faça UMA pergunta curta em vez de adivinhar.
- Use apenas informações fornecidas pelas ferramentas ou pelo contexto. Nunca invente e-mails, mensagens, valores ou nomes.
- O contexto recente (último e-mail, planilha, contato, linhas encontradas) vem junto com cada pedido; use-o para entender "esse", "essa", "delas", "correspondente".
- Latência importa: comece a resposta imediatamente."""


@dataclass
class AgentOutcome:
    text: str
    pending: Any = None  # PendingAction aguardando confirmação
    follow_up: Callable[[str], Any] | None = None
    display: str | None = None
    undo: Callable[[], str] | None = None
    undo_label: str = ""
    expects_reply: bool = False
    actions: list[str] = field(default_factory=list)


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self, settings, secrets) -> None:
        self.settings = settings
        self.secrets = secrets
        self._lock = threading.Lock()
        self._anthropic = None
        self._anthropic_key = ""
        self.messages: list[dict] = []
        self._pending_tool_results: list[dict] = []
        self._last_used = 0.0

    # ------------------------------------------------------------ estado
    @property
    def provider(self) -> str:
        return self.settings.get("ai.provider", "none") or "none"

    def available(self) -> bool:
        if self.provider == "anthropic":
            return bool(self.secrets.get("anthropic_api_key"))
        return self.provider == "ollama"

    def reset(self) -> None:
        with self._lock:
            self.messages = []
            self._pending_tool_results = []

    def _system(self) -> str:
        profile = self.settings.get("voice.profile", "jarvis")
        detailed = self.settings.get("voice.verbosity", "short") == "detailed"
        length = "completa quando necessário (até 6 frases)" if detailed else "curta (1 a 2 frases)"
        return SYSTEM_TEMPLATE.format(persona=PROFILE_PERSONA.get(profile, PROFILE_PERSONA["jarvis"]), length=length)

    # ---------------------------------------------------------- Anthropic
    def _client(self):
        import anthropic

        key = self.secrets.get("anthropic_api_key") or ""
        if not key:
            raise LLMError("Chave da API Anthropic não configurada.")
        if self._anthropic is None or key != self._anthropic_key:
            timeout = float(self.settings.get("ai.timeout_seconds", 30))
            self._anthropic = anthropic.Anthropic(api_key=key, timeout=timeout, max_retries=1)
            self._anthropic_key = key
        return self._anthropic

    def _anthropic_create(self, **kwargs):
        import anthropic

        model = self.settings.get("ai.anthropic_model", "claude-opus-5-5")
        request = dict(model=model, max_tokens=kwargs.pop("max_tokens", 4096),
                       output_config={"effort": self.settings.get("ai.effort", "low")}, **kwargs)
        # Fallback automático do servidor caso o modelo recuse por política
        # (disponível para Opus/Sonnet 5.5 e Fable; Haiku não tem fallback).
        if not model.startswith("claude-haiku"):
            request["betas"] = ["server-side-fallback-2026-07-01"]
            request["fallbacks"] = "default"
        try:
            return self._client().beta.messages.create(**request)
        except anthropic.AuthenticationError as exc:
            raise LLMError("A chave da API Anthropic foi recusada. Verifique em Configurações > IA.") from exc
        except anthropic.PermissionDeniedError as exc:
            raise LLMError("A chave da API não tem permissão para esse modelo.") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("Limite de uso da IA atingido. Tente novamente em instantes.") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Sem conexão com o serviço de IA. Comandos locais continuam funcionando.") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"O serviço de IA retornou erro {exc.status_code}.") from exc

    # ------------------------------------------------------------- Ollama
    def _ollama_chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        import httpx

        url = self.settings.get("ai.ollama_url", "http://localhost:11434").rstrip("/") + "/api/chat"
        body: dict[str, Any] = {"model": self.settings.get("ai.ollama_model", "llama3.1"),
                                "messages": messages, "stream": False}
        if tools:
            body["tools"] = [{"type": "function", "function": {
                "name": t["name"], "description": t["description"], "parameters": t["input_schema"]}} for t in tools]
        try:
            response = httpx.post(url, json=body, timeout=float(self.settings.get("ai.timeout_seconds", 30)) * 2)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError("O Ollama não respondeu. Verifique se ele está aberto e com o modelo baixado.") from exc
        return response.json().get("message", {})

    # ---------------------------------------------------------- texto simples
    def complete(self, prompt: str, max_tokens: int = 1200) -> str | None:
        """Pedido isolado (resumos, redação). Não altera o histórico da conversa."""
        if not self.available():
            return None
        try:
            if self.provider == "anthropic":
                response = self._anthropic_create(
                    max_tokens=max_tokens, system=self._system(),
                    messages=[{"role": "user", "content": prompt}])
                if response.stop_reason == "refusal":
                    return None
                return "".join(b.text for b in response.content if b.type == "text").strip() or None
            message = self._ollama_chat([{"role": "system", "content": self._system()},
                                         {"role": "user", "content": prompt}])
            return (message.get("content") or "").strip() or None
        except LLMError as exc:
            log.warning("IA indisponível: %s", exc)
            return None

    # ------------------------------------------------------ conversa + ações
    def resolve_pending_tool(self, outcome_text: str) -> None:
        """Registra o desfecho de uma ação que aguardava confirmação."""
        with self._lock:
            for item in self._pending_tool_results:
                if item.get("_awaiting"):
                    item["content"] = outcome_text
                    item.pop("_awaiting", None)

    def chat(self, user_text: str, context: str, tools: list[dict],
             execute_tool: Callable[[str, dict], Any], max_steps: int = 5) -> AgentOutcome:
        if not self.available():
            raise LLMError("Nenhum provedor de IA configurado.")
        with self._lock:
            idle = time.time() - self._last_used
            max_turns = int(self.settings.get("ai.max_history_turns", 20))
            if idle > 600 or len(self.messages) > max_turns * 4:
                # Recomeça a conversa em vez de editar o histórico antigo
                self.messages, self._pending_tool_results = [], []
            self._last_used = time.time()
            stamp = time.strftime("%d/%m/%Y %H:%M")
            text = f"[Agora: {stamp}]\n[Contexto recente]\n{context}\n\n[Pedido do usuário]\n{user_text}"
            if self.provider == "anthropic":
                return self._chat_anthropic(text, tools, execute_tool, max_steps)
            return self._chat_ollama(text, tools, execute_tool, max_steps)

    def _tool_result_text(self, result) -> str:
        parts = [result.say]
        if result.display:
            parts.append(result.display[:3000])
        return ("OK: " if result.ok else "FALHA: ") + "\n".join(parts)

    def _chat_anthropic(self, text, tools, execute_tool, max_steps) -> AgentOutcome:
        content: list[dict] = []
        for item in self._pending_tool_results:
            content.append({"type": "tool_result", "tool_use_id": item["tool_use_id"],
                            "content": item.get("content") or "O usuário não confirmou; nada foi executado."})
        self._pending_tool_results = []
        content.append({"type": "text", "text": text})
        self.messages.append({"role": "user", "content": content})
        outcome = AgentOutcome(text="")
        for _ in range(max_steps):
            response = self._anthropic_create(system=self._system(), messages=self.messages, tools=tools)
            self.messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason == "refusal":
                outcome.text = "Não posso ajudar com esse pedido."
                return outcome
            uses = [b for b in response.content if b.type == "tool_use"]
            said = "".join(b.text for b in response.content if b.type == "text").strip()
            if not uses:
                outcome.text = said or outcome.text or "Feito."
                return outcome
            results: list[dict] = []
            stop = False
            for use in uses:
                if stop:
                    results.append({"type": "tool_result", "tool_use_id": use.id,
                                    "content": "Não executado: aguardando confirmação de outra ação."})
                    continue
                result = execute_tool(use.name, dict(use.input or {}))
                outcome.actions.append(use.name)
                if result.undo:
                    outcome.undo, outcome.undo_label = result.undo, result.undo_label
                if result.display:
                    outcome.display = result.display
                if result.pending or result.follow_up:
                    # Pausa: o usuário precisa confirmar/responder. O resultado
                    # real é anexado na próxima mensagem (histórico só cresce).
                    outcome.text = result.say
                    outcome.pending, outcome.follow_up = result.pending, result.follow_up
                    outcome.expects_reply = True
                    self._pending_tool_results.append({"tool_use_id": use.id, "content": "", "_awaiting": True})
                    stop = True
                    continue
                results.append({"type": "tool_result", "tool_use_id": use.id,
                                "content": self._tool_result_text(result), "is_error": not result.ok})
            if stop:
                self._pending_tool_results = [
                    {"tool_use_id": r["tool_use_id"], "content": r["content"]} for r in results
                ] + self._pending_tool_results
                return outcome
            self.messages.append({"role": "user", "content": results})
        outcome.text = outcome.text or "Concluí as etapas possíveis."
        return outcome

    def _chat_ollama(self, text, tools, execute_tool, max_steps) -> AgentOutcome:
        if not self.messages:
            self.messages.append({"role": "system", "content": self._system()})
        for item in self._pending_tool_results:
            self.messages.append({"role": "tool", "content": item.get("content") or "O usuário não confirmou."})
        self._pending_tool_results = []
        self.messages.append({"role": "user", "content": text})
        outcome = AgentOutcome(text="")
        for _ in range(max_steps):
            message = self._ollama_chat(self.messages, tools)
            self.messages.append({"role": "assistant", "content": message.get("content", ""),
                                  "tool_calls": message.get("tool_calls", [])})
            calls = message.get("tool_calls") or []
            if not calls:
                outcome.text = (message.get("content") or "").strip() or "Feito."
                return outcome
            for call in calls:
                fn = call.get("function", {})
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                result = execute_tool(fn.get("name", ""), args)
                outcome.actions.append(fn.get("name", ""))
                if result.display:
                    outcome.display = result.display
                if result.undo:
                    outcome.undo, outcome.undo_label = result.undo, result.undo_label
                if result.pending or result.follow_up:
                    outcome.text, outcome.pending, outcome.follow_up = result.say, result.pending, result.follow_up
                    outcome.expects_reply = True
                    self._pending_tool_results.append({"content": "", "_awaiting": True})
                    return outcome
                self.messages.append({"role": "tool", "content": self._tool_result_text(result),
                                      "tool_name": fn.get("name", "")})
        outcome.text = outcome.text or "Concluí as etapas possíveis."
        return outcome

    def test(self) -> str:
        """Teste rápido usado pela tela de configurações."""
        text = self.complete("Responda apenas: conexão funcionando.", max_tokens=200)
        if not text:
            raise LLMError("Sem resposta do provedor de IA.")
        return text
