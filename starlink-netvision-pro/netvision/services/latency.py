"""Ping ICMP real sem exigir administrador.

* Windows: API nativa ``IcmpSendEcho`` (iphlpapi.dll), a mesma usada pelo ``ping.exe``.
* Linux/macOS: ``icmplib`` (socket ICMP não privilegiado, ou raw quando root).
"""
from __future__ import annotations

import ctypes
import os
import socket
import statistics
import struct
import sys
import threading
from collections import deque
from dataclasses import dataclass

IS_WINDOWS = sys.platform.startswith("win")


if IS_WINDOWS:
    from ctypes import wintypes

    class IP_OPTION_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("Ttl", ctypes.c_ubyte),
            ("Tos", ctypes.c_ubyte),
            ("Flags", ctypes.c_ubyte),
            ("OptionsSize", ctypes.c_ubyte),
            ("OptionsData", ctypes.c_void_p),
        ]

    class ICMP_ECHO_REPLY(ctypes.Structure):
        _fields_ = [
            ("Address", wintypes.ULONG),
            ("Status", wintypes.ULONG),
            ("RoundTripTime", wintypes.ULONG),
            ("DataSize", wintypes.USHORT),
            ("Reserved", wintypes.USHORT),
            ("Data", ctypes.c_void_p),
            ("Options", IP_OPTION_INFORMATION),
        ]

    _iphlp = ctypes.WinDLL("iphlpapi.dll", use_last_error=True)
    _iphlp.IcmpCreateFile.restype = wintypes.HANDLE
    _iphlp.IcmpCloseHandle.argtypes = [wintypes.HANDLE]
    _iphlp.IcmpSendEcho.argtypes = [
        wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p, wintypes.WORD,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
    ]
    _iphlp.IcmpSendEcho.restype = wintypes.DWORD
    _tls = threading.local()

    def _handle():
        h = getattr(_tls, "h", None)
        if h is None:
            h = _iphlp.IcmpCreateFile()
            _tls.h = h
        return h

    def ping_once(host: str, timeout_ms: int = 1000) -> float | None:
        """Retorna o RTT em ms (resolução de 1 ms da API) ou None em caso de perda."""
        try:
            ip = socket.gethostbyname(host)
        except OSError:
            return None
        addr = struct.unpack("<I", socket.inet_aton(ip))[0]
        payload = b"NetVisionPro-ping-" + b"x" * 14
        buf_size = ctypes.sizeof(ICMP_ECHO_REPLY) + len(payload) + 8
        buf = ctypes.create_string_buffer(buf_size)
        data = ctypes.create_string_buffer(payload, len(payload))
        n = _iphlp.IcmpSendEcho(_handle(), addr, data, len(payload), None, buf, buf_size, int(timeout_ms))
        if n == 0:
            return None
        reply = ICMP_ECHO_REPLY.from_buffer(buf)
        if reply.Status != 0:
            return None
        return float(reply.RoundTripTime)

else:
    from icmplib import ping as _icmp_ping

    _PRIV = hasattr(os, "geteuid") and os.geteuid() == 0

    def ping_once(host: str, timeout_ms: int = 1000) -> float | None:
        try:
            r = _icmp_ping(host, count=1, timeout=timeout_ms / 1000, privileged=_PRIV)
        except Exception:  # noqa: BLE001
            return None
        return r.avg_rtt if r.is_alive else None


@dataclass
class LatencyStats:
    target: str
    last_ms: float | None
    avg_ms: float | None
    min_ms: float | None
    max_ms: float | None
    jitter_ms: float | None
    loss_pct: float
    samples: int


class LatencyTracker:
    """Janela deslizante de amostras para calcular média, jitter (RFC 3550 simplificado) e perda."""

    def __init__(self, target: str, window: int = 60):
        self.target = target
        self.samples: deque[float | None] = deque(maxlen=window)
        self._lock = threading.Lock()

    def add(self, rtt: float | None) -> None:
        with self._lock:
            self.samples.append(rtt)

    def stats(self) -> LatencyStats:
        with self._lock:
            data = list(self.samples)
        ok = [s for s in data if s is not None]
        loss = (100.0 * (len(data) - len(ok)) / len(data)) if data else 0.0
        jitter = None
        if len(ok) >= 2:
            diffs = [abs(b - a) for a, b in zip(ok, ok[1:])]
            jitter = statistics.fmean(diffs)
        return LatencyStats(
            target=self.target,
            last_ms=data[-1] if data else None,
            avg_ms=statistics.fmean(ok) if ok else None,
            min_ms=min(ok) if ok else None,
            max_ms=max(ok) if ok else None,
            jitter_ms=jitter,
            loss_pct=loss,
            samples=len(data),
        )
