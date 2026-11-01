"""Rede e DNS: teste de latência de DNS (offline, sem bibliotecas externas), troca reversível de DNS
e limpeza do cache DNS."""
from __future__ import annotations

import os
import random
import socket
import struct
import time

from ..utils import powershell, powershell_json, run
from .journal import Journal

DNS_PROVIDERS = {
    "cloudflare": ("Cloudflare", ["1.1.1.1", "1.0.0.1"]),
    "google": ("Google", ["8.8.8.8", "8.8.4.4"]),
    "quad9": ("Quad9 (bloqueia malware)", ["9.9.9.9", "149.112.112.112"]),
    "opendns": ("OpenDNS", ["208.67.222.222", "208.67.220.220"]),
    "adguard": ("AdGuard (bloqueia anúncios)", ["94.140.14.14", "94.140.15.15"]),
}
GID = "network:dns"


def _dns_query(server: str, domain: str, timeout: float = 1.5) -> float | None:
    """Envia uma consulta DNS (registro A) via UDP e retorna o tempo de resposta em ms."""
    tid = random.randint(0, 0xFFFF)
    header = struct.pack(">HHHHHH", tid, 0x0100, 1, 0, 0, 0)
    qname = b"".join(bytes([len(p)]) + p.encode() for p in domain.split(".")) + b"\x00"
    packet = header + qname + struct.pack(">HH", 1, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        t0 = time.perf_counter()
        s.sendto(packet, (server, 53))
        data, _ = s.recvfrom(512)
        if struct.unpack(">H", data[:2])[0] != tid:
            return None
        return (time.perf_counter() - t0) * 1000
    except OSError:
        return None
    finally:
        s.close()


def benchmark_dns(include_current: bool = True) -> list[dict]:
    """Mede a latência média (mediana de 5 consultas) de cada provedor de DNS."""
    domains = ["google.com", "youtube.com", "microsoft.com", "steampowered.com", "riotgames.com"]
    targets = [(k, name, servers[0]) for k, (name, servers) in DNS_PROVIDERS.items()]
    if include_current:
        for a in current_dns():
            for srv in a["servers"][:1]:
                if ":" not in srv:
                    targets.insert(0, ("current", f"Atual ({a['alias']})", srv))
    results = []
    for key, name, server in targets:
        times = [t for d in domains if (t := _dns_query(server, d)) is not None]
        med = sorted(times)[len(times) // 2] if times else None
        results.append({"key": key, "name": name, "server": server, "ms": med,
                        "fail": len(domains) - len(times)})
    results.sort(key=lambda r: r["ms"] if r["ms"] is not None else 9999)
    return results


def current_dns() -> list[dict]:
    """Adaptadores ativos com seus servidores DNS IPv4 e se são automáticos (DHCP)."""
    rows = powershell_json(
        "Get-NetAdapter | Where-Object Status -eq 'Up' | ForEach-Object { "
        "$d = Get-DnsClientServerAddress -InterfaceIndex $_.ifIndex -AddressFamily IPv4; "
        "$g = $_.InterfaceGuid; "
        "$ns = (Get-ItemProperty \"HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces\\$g\" "
        "-Name NameServer -ErrorAction SilentlyContinue).NameServer; "
        "[pscustomobject]@{Index=$_.ifIndex; Alias=$_.Name; Desc=$_.InterfaceDescription; "
        "Servers=@($d.ServerAddresses); Static=[bool]$ns} }")
    return [{"index": r.get("Index"), "alias": r.get("Alias"), "desc": r.get("Desc"),
             "servers": r.get("Servers") or [], "static": bool(r.get("Static"))} for r in rows]


def set_dns(provider: str, journal: Journal) -> tuple[bool, str]:
    name, servers = DNS_PROVIDERS[provider]
    adapters = current_dns()
    if not adapters:
        return False, "Nenhum adaptador de rede ativo encontrado."
    if journal.has_group(GID):
        journal.revert_group(GID)  # volta ao original antes de trocar novamente
        adapters = current_dns()
    journal.group(GID, f"DNS alterado para {name}", "rede")
    done = []
    for a in adapters:
        if a["static"]:
            prev = ",".join(f"'{s}'" for s in a["servers"])
            revert = f"Set-DnsClientServerAddress -InterfaceIndex {a['index']} -ServerAddresses @({prev})"
        else:
            revert = f"Set-DnsClientServerAddress -InterfaceIndex {a['index']} -ResetServerAddresses"
        srv = ",".join(f"'{s}'" for s in servers)
        r = powershell(f"Set-DnsClientServerAddress -InterfaceIndex {a['index']} -ServerAddresses @({srv})")
        if r.returncode == 0:
            journal.add_action(GID, {"kind": "ps", "script": revert, "desc": f"Restaurar DNS de {a['alias']}"})
            done.append(a["alias"])
    flush_dns()
    if not done:
        return False, "Não foi possível alterar o DNS (requer administrador)."
    return True, f"DNS {name} aplicado em: {', '.join(done)}."


def restore_dns(journal: Journal) -> list[str]:
    errs = journal.revert_group(GID)
    flush_dns()
    return errs


def flush_dns() -> bool:
    return run(["ipconfig", "/flushdns"]).returncode == 0


def ping(host: str = "1.1.1.1", count: int = 4) -> float | None:
    """Ping médio em ms usando o utilitário do Windows."""
    flag = "-n" if os.name == "nt" else "-c"
    out = run(["ping", flag, str(count), host], timeout=20).stdout
    import re
    times = [float(x.replace(",", ".")) for x in re.findall(r"[=<]\s*(\d+(?:[.,]\d+)?)\s*ms", out)]
    return sum(times) / len(times) if times else None
