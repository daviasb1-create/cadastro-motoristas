"""Configuração de ambiente do LOGISTICS INTELLIGENCE.

Credenciais ficam SEMPRE em variáveis de ambiente (.env local ou Secrets do
GitHub). Nada de chave de API no banco de dados ou no código.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
if not os.getenv("LI_SKIP_DOTENV"):
    load_dotenv(ENV_FILE, override=False)

DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
REPORTS_DIR = DATA_DIR / "relatorios"
for _d in (DATA_DIR, LOG_DIR, REPORTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

TIMEZONE = "America/Sao_Paulo"
APP_NAME = "LOGISTICS INTELLIGENCE"
APP_SUBTITLE = "Radar Comercial de Transportes"


def env(key: str, default: str | None = None) -> str | None:
    value = os.getenv(key)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def database_url() -> str:
    url = env("DATABASE_URL")
    if url:
        # Neon/Supabase/Heroku costumam entregar "postgres://"; o SQLAlchemy exige "postgresql://"
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        return url
    return f"sqlite:///{(DATA_DIR / 'logistics.db').as_posix()}"


def anthropic_model() -> str:
    return env("ANTHROPIC_MODEL", "claude-opus-5-5")


# Credenciais reconhecidas pelo sistema (exibidas mascaradas no painel).
CREDENTIALS = {
    "ANTHROPIC_API_KEY": "Claude API: análise de oportunidades, pesquisa na web e textos comerciais",
    "BRAVE_API_KEY": "Brave Search API: busca web/notícias/vagas",
    "SERPER_API_KEY": "Serper.dev: resultados do Google (web e notícias)",
    "TELEGRAM_BOT_TOKEN": "Token do bot do Telegram (alertas)",
    "TELEGRAM_CHAT_ID": "ID do chat/grupo do Telegram que recebe os alertas",
    "SMTP_HOST": "Servidor SMTP para alertas por e-mail",
    "SMTP_PORT": "Porta SMTP (587 para STARTTLS)",
    "SMTP_USER": "Usuário SMTP",
    "SMTP_PASSWORD": "Senha/App password SMTP",
    "ALERT_EMAIL_TO": "Destinatário dos alertas por e-mail",
    "MS_TENANT_ID": "Microsoft 365: tenant (rascunhos no Outlook via Graph)",
    "MS_CLIENT_ID": "Microsoft 365: client id do app registrado",
    "MS_CLIENT_SECRET": "Microsoft 365: client secret",
    "MS_SENDER_MAILBOX": "Caixa de e-mail onde os rascunhos serão criados",
    "DATABASE_URL": "Banco PostgreSQL (opcional; padrão SQLite local)",
}


def is_configured(key: str) -> bool:
    return env(key) is not None


def mask(value: str | None) -> str:
    if not value:
        return "não configurado"
    if len(value) <= 8:
        return "••••"
    return value[:4] + "••••" + value[-3:]


def write_env_value(key: str, value: str) -> None:
    """Grava/atualiza uma chave no arquivo .env local (uso pelo painel)."""
    if key not in CREDENTIALS and key != "ANTHROPIC_MODEL":
        raise ValueError(f"Chave não permitida: {key}")
    if "\n" in value or "\r" in value:
        raise ValueError("Valor inválido")
    lines: list[str] = []
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == key:
            lines[i] = f"{key}={value}"
            found = True
    if not found:
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value
