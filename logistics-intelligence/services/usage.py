"""Controle de consumo de APIs (chamadas, tokens e buscas por dia e fonte)."""
from __future__ import annotations

from sqlalchemy import select

from database.db import session_scope
from database.models import ApiUsage, Source
from services.timeutil import today

# Preços de referência (USD) usados apenas para ESTIMAR custo no painel.
PRICE_PER_MTOK_IN = 4.00   # Claude Opus 5.5 entrada
PRICE_PER_MTOK_OUT = 20.00  # Claude Opus 5.5 saída
PRICE_PER_WEB_SEARCH = 0.01  # US$ 10 / 1.000 buscas


def record(source_key: str, calls: int = 1, input_tokens: int = 0, output_tokens: int = 0,
           web_searches: int = 0) -> None:
    with session_scope() as s:
        row = s.scalar(select(ApiUsage).where(ApiUsage.day == today(), ApiUsage.source_key == source_key))
        if row is None:
            row = ApiUsage(day=today(), source_key=source_key, calls=0, input_tokens=0,
                           output_tokens=0, web_searches=0)
            s.add(row)
        row.calls += calls
        row.input_tokens += input_tokens
        row.output_tokens += output_tokens
        row.web_searches += web_searches


def used_today(source_key: str) -> int:
    with session_scope() as s:
        row = s.scalar(select(ApiUsage).where(ApiUsage.day == today(), ApiUsage.source_key == source_key))
        return row.calls if row else 0


def remaining_today(source_key: str) -> int:
    with session_scope() as s:
        src = s.scalar(select(Source).where(Source.key == source_key))
        limit = src.daily_limit if src else 50
    return max(0, limit - used_today(source_key))


def estimated_cost_usd(input_tokens: int, output_tokens: int, web_searches: int) -> float:
    return (input_tokens / 1e6 * PRICE_PER_MTOK_IN + output_tokens / 1e6 * PRICE_PER_MTOK_OUT
            + web_searches * PRICE_PER_WEB_SEARCH)
