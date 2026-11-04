"""Identificação de fabricante pelo MAC (base OUI do Wireshark embutida no Scapy, offline)."""
from __future__ import annotations

import functools
import re

_MAC_RE = re.compile(r"^([0-9a-f]{2}[:-]){5}[0-9a-f]{2}$", re.I)


def normalize_mac(mac: str) -> str:
    return mac.strip().lower().replace("-", ":")


def is_valid_unicast(mac: str) -> bool:
    mac = normalize_mac(mac)
    if not _MAC_RE.match(mac) or mac in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"):
        return False
    return not (int(mac[:2], 16) & 0x01)  # bit multicast


def is_randomized(mac: str) -> bool:
    """MAC "localmente administrado" (bit 2 do 1º octeto): típico de MAC privado em iOS/Android/Windows."""
    mac = normalize_mac(mac)
    try:
        return bool(int(mac[:2], 16) & 0x02)
    except ValueError:
        return False


@functools.lru_cache(maxsize=1)
def _manufdb():
    try:
        from scapy.all import conf

        return conf.manufdb
    except Exception:  # noqa: BLE001
        return None


@functools.lru_cache(maxsize=4096)
def vendor(mac: str) -> str:
    mac = normalize_mac(mac)
    if is_randomized(mac):
        return "MAC privado (aleatório)"
    db = _manufdb()
    if db is None:
        return ""
    try:
        name = db._get_manuf(mac)
    except Exception:  # noqa: BLE001
        return ""
    # _get_manuf devolve o próprio MAC quando não encontra
    if not name or normalize_mac(str(name)) == mac:
        return ""
    try:
        long_name = db.lookup(mac)[1]
        return long_name or name
    except Exception:  # noqa: BLE001
        return name
