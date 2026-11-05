"""Datas e horas sempre no fuso America/Sao_Paulo (armazenadas sem tzinfo)."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")


def now() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None, microsecond=0)


def today() -> date:
    return now().date()


def to_local(dt: datetime | None) -> datetime | None:
    """Converte datetime com fuso para horário local sem tzinfo."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(TZ).replace(tzinfo=None, microsecond=0)
    return dt


def fmt(dt: datetime | date | None, with_time: bool = True) -> str:
    if dt is None:
        return "Não identificado"
    if isinstance(dt, datetime):
        return dt.strftime("%d/%m/%Y %H:%M" if with_time else "%d/%m/%Y")
    return dt.strftime("%d/%m/%Y")
