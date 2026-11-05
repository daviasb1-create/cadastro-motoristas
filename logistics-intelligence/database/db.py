"""Conexão, criação das tabelas e acesso às configurações."""
from __future__ import annotations

import copy
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from config import settings as cfg
from config.defaults import DEFAULT_SETTINGS, DEFAULT_TEMPLATES
from database.models import Base, Setting, Source, Template

_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine(url: str | None = None):
    global _engine, _SessionLocal
    if _engine is None or url is not None:
        url = url or cfg.database_url()
        kwargs: dict[str, Any] = {"future": True, "pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        _engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _):  # noqa: ANN001
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def reset_engine(url: str) -> None:
    """Usado nos testes para apontar para outro banco."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None
    get_engine(url)


@contextmanager
def session_scope() -> Iterator[Session]:
    get_engine()
    assert _SessionLocal is not None
    s = _SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def init_db() -> None:
    """Cria tabelas e grava padrões que ainda não existem (idempotente)."""
    engine = get_engine()
    Base.metadata.create_all(engine)
    from modules.search.registry import SOURCE_DEFINITIONS  # import tardio evita ciclo

    with session_scope() as s:
        existing = {k for (k,) in s.execute(select(Setting.key))}
        for key, value in DEFAULT_SETTINGS.items():
            if key not in existing:
                s.add(Setting(key=key, value=copy.deepcopy(value)))
        tkeys = {k for (k,) in s.execute(select(Template.key))}
        for t in DEFAULT_TEMPLATES:
            if t["key"] not in tkeys:
                s.add(Template(key=t["key"], name=t["nome"], channel=t["canal"],
                               subject=t["assunto"], body=t["corpo"]))
        skeys = {k for (k,) in s.execute(select(Source.key))}
        for d in SOURCE_DEFINITIONS:
            if d["key"] not in skeys:
                s.add(Source(key=d["key"], name=d["name"], enabled=d.get("enabled", True),
                             daily_limit=d.get("daily_limit", 50), config=d.get("config", {})))


def get_setting(key: str, default: Any = None) -> Any:
    with session_scope() as s:
        row = s.get(Setting, key)
        if row is None:
            return copy.deepcopy(DEFAULT_SETTINGS.get(key, default))
        return copy.deepcopy(row.value)


def set_setting(key: str, value: Any) -> None:
    with session_scope() as s:
        row = s.get(Setting, key)
        if row is None:
            s.add(Setting(key=key, value=value))
        else:
            row.value = copy.deepcopy(value)


def all_settings() -> dict:
    data = copy.deepcopy(DEFAULT_SETTINGS)
    with session_scope() as s:
        for row in s.scalars(select(Setting)):
            data[row.key] = copy.deepcopy(row.value)
    return data
