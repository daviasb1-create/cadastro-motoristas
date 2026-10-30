"""Interpretação de expressões de tempo em português para lembretes.

Exemplos aceitos (após normalização e conversão de números):
    "em 10 minutos", "daqui a meia hora", "daqui a 1 hora e meia",
    "as 15:30", "as 3 e meia da tarde", "amanha as 8", "ao meio dia".
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from .numbers import words_to_digits

_REL = re.compile(
    r"\b(?:em|daqui a|daqui|dentro de|apos|depois de)\s+"
    r"(?:(?P<meia>meia hora)|(?P<n>\d+)\s*(?P<unit>segundos?|minutos?|min|horas?|h|dias?)"
    r"(?:\s+e\s+(?:(?P<half>meia)|(?P<n2>\d+)\s*(?P<unit2>minutos?|min)))?)"
)
_ABS = re.compile(
    r"\b(?:as|a|para as|pras|pra)\s+(?P<h>\d{1,2})(?:(?::|h|\s+e\s+|\s+horas\s+e\s+)(?P<m>\d{1,2}|meia))?"
    r"(?:\s*horas?)?(?:\s+(?P<period>da manha|da tarde|da noite|da madrugada))?\b"
)
_NOON = re.compile(r"\b(?:ao|as|a)\s+(?P<which>meio dia|meia noite)(?:\s+e\s+(?P<m>\d{1,2}|meia))?\b")


def parse_when(text: str, now: datetime | None = None) -> tuple[datetime | None, str]:
    """Retorna (momento, texto_sem_a_expressao). Momento None se nada encontrado."""
    now = now or datetime.now()
    text = words_to_digits(text)
    tomorrow = bool(re.search(r"\bamanha\b", text))

    match = _REL.search(text)
    if match:
        if match.group("meia"):
            delta = timedelta(minutes=30)
        else:
            n = int(match.group("n"))
            unit = match.group("unit")
            if unit.startswith("seg"):
                delta = timedelta(seconds=n)
            elif unit.startswith("min"):
                delta = timedelta(minutes=n)
            elif unit.startswith("h"):
                delta = timedelta(hours=n)
            else:
                delta = timedelta(days=n)
            if match.group("half"):
                delta += timedelta(minutes=30)
            elif match.group("n2"):
                delta += timedelta(minutes=int(match.group("n2")))
        return now + delta, _cleanup(text, match.span())

    match = _NOON.search(text)
    if match:
        hour = 12 if match.group("which") == "meio dia" else 0
        minute = _minute(match.group("m"))
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if tomorrow or due <= now:
            due += timedelta(days=1)
        return due, _cleanup(text, match.span())

    match = _ABS.search(text)
    if match:
        hour = int(match.group("h"))
        minute = _minute(match.group("m"))
        period = match.group("period")
        if hour > 23 or minute > 59:
            return None, text
        if period in ("da tarde", "da noite") and hour < 12:
            hour += 12
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if tomorrow:
            due += timedelta(days=1)
        elif due <= now:
            if not period and hour < 12 and due + timedelta(hours=12) > now:
                due += timedelta(hours=12)
            else:
                due += timedelta(days=1)
        return due, _cleanup(text, match.span())

    return None, text


def _minute(value: str | None) -> int:
    if not value:
        return 0
    return 30 if value == "meia" else int(value)


def _cleanup(text: str, span: tuple[int, int]) -> str:
    cleaned = (text[: span[0]] + " " + text[span[1]:])
    cleaned = re.sub(r"\b(amanha|hoje)\b", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def describe(due: datetime, now: datetime | None = None) -> str:
    """Descrição falada: 'hoje às 15:30', 'amanhã às 08:00' ou 'em 10 minutos'."""
    now = now or datetime.now()
    seconds = (due - now).total_seconds()
    if 0 < seconds < 3600:
        minutes = max(1, round(seconds / 60))
        return f"em {minutes} minuto{'s' if minutes != 1 else ''}"
    day = "hoje" if due.date() == now.date() else (
        "amanhã" if due.date() == (now + timedelta(days=1)).date() else due.strftime("%d/%m")
    )
    return f"{day} às {due:%H:%M}"
