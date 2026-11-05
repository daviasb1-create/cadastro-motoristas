"""Cliente da Claude API (Anthropic) com controle de custo e proteção contra invenção.

- Saídas estruturadas (JSON Schema) para extração de oportunidades.
- Ferramenta oficial de pesquisa na web (web_search) para descobrir oportunidades
  com fonte verificável.
- Fallback automático do lado do servidor em caso de recusa ("fallbacks": "default").
"""
from __future__ import annotations

import json
import re
from typing import Any

from config import settings as cfg
from services import usage
from services.logger import get_logger

log = get_logger("claude")

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AIUnavailable(Exception):
    pass


def available() -> bool:
    return cfg.is_configured("ANTHROPIC_API_KEY")


def _client():
    if not available():
        raise AIUnavailable("ANTHROPIC_API_KEY não configurada")
    import anthropic

    return anthropic.Anthropic(max_retries=3, timeout=300.0)


def _record(resp: Any, web_searches: int = 0) -> None:
    u = getattr(resp, "usage", None)
    usage.record("claude", calls=1,
                 input_tokens=getattr(u, "input_tokens", 0) or 0,
                 output_tokens=getattr(u, "output_tokens", 0) or 0,
                 web_searches=web_searches)


def _create(**kwargs) -> Any:
    """Chamada com fallback de recusa; se a conta não suportar o beta, tenta sem ele."""
    import anthropic

    client = _client()
    try:
        return client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
    except anthropic.BadRequestError as exc:
        if "fallback" in str(exc).lower():
            log.warning("Fallback de recusa indisponível nesta conta; repetindo sem ele.")
            return client.beta.messages.create(**kwargs)
        raise


def _text_of(resp: Any) -> str:
    return "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")


def call_json(system: str, user: str, schema: dict, effort: str = "low",
              max_tokens: int = 16000) -> dict | None:
    """Retorna o JSON validado pelo schema, ou None se recusado/truncado."""
    import anthropic

    try:
        resp = _create(
            model=cfg.anthropic_model(), max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        )
    except anthropic.AuthenticationError as exc:
        raise AIUnavailable("ANTHROPIC_API_KEY inválida") from exc
    except anthropic.RateLimitError as exc:
        raise AIUnavailable("Limite de uso da Claude API atingido") from exc
    except anthropic.APIStatusError as exc:
        raise AIUnavailable(f"Claude API HTTP {exc.status_code}") from exc
    except anthropic.APIConnectionError as exc:
        raise AIUnavailable("Sem conexão com a Claude API") from exc
    _record(resp)
    if resp.stop_reason == "refusal":
        log.warning("Claude recusou a solicitação (stop_reason=refusal).")
        return None
    if resp.stop_reason == "max_tokens":
        log.warning("Resposta da Claude truncada (max_tokens).")
        return None
    try:
        return json.loads(_text_of(resp))
    except json.JSONDecodeError:
        log.warning("Resposta da Claude não era JSON válido.")
        return None


def call_text(system: str, user: str, effort: str = "low", max_tokens: int = 4000) -> str | None:
    import anthropic

    try:
        resp = _create(model=cfg.anthropic_model(), max_tokens=max_tokens, system=system,
                       messages=[{"role": "user", "content": user}], output_config={"effort": effort})
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        raise AIUnavailable(str(exc.__class__.__name__)) from exc
    _record(resp)
    if resp.stop_reason in ("refusal", "max_tokens"):
        return None
    return _text_of(resp).strip() or None


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.S)


def _extract_json(text: str) -> Any:
    m = _JSON_BLOCK.search(text)
    candidate = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None


def web_research(system: str, user: str, max_searches: int = 5, effort: str = "medium",
                 max_tokens: int = 32000) -> tuple[Any, set[str]]:
    """Pesquisa na web com a ferramenta oficial. Retorna (json_final, urls_realmente_visitadas).

    As URLs retornadas servem para descartar qualquer item cuja fonte não tenha
    aparecido de fato nos resultados da busca (proteção contra invenção).
    """
    import anthropic

    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches,
              "user_location": {"type": "approximate", "country": "BR", "timezone": "America/Sao_Paulo"}}]
    messages: list[dict] = [{"role": "user", "content": user}]
    seen_urls: set[str] = set()
    resp = None
    for _ in range(4):  # retoma turnos pausados (pause_turn)
        try:
            client = _client()
            with client.beta.messages.stream(
                model=cfg.anthropic_model(), max_tokens=max_tokens, system=system, tools=tools,
                messages=messages, output_config={"effort": effort},
                betas=[FALLBACK_BETA], fallbacks="default",
            ) as stream:
                resp = stream.get_final_message()
        except anthropic.AuthenticationError as exc:
            raise AIUnavailable("ANTHROPIC_API_KEY inválida") from exc
        except anthropic.APIStatusError as exc:
            raise AIUnavailable(f"Claude API HTTP {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise AIUnavailable("Sem conexão com a Claude API") from exc
        turn_searches = 0
        for block in resp.content:
            btype = getattr(block, "type", "")
            if btype == "server_tool_use":
                turn_searches += 1
            if btype == "web_search_tool_result":
                content = getattr(block, "content", None)
                if isinstance(content, list):
                    for r in content:
                        url = getattr(r, "url", None)
                        if url:
                            seen_urls.add(url)
        _record(resp, web_searches=turn_searches)
        if resp.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": resp.content})
            continue
        break
    if resp is None or resp.stop_reason == "refusal":
        return None, seen_urls
    return _extract_json(_text_of(resp)), seen_urls
