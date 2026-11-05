import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Testes nunca usam credenciais reais nem rede
for k in ("ANTHROPIC_API_KEY", "BRAVE_API_KEY", "SERPER_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
          "SMTP_HOST", "MS_TENANT_ID", "DATABASE_URL"):
    os.environ.pop(k, None)
os.environ["LI_SKIP_DOTENV"] = "1"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    from database import db as dbmod

    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    dbmod.reset_engine(url)
    dbmod.init_db()
    yield dbmod


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    from services import http

    def blocked(*a, **k):
        raise http.SourceUnavailable("rede bloqueada nos testes")

    monkeypatch.setattr(http, "get", blocked)
    monkeypatch.setattr(http, "post", blocked)
    monkeypatch.setattr(http, "fetch_page", lambda *a, **k: None)
