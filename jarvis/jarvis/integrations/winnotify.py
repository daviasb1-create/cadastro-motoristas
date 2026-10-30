"""Leitura das notificações do Windows (somente leitura, dados do próprio usuário).

O Windows 10/11 guarda as notificações exibidas na Central de Notificações no
banco local ``%LOCALAPPDATA%\\Microsoft\\Windows\\Notifications\\wpndatabase.db``.
O JARVIS abre esse arquivo apenas para leitura, com as permissões normais do
seu usuário. Não há acesso a sessões, tokens ou ao WhatsApp em si: só ao que
o próprio Windows mostrou como notificação.

Limitações (documentadas em docs/INTEGRACOES.md):
* o formato do banco não é documentado oficialmente e pode mudar;
* notificações apagadas antes da leitura não aparecem (lemos a cada poucos
  segundos para minimizar isso);
* se a prévia de mensagens estiver desligada no WhatsApp, só o remetente
  (ou nem ele) fica disponível.
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

QUERY = """
SELECT n.Id AS id, n.ArrivalTime AS arrival, n.Payload AS payload, h.PrimaryId AS handler
FROM Notification n JOIN NotificationHandler h ON n.HandlerId = h.RecordId
WHERE n.Type = 'toast' AND n.Id > ?
ORDER BY n.Id
"""


def default_db_path() -> Path:
    base = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    return Path(base) / "Microsoft" / "Windows" / "Notifications" / "wpndatabase.db"


def filetime_to_datetime(value: int | None) -> datetime:
    if not value:
        return datetime.now()
    try:
        utc = datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=int(value) // 10)
        return utc.astimezone().replace(tzinfo=None)
    except (OverflowError, ValueError):
        return datetime.now()


@dataclass
class WinNotification:
    id: int
    handler: str
    arrival: datetime
    texts: list[str] = field(default_factory=list)
    attribution: str = ""
    launch: str = ""

    @property
    def title(self) -> str:
        return self.texts[0] if self.texts else ""

    @property
    def body(self) -> str:
        return " ".join(self.texts[1:]).strip()


def parse_payload(payload: bytes | str | None) -> tuple[list[str], str, str]:
    """Extrai textos (título, corpo), atribuição e argumento de abertura do XML do toast."""
    if payload is None:
        return [], "", ""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="ignore")
    payload = payload.strip("\x00 \r\n")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return [], "", ""
    texts, attribution = [], ""
    for text in root.iter("text"):
        value = (text.text or "").strip()
        if not value:
            continue
        if text.get("placement") == "attribution":
            attribution = value
        else:
            texts.append(value)
    return texts, attribution, root.get("launch", "")


class NotificationDbReader:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_db_path()
        self.last_id = 0
        self._tmp: Path | None = None

    @property
    def available(self) -> bool:
        return self.path.exists()

    def _connect(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True, timeout=2)
            conn.execute("SELECT 1 FROM Notification LIMIT 1")
            return conn
        except sqlite3.Error:
            # Arquivo bloqueado: lê uma cópia temporária (banco + WAL)
            self._tmp = self._tmp or Path(tempfile.mkdtemp(prefix="jarvis_wpn_"))
            target = self._tmp / "wpn.db"
            shutil.copy2(self.path, target)
            for suffix in ("-wal", "-shm"):
                src = Path(str(self.path) + suffix)
                if src.exists():
                    shutil.copy2(src, Path(str(target) + suffix))
            return sqlite3.connect(str(target), timeout=2)

    def prime(self) -> None:
        """Marca as notificações já existentes como vistas (não anuncia o passado)."""
        if not self.available:
            return
        conn = self._connect()
        try:
            row = conn.execute("SELECT MAX(Id) FROM Notification").fetchone()
            self.last_id = int(row[0] or 0)
        finally:
            conn.close()

    def read_new(self) -> list[WinNotification]:
        if not self.available:
            return []
        conn = self._connect()
        try:
            rows = conn.execute(QUERY, (self.last_id,)).fetchall()
        finally:
            conn.close()
        result = []
        for nid, arrival, payload, handler in rows:
            self.last_id = max(self.last_id, int(nid))
            texts, attribution, launch = parse_payload(payload)
            if texts:
                result.append(WinNotification(int(nid), handler or "", filetime_to_datetime(arrival),
                                              texts, attribution, launch))
        return result
