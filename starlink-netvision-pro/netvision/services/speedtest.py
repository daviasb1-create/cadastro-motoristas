"""Teste de velocidade real com múltiplas conexões HTTP.

Usa os endpoints públicos do teste da Cloudflare (``/__down?bytes=N`` e ``/__up``), os mesmos
do site speed.cloudflare.com. A base é configurável, permitindo apontar para outro servidor
compatível. Latência sob o teste é medida com ping ICMP real em paralelo.
"""
from __future__ import annotations

import statistics
import threading
import time
from typing import Callable

import requests

from netvision.services.latency import ping_once

CHUNK = 64 * 1024


class _Counter:
    def __init__(self):
        self.n = 0
        self.lock = threading.Lock()

    def add(self, k: int):
        with self.lock:
            self.n += k


def _download_worker(base: str, stop: threading.Event, counter: _Counter, errors: list):
    s = requests.Session()
    while not stop.is_set():
        try:
            with s.get(f"{base}/__down", params={"bytes": 25_000_000}, stream=True, timeout=10) as r:
                r.raise_for_status()
                for chunk in r.iter_content(CHUNK):
                    if stop.is_set():
                        return
                    counter.add(len(chunk))
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
            if stop.wait(0.5):
                return


class _Stopped(Exception):
    """Interrompe um upload em andamento ao fim da medição."""


class _CountingBody:
    """Corpo de upload com tamanho fixo (Content-Length) que contabiliza bytes à medida que são enviados."""

    def __init__(self, size: int, counter: _Counter, stop: threading.Event):
        self.len = size
        self._left = size
        self._counter = counter
        self._stop = stop

    def __len__(self) -> int:
        return self.len

    def read(self, n: int = -1) -> bytes:
        if self._stop.is_set():
            raise _Stopped()
        if self._left <= 0:
            return b""
        n = CHUNK if n is None or n < 0 else min(n, CHUNK)
        n = min(n, self._left)
        self._left -= n
        self._counter.add(n)
        return b"0" * n


def _upload_worker(base: str, stop: threading.Event, counter: _Counter, errors: list):
    s = requests.Session()
    while not stop.is_set():
        try:
            r = s.post(f"{base}/__up", data=_CountingBody(10_000_000, counter, stop), timeout=15,
                       headers={"Content-Type": "application/octet-stream"})
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            if not stop.is_set():
                errors.append(str(e))
                if stop.wait(0.5):
                    return


def _measure(worker, base: str, streams: int, duration: float, progress: Callable | None, phase: str) -> float:
    stop = threading.Event()
    counter = _Counter()
    errors: list[str] = []
    threads = [threading.Thread(target=worker, args=(base, stop, counter, errors), daemon=True) for _ in range(streams)]
    for t in threads:
        t.start()
    # descarta o primeiro segundo (aceleração do TCP)
    warm = min(1.0, duration / 4)
    time.sleep(warm)
    start_bytes, t0 = counter.n, time.monotonic()
    while time.monotonic() - t0 < duration - warm:
        time.sleep(0.25)
        el = time.monotonic() - t0
        if progress and el > 0:
            progress(phase, (counter.n - start_bytes) * 8 / el / 1e6, min(1.0, el / (duration - warm)))
    elapsed = time.monotonic() - t0
    total = counter.n - start_bytes
    stop.set()
    for t in threads:
        t.join(timeout=3)
    if total == 0 and errors:
        raise RuntimeError(errors[-1])
    return total * 8 / elapsed / 1e6


def run_speedtest(base_url: str = "https://speed.cloudflare.com", duration: float = 8.0, streams: int = 4,
                  ping_host: str = "1.1.1.1", progress: Callable[[str, float, float], None] | None = None) -> dict:
    base = base_url.rstrip("/")
    result = {"ts": time.time(), "server": base, "ok": False, "error": None,
              "down_mbps": None, "up_mbps": None, "ping_ms": None, "jitter_ms": None}
    try:
        pings = [p for p in (ping_once(ping_host, 1000) for _ in range(5)) if p is not None]
        if pings:
            result["ping_ms"] = statistics.median(pings)
            if len(pings) > 1:
                result["jitter_ms"] = statistics.fmean(abs(b - a) for a, b in zip(pings, pings[1:]))
        if progress:
            progress("ping", result["ping_ms"] or 0, 1.0)
        result["down_mbps"] = _measure(_download_worker, base, streams, duration, progress, "download")
        result["up_mbps"] = _measure(_upload_worker, base, streams, duration, progress, "upload")
        result["ok"] = True
    except Exception as e:  # noqa: BLE001
        result["error"] = str(e)
    return result
