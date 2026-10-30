"""Infraestrutura do sistema de ações (extensível).

Uma ação é uma função registrada com nome, descrição, esquema de parâmetros
e nível de risco. O mesmo registro atende:
  * o interpretador local (intenções -> ações);
  * o provedor de IA (as ações viram "ferramentas" que o modelo pode pedir);
  * os comandos personalizados do usuário (sequências de ações).

Para criar uma ação nova, basta decorar uma função em qualquer módulo de
``jarvis/actions`` com ``@action(...)`` e importá-lo em ``actions/__init__.py``.

Riscos:
  safe     executa direto;
  confirm  pede confirmação (voz "sim/não" ou botão) antes de executar;
  blocked  nunca executa por comando de voz.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ..brain.services import Services

log = logging.getLogger(__name__)


@dataclass
class PendingAction:
    """Ação aguardando confirmação explícita do usuário."""

    question: str
    execute: Callable[[], "ActionResult"]
    details: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    attempts: int = 0


@dataclass
class ActionResult:
    say: str
    ok: bool = True
    display: str | None = None  # texto mais longo para a interface
    undo: Callable[[], str] | None = None  # desfaz e retorna a frase falada
    undo_label: str = ""
    data: dict[str, Any] | None = None
    pending: PendingAction | None = None
    expects_reply: bool = False  # reabre o microfone sem palavra de ativação
    # Quando a ação precisa de uma informação a mais ("O que devo responder?"),
    # a próxima fala do usuário é entregue a esta função.
    follow_up: Callable[[str], "ActionResult"] | None = None

    @classmethod
    def fail(cls, say: str, display: str | None = None) -> "ActionResult":
        return cls(say=say, ok=False, display=display)


Handler = Callable[["Services", dict[str, Any]], ActionResult]


@dataclass
class ActionSpec:
    name: str
    description: str
    handler: Handler
    parameters: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    risk: str = "safe"
    llm: bool = True  # exposta como ferramenta para a IA
    confirm_text: Callable[[dict[str, Any]], str] | None = None

    def tool_schema(self) -> dict[str, Any]:
        schema = dict(self.parameters)
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        return {"name": self.name, "description": self.description, "input_schema": schema}


class Registry:
    def __init__(self) -> None:
        self._actions: dict[str, ActionSpec] = {}

    def register(self, spec: ActionSpec) -> None:
        if spec.name in self._actions:
            log.debug("Ação %s redefinida", spec.name)
        self._actions[spec.name] = spec

    def get(self, name: str) -> ActionSpec | None:
        return self._actions.get(name)

    def names(self) -> list[str]:
        return sorted(self._actions)

    def llm_tools(self) -> list[dict[str, Any]]:
        return [spec.tool_schema() for spec in sorted(self._actions.values(), key=lambda s: s.name) if spec.llm]

    def run(self, services: "Services", name: str, params: dict[str, Any] | None = None,
            confirmed: bool = False) -> ActionResult:
        spec = self._actions.get(name)
        params = dict(params or {})
        if spec is None:
            return ActionResult.fail("Não conheço essa ação.", display=f"Ação inexistente: {name}")
        if spec.risk == "blocked":
            return ActionResult.fail("Essa ação está bloqueada por segurança.")
        if spec.risk == "confirm" and not confirmed:
            question = spec.confirm_text(params) if spec.confirm_text else f"Confirma a ação {name}?"
            return ActionResult(
                say=question,
                pending=PendingAction(question=question,
                                      execute=lambda: self.run(services, name, params, confirmed=True),
                                      details=question),
                expects_reply=True,
            )
        try:
            return spec.handler(services, params)
        except ServiceUnavailable as exc:
            return ActionResult.fail(str(exc))
        except Exception as exc:  # noqa: BLE001 - qualquer falha vira resposta clara
            log.exception("Falha na ação %s", name)
            return ActionResult.fail("Não consegui concluir essa ação. Detalhes no registro.", display=str(exc))


class ServiceUnavailable(Exception):
    """Erro com mensagem amigável (serviço desconectado, sem internet, sem permissão)."""


REGISTRY = Registry()


def action(name: str, description: str, parameters: dict[str, Any] | None = None, risk: str = "safe",
           llm: bool = True, confirm_text: Callable[[dict[str, Any]], str] | None = None):
    def decorator(func: Handler) -> Handler:
        REGISTRY.register(ActionSpec(
            name=name, description=description, handler=func,
            parameters=parameters or {"type": "object", "properties": {}},
            risk=risk, llm=llm, confirm_text=confirm_text,
        ))
        return func

    return decorator


def props(required: list[str] | None = None, **properties: dict[str, Any]) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


STR = {"type": "string"}
INT = {"type": "integer"}
BOOL = {"type": "boolean"}
