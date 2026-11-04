"""Persistência em SQLite: amostras por minuto, dispositivos, eventos, testes e uso por app."""
from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS minute_stats (
    ts INTEGER PRIMARY KEY,           -- início do minuto (epoch)
    pc_rx INTEGER DEFAULT 0,          -- bytes recebidos pelo computador
    pc_tx INTEGER DEFAULT 0,          -- bytes enviados pelo computador
    net_rx INTEGER DEFAULT 0,         -- bytes estimados da rede toda (integração do throughput da antena)
    net_tx INTEGER DEFAULT 0,
    ping_avg REAL, ping_min REAL, ping_max REAL, jitter REAL, loss_pct REAL,
    dish_ping REAL, dish_drop REAL, dish_state TEXT, devices INTEGER
);
CREATE TABLE IF NOT EXISTS speedtests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER, down_mbps REAL, up_mbps REAL, ping_ms REAL, jitter_ms REAL,
    server TEXT, ok INTEGER, error TEXT
);
CREATE TABLE IF NOT EXISTS devices (
    mac TEXT PRIMARY KEY, ip TEXT, hostname TEXT, vendor TEXT, custom_name TEXT,
    source TEXT, first_seen INTEGER, last_seen INTEGER, online INTEGER DEFAULT 0,
    random_mac INTEGER DEFAULT 0, iface TEXT, signal REAL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, level TEXT, kind TEXT, message TEXT
);
CREATE TABLE IF NOT EXISTS app_usage (
    day TEXT, app TEXT, rx INTEGER DEFAULT 0, tx INTEGER DEFAULT 0, PRIMARY KEY(day, app)
);
CREATE TABLE IF NOT EXISTS service_usage (
    day TEXT, source TEXT, service TEXT, hits INTEGER DEFAULT 0, bytes INTEGER DEFAULT 0,
    PRIMARY KEY(day, source, service)
);
CREATE TABLE IF NOT EXISTS device_usage (
    day TEXT, mac TEXT, rx INTEGER DEFAULT 0, tx INTEGER DEFAULT 0, PRIMARY KEY(day, mac)
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_speed_ts ON speedtests(ts);
"""


def day_str(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts if ts is not None else time.time()).strftime("%Y-%m-%d")


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ------------------------------------------------------------------ util
    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, tuple(params)).fetchall()]

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --------------------------------------------------------------- minutos
    def upsert_minute(self, ts: int, **values: Any) -> None:
        """Soma contadores de bytes e sobrescreve métricas de qualidade do minuto."""
        add_cols = {"pc_rx", "pc_tx", "net_rx", "net_tx"}
        with self._lock:
            self._conn.execute("INSERT OR IGNORE INTO minute_stats(ts) VALUES (?)", (ts,))
            sets, params = [], []
            for k, v in values.items():
                if v is None:
                    continue
                if k in add_cols:
                    sets.append(f"{k} = COALESCE({k},0) + ?")
                else:
                    sets.append(f"{k} = ?")
                params.append(v)
            if sets:
                self._conn.execute(f"UPDATE minute_stats SET {', '.join(sets)} WHERE ts = ?", (*params, ts))
            self._conn.commit()

    def minutes(self, since: int, until: int | None = None) -> list[dict]:
        until = until or int(time.time()) + 60
        return self.query("SELECT * FROM minute_stats WHERE ts >= ? AND ts < ? ORDER BY ts", (since, until))

    def daily_summary(self, days: int = 31) -> list[dict]:
        since = int(time.time()) - days * 86400
        return self.query(
            """SELECT date(ts,'unixepoch','localtime') AS dia,
                      SUM(pc_rx) AS pc_rx, SUM(pc_tx) AS pc_tx,
                      SUM(net_rx) AS net_rx, SUM(net_tx) AS net_tx,
                      AVG(ping_avg) AS ping_avg, AVG(jitter) AS jitter, AVG(loss_pct) AS loss_pct,
                      AVG(dish_ping) AS dish_ping, AVG(dish_drop) AS dish_drop,
                      COUNT(*) AS minutos,
                      SUM(CASE WHEN dish_state IS NOT NULL AND dish_state <> 'CONNECTED' THEN 1 ELSE 0 END) AS minutos_fora
               FROM minute_stats WHERE ts >= ? GROUP BY dia ORDER BY dia DESC""",
            (since,),
        )

    def monthly_summary(self, months: int = 13) -> list[dict]:
        since = int(time.time()) - months * 31 * 86400
        return self.query(
            """SELECT strftime('%Y-%m', ts,'unixepoch','localtime') AS mes,
                      SUM(pc_rx) AS pc_rx, SUM(pc_tx) AS pc_tx,
                      SUM(net_rx) AS net_rx, SUM(net_tx) AS net_tx,
                      AVG(ping_avg) AS ping_avg, AVG(jitter) AS jitter, AVG(loss_pct) AS loss_pct,
                      COUNT(*) AS minutos
               FROM minute_stats WHERE ts >= ? GROUP BY mes ORDER BY mes DESC""",
            (since,),
        )

    def usage_today(self) -> dict:
        start = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        r = self.query(
            "SELECT COALESCE(SUM(pc_rx),0) pc_rx, COALESCE(SUM(pc_tx),0) pc_tx, "
            "COALESCE(SUM(net_rx),0) net_rx, COALESCE(SUM(net_tx),0) net_tx FROM minute_stats WHERE ts >= ?",
            (start,),
        )
        return r[0]

    def usage_month(self) -> dict:
        start = int(datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp())
        r = self.query(
            "SELECT COALESCE(SUM(pc_rx),0) pc_rx, COALESCE(SUM(pc_tx),0) pc_tx, "
            "COALESCE(SUM(net_rx),0) net_rx, COALESCE(SUM(net_tx),0) net_tx FROM minute_stats WHERE ts >= ?",
            (start,),
        )
        return r[0]

    # ------------------------------------------------------------ speedtests
    def add_speedtest(self, result: dict) -> None:
        self.execute(
            "INSERT INTO speedtests(ts, down_mbps, up_mbps, ping_ms, jitter_ms, server, ok, error) VALUES (?,?,?,?,?,?,?,?)",
            (
                int(result.get("ts", time.time())), result.get("down_mbps"), result.get("up_mbps"),
                result.get("ping_ms"), result.get("jitter_ms"), result.get("server"),
                1 if result.get("ok") else 0, result.get("error"),
            ),
        )

    def speedtests(self, limit: int = 200) -> list[dict]:
        return self.query("SELECT * FROM speedtests ORDER BY ts DESC LIMIT ?", (limit,))

    # --------------------------------------------------------------- devices
    def get_devices(self) -> list[dict]:
        return self.query("SELECT * FROM devices ORDER BY online DESC, ip")

    def upsert_device(self, d: dict) -> None:
        with self._lock:
            row = self._conn.execute("SELECT mac FROM devices WHERE mac=?", (d["mac"],)).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO devices(mac, ip, hostname, vendor, source, first_seen, last_seen, online, random_mac, iface, signal)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (d["mac"], d.get("ip"), d.get("hostname"), d.get("vendor"), d.get("source"),
                     d.get("first_seen", int(time.time())), d.get("last_seen", int(time.time())),
                     1 if d.get("online", True) else 0, 1 if d.get("random_mac") else 0, d.get("iface"), d.get("signal")),
                )
            else:
                self._conn.execute(
                    "UPDATE devices SET ip=COALESCE(?,ip), hostname=COALESCE(NULLIF(?,''),hostname), vendor=COALESCE(NULLIF(?,''),vendor),"
                    " source=COALESCE(?,source), last_seen=?, online=?, random_mac=?, iface=COALESCE(?,iface), signal=COALESCE(?,signal)"
                    " WHERE mac=?",
                    (d.get("ip"), d.get("hostname") or "", d.get("vendor") or "", d.get("source"),
                     d.get("last_seen", int(time.time())), 1 if d.get("online", True) else 0,
                     1 if d.get("random_mac") else 0, d.get("iface"), d.get("signal"), d["mac"]),
                )
            self._conn.commit()

    def set_device_offline(self, mac: str) -> None:
        self.execute("UPDATE devices SET online=0 WHERE mac=?", (mac,))

    def set_custom_name(self, mac: str, name: str) -> None:
        self.execute("UPDATE devices SET custom_name=? WHERE mac=?", (name.strip() or None, mac))

    def forget_device(self, mac: str) -> None:
        self.execute("DELETE FROM devices WHERE mac=?", (mac,))

    def add_device_usage(self, mac: str, rx: int, tx: int, day: str | None = None) -> None:
        day = day or day_str()
        with self._lock:
            self._conn.execute(
                "INSERT INTO device_usage(day, mac, rx, tx) VALUES (?,?,?,?) "
                "ON CONFLICT(day, mac) DO UPDATE SET rx = rx + excluded.rx, tx = tx + excluded.tx",
                (day, mac, rx, tx),
            )
            self._conn.commit()

    def device_usage(self, day: str | None = None) -> dict[str, dict]:
        rows = self.query("SELECT mac, rx, tx FROM device_usage WHERE day=?", (day or day_str(),))
        return {r["mac"]: r for r in rows}

    # ---------------------------------------------------------------- events
    def add_event(self, kind: str, message: str, level: str = "info", ts: float | None = None) -> dict:
        ts = int(ts or time.time())
        self.execute("INSERT INTO events(ts, level, kind, message) VALUES (?,?,?,?)", (ts, level, kind, message))
        return {"ts": ts, "level": level, "kind": kind, "message": message}

    def events(self, limit: int = 300) -> list[dict]:
        return self.query("SELECT * FROM events ORDER BY ts DESC, id DESC LIMIT ?", (limit,))

    # ------------------------------------------------------------- app usage
    def add_app_usage(self, rows: dict[str, tuple[int, int]], day: str | None = None) -> None:
        day = day or day_str()
        with self._lock:
            for app, (rx, tx) in rows.items():
                self._conn.execute(
                    "INSERT INTO app_usage(day, app, rx, tx) VALUES (?,?,?,?) "
                    "ON CONFLICT(day, app) DO UPDATE SET rx = rx + excluded.rx, tx = tx + excluded.tx",
                    (day, app, rx, tx),
                )
            self._conn.commit()

    def app_usage(self, since_day: str) -> list[dict]:
        return self.query(
            "SELECT app, SUM(rx) rx, SUM(tx) tx FROM app_usage WHERE day >= ? GROUP BY app ORDER BY SUM(rx)+SUM(tx) DESC",
            (since_day,),
        )

    def add_service_usage(self, source: str, service: str, hits: int = 1, nbytes: int = 0, day: str | None = None) -> None:
        day = day or day_str()
        with self._lock:
            self._conn.execute(
                "INSERT INTO service_usage(day, source, service, hits, bytes) VALUES (?,?,?,?,?) "
                "ON CONFLICT(day, source, service) DO UPDATE SET hits = hits + excluded.hits, bytes = bytes + excluded.bytes",
                (day, source, service, hits, nbytes),
            )
            self._conn.commit()

    def service_usage(self, since_day: str) -> list[dict]:
        return self.query(
            "SELECT source, service, SUM(hits) hits, SUM(bytes) bytes FROM service_usage WHERE day >= ? "
            "GROUP BY source, service ORDER BY hits DESC",
            (since_day,),
        )

    # ---------------------------------------------------------------- limpeza
    def purge(self, retention_days: int) -> None:
        cutoff = int(time.time()) - retention_days * 86400
        self.execute("DELETE FROM minute_stats WHERE ts < ?", (cutoff,))
        self.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
        self.execute("DELETE FROM app_usage WHERE day < ?", (day_str(cutoff),))
        self.execute("DELETE FROM service_usage WHERE day < ?", (day_str(cutoff),))
        self.execute("DELETE FROM device_usage WHERE day < ?", (day_str(cutoff),))
