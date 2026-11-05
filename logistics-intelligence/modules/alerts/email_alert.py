"""Alertas por e-mail via SMTP (para o PRÓPRIO usuário, nunca para leads)."""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from config import settings as cfg


def configured() -> bool:
    return all(cfg.is_configured(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "ALERT_EMAIL_TO"))


def send(subject: str, body: str) -> None:
    if not configured():
        raise RuntimeError("SMTP não configurado")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.env("SMTP_USER")
    msg["To"] = cfg.env("ALERT_EMAIL_TO")
    msg.set_content(body)
    port = int(cfg.env("SMTP_PORT", "587"))
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(cfg.env("SMTP_HOST"), port, context=ctx, timeout=30) as smtp:
            smtp.login(cfg.env("SMTP_USER"), cfg.env("SMTP_PASSWORD"))
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(cfg.env("SMTP_HOST"), port, timeout=30) as smtp:
            smtp.starttls(context=ctx)
            smtp.login(cfg.env("SMTP_USER"), cfg.env("SMTP_PASSWORD"))
            smtp.send_message(msg)
