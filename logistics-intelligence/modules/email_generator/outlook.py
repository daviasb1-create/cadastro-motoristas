"""Integração oficial com o Outlook (Microsoft Graph): cria RASCUNHO, nunca envia.

Requer app registrado no Microsoft Entra ID com permissão de aplicativo
Mail.ReadWrite (consentida por um administrador) e as variáveis MS_* no .env.
"""
from __future__ import annotations

from config import settings as cfg
from services import http

REQUIRED = ("MS_TENANT_ID", "MS_CLIENT_ID", "MS_CLIENT_SECRET", "MS_SENDER_MAILBOX")


def configured() -> bool:
    return all(cfg.is_configured(k) for k in REQUIRED)


def _token() -> str:
    url = f"https://login.microsoftonline.com/{cfg.env('MS_TENANT_ID')}/oauth2/v2.0/token"
    resp = http.post(url, data={
        "client_id": cfg.env("MS_CLIENT_ID"), "client_secret": cfg.env("MS_CLIENT_SECRET"),
        "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials",
    })
    if resp.status_code != 200:
        raise RuntimeError(f"Falha ao autenticar no Microsoft 365 (HTTP {resp.status_code})")
    return resp.json()["access_token"]


def create_draft(to: str, subject: str, body: str) -> str:
    """Cria rascunho na caixa configurada e devolve o link para abri-lo."""
    if not configured():
        raise RuntimeError("Integração com Outlook não configurada")
    mailbox = cfg.env("MS_SENDER_MAILBOX")
    resp = http.post(
        f"https://graph.microsoft.com/v1.0/users/{mailbox}/messages",
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
        json={"subject": subject, "body": {"contentType": "Text", "content": body},
              "toRecipients": [{"emailAddress": {"address": to}}]},
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Microsoft Graph recusou o rascunho (HTTP {resp.status_code})")
    data = resp.json()
    return data.get("webLink") or data.get("id", "")
