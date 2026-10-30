"""Banco SQLite local com histórico, notificações, lembretes e auditoria.

Tudo fica no computador do usuário (pasta de dados do JARVIS). A tela
"Privacidade e memória" permite visualizar e apagar cada tabela.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from . import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    data TEXT
);
CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity(ts);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    ts REAL NOT NULL,
    source TEXT NOT NULL,
    app TEXT,
    sender TEXT,
    title TEXT,
    body TEXT,
    important INTEGER NOT NULL DEFAULT 0,
    content_available INTEGER NOT NULL DEFAULT 1,
    seen INTEGER NOT NULL DEFAULT 0,
    spoken INTEGER NOT NULL DEFAULT 0,
    link TEXT,
    extra TEXT
);
CREATE INDEX IF NOT EXISTS idx_notifications_ts ON notifications(ts);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created REAL NOT NULL,
    due REAL NOT NULL,
    text TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS excel_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    workbook TEXT NOT NULL,
    sheet TEXT NOT NULL,
    address TEXT NOT NULL,
    before TEXT,
    after TEXT,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

TABLES = ("activity", "notifications", "reminders", "excel_audit", "conversation", "kv")


class Storage:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else paths.database_path()
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)

    # ------------------------------------------------------------------ util
    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, tuple(params))

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, tuple(params)).fetchall()]

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -------------------------------------------------------------- activity
    def log_activity(self, kind: str, text: str, data: dict | None = None) -> None:
        self.execute(
            "INSERT INTO activity(ts, kind, text, data) VALUES (?,?,?,?)",
            (time.time(), kind, text, json.dumps(data, ensure_ascii=False) if data else None),
        )

    def recent_activity(self, limit: int = 100) -> list[dict]:
        return self.query("SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,))

    # ------------------------------------------------------------- key/value
    def kv_get(self, key: str, default: Any = None) -> Any:
        rows = self.query("SELECT value FROM kv WHERE key=?", (key,))
        if not rows:
            return default
        try:
            return json.loads(rows[0]["value"])
        except (TypeError, json.JSONDecodeError):
            return default

    def kv_set(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO kv(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )

    # ---------------------------------------------------------- conversation
    def add_conversation(self, role: str, text: str) -> None:
        self.execute("INSERT INTO conversation(ts, role, text) VALUES (?,?,?)", (time.time(), role, text))

    # ----------------------------------------------------------- manutenção
    def purge_older_than(self, days: int) -> None:
        limit = time.time() - days * 86400
        for table in ("activity", "notifications", "conversation"):
            self.execute(f"DELETE FROM {table} WHERE ts < ?", (limit,))
        self.execute("DELETE FROM reminders WHERE done=1 AND due < ?", (limit,))

    def clear_table(self, table: str) -> None:
        if table not in TABLES:
            raise ValueError(f"Tabela desconhecida: {table}")
        self.execute(f"DELETE FROM {table}")

    def counts(self) -> dict[str, int]:
        return {t: self.query(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in TABLES}
