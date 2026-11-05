"""Envio de alertas via Telegram Bot API (oficial)."""
from __future__ import annotations

from config import settings as cfg
from services import http

API = "https://api.telegram.org/bot{token}/sendMessage"


def configured() -> bool:
    return cfg.is_configured("TELEGRAM_BOT_TOKEN") and cfg.is_configured("TELEGRAM_CHAT_ID")


def send(text: str) -> None:
    if not configured():
        raise RuntimeError("Telegram não configurado")
    for chunk in _chunks(text, 3900):
        resp = http.post(API.format(token=cfg.env("TELEGRAM_BOT_TOKEN")), json={
            "chat_id": cfg.env("TELEGRAM_CHAT_ID"), "text": chunk, "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })
        if resp.status_code != 200:
            raise RuntimeError(f"Telegram recusou a mensagem (HTTP {resp.status_code})")


def _chunks(text: str, n: int) -> list[str]:
    if len(text) <= n:
        return [text]
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > n:
            parts.append(cur)
            cur = ""
        cur += line + "\n"
    if cur:
        parts.append(cur)
    return parts
