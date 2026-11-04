"""Servidor DNS encaminhador opcional para identificar serviços usados por OUTROS aparelhos da rede.

Por que existe: o roteador integrado da Starlink Mini não exporta logs de DNS nem permite
espelhamento de tráfego, e o Wi-Fi WPA2/WPA3 cifra o tráfego de cada aparelho com chave
própria. Logo, o computador não enxerga o que o celular acessa. A única alternativa
legítima e funcional é o aparelho usar este computador como servidor DNS (configurado
manualmente no Wi-Fi do aparelho). As consultas são encaminhadas sem alteração ao DNS
upstream e somente o NOME consultado é registrado e classificado (estimativa).
"""
from __future__ import annotations

import logging
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

log = logging.getLogger(__name__)

# consultas de infraestrutura que não representam uso de serviço
_IGNORE_SUFFIXES = (".local", ".arpa", ".lan", ".home", "localhost")


class DnsForwarder:
    def __init__(self, listen_port: int = 53, upstream: str = "1.1.1.1", listen_ip: str = "0.0.0.0",
                 on_query: Callable[[str, str], None] | None = None, upstream_port: int = 53):
        self.listen = (listen_ip, listen_port)
        self.upstream = (upstream, upstream_port)
        self.on_query = on_query
        self._sock: socket.socket | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pool = ThreadPoolExecutor(max_workers=32, thread_name_prefix="dns")
        self.queries = 0
        self.error: str | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> bool:
        if self.running:
            return True
        self._stop.clear()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind(self.listen)
            s.settimeout(0.5)
        except OSError as e:
            self.error = (f"Não foi possível abrir a porta UDP {self.listen[1]}: {e}. "
                          "Verifique se outro serviço DNS usa a porta.")
            return False
        self._sock = s
        self.error = None
        self._thread = threading.Thread(target=self._loop, name="dns-forwarder", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._sock:
            self._sock.close()
            self._sock = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                data, client = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            self._pool.submit(self._forward, data, client)

    def _forward(self, data: bytes, client) -> None:
        up = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        up.settimeout(3)
        try:
            up.sendto(data, self.upstream)
            resp, _ = up.recvfrom(65535)
            if self._sock:
                self._sock.sendto(resp, client)
        except OSError:
            return
        finally:
            up.close()
        self.queries += 1
        name = self._qname(data)
        if name and self.on_query and not name.endswith(_IGNORE_SUFFIXES):
            try:
                self.on_query(client[0], name)
            except Exception:  # noqa: BLE001
                log.exception("on_query")

    @staticmethod
    def _qname(data: bytes) -> str | None:
        try:
            from dnslib import DNSRecord

            rec = DNSRecord.parse(data)
            if rec.questions:
                return str(rec.questions[0].qname).rstrip(".").lower()
        except Exception:  # noqa: BLE001
            return None
        return None


class ServiceHitCounter:
    """Agrupa consultas por (aparelho, serviço) com janela de deduplicação para não inflar contagens."""

    def __init__(self, dedup_s: float = 30.0):
        self.dedup_s = dedup_s
        self._last: dict[tuple[str, str], float] = {}
        self.pending: dict[tuple[str, str], int] = {}
        self.recent: list[dict] = []
        self._lock = threading.Lock()

    def add(self, source: str, service: str, domain: str, confidence: str) -> None:
        now = time.time()
        key = (source, service)
        with self._lock:
            if now - self._last.get(key, 0) < self.dedup_s:
                return
            self._last[key] = now
            self.pending[key] = self.pending.get(key, 0) + 1
            self.recent.insert(0, {"ts": now, "source": source, "service": service,
                                   "domain": domain, "confidence": confidence})
            del self.recent[300:]

    def take(self) -> dict[tuple[str, str], int]:
        with self._lock:
            out, self.pending = self.pending, {}
        return out
