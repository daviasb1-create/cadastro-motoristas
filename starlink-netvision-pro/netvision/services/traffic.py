"""Consumo de internet do computador (contadores reais das placas de rede via psutil)."""
from __future__ import annotations

import time
from dataclasses import dataclass

import psutil

_VIRTUAL_HINTS = ("loopback", "vethernet", "vmware", "virtualbox", "hyper-v", "npcap", "bluetooth",
                  "teredo", "isatap", "pseudo", "docker", "wsl", "tailscale", "zerotier", "lo")


@dataclass
class TrafficSample:
    ts: float
    rx_bps: float  # bits por segundo
    tx_bps: float
    rx_bytes: int  # bytes no intervalo
    tx_bytes: int


def physical_nics() -> list[str]:
    stats = psutil.net_if_stats()
    out = []
    for name, st in stats.items():
        low = name.lower()
        if not st.isup or low == "lo" or any(h in low for h in _VIRTUAL_HINTS if h != "lo"):
            continue
        out.append(name)
    return out


class TrafficMeter:
    def __init__(self, nics: list[str] | None = None):
        self.nics = nics
        self._last: tuple[float, int, int] | None = None

    def _counters(self) -> tuple[int, int]:
        per = psutil.net_io_counters(pernic=True)
        names = self.nics or physical_nics() or list(per)
        rx = sum(per[n].bytes_recv for n in names if n in per)
        tx = sum(per[n].bytes_sent for n in names if n in per)
        return rx, tx

    def sample(self) -> TrafficSample | None:
        now = time.monotonic()
        rx, tx = self._counters()
        last = self._last
        self._last = (now, rx, tx)
        if last is None:
            return None
        dt = max(now - last[0], 1e-3)
        drx, dtx = max(rx - last[1], 0), max(tx - last[2], 0)  # reinício de contador = 0
        return TrafficSample(ts=time.time(), rx_bps=drx * 8 / dt, tx_bps=dtx * 8 / dt, rx_bytes=drx, tx_bytes=dtx)
