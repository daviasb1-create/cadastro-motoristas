"""Scanner da rede local: descobre dispositivos ativos, novos e desconectados.

Estratégia (do mais completo ao mais simples, escolhida automaticamente):
1. Lista de clientes Wi-Fi do roteador Starlink (quando a API responde): nome DHCP, sinal, banda.
2. ARP ativo via Scapy (requer Npcap no Windows): resposta de praticamente todo dispositivo IPv4.
3. Varredura ICMP + leitura da tabela ARP do Windows (sem Npcap e sem administrador).
   Mesmo dispositivos que bloqueiam ping aparecem, pois o Windows resolve o ARP antes de enviar o ICMP.
"""
from __future__ import annotations

import ipaddress
import logging
import re
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import psutil

from netvision.core.winsys import run_hidden
from netvision.services import oui
from netvision.services.latency import ping_once

log = logging.getLogger(__name__)
IS_WINDOWS = sys.platform.startswith("win")
MAX_HOSTS = 1022

_ARP_WIN_LINE = re.compile(r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+([0-9a-fA-F]{2}(?:-[0-9a-fA-F]{2}){5})\s+(\S+)", re.M)
_ARP_WIN_IFACE = re.compile(r"^\S.*?(\d{1,3}(?:\.\d{1,3}){3})\s+---", re.M)


# ------------------------------------------------------------------ parsers
def parse_arp_windows(text: str, iface_ip: str | None = None) -> dict[str, str]:
    """Interpreta a saída de ``arp -a`` (qualquer idioma do Windows)."""
    result: dict[str, str] = {}
    current_iface = None
    for line in text.splitlines():
        m_if = _ARP_WIN_IFACE.match(line)
        if m_if:
            current_iface = m_if.group(1)
            continue
        m = _ARP_WIN_LINE.match(line)
        if not m:
            continue
        if iface_ip and current_iface and current_iface != iface_ip:
            continue
        ip, mac = m.group(1), oui.normalize_mac(m.group(2))
        if oui.is_valid_unicast(mac) and not ip.endswith(".255"):
            result[ip] = mac
    return result


def parse_proc_net_arp(text: str, iface: str | None = None) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        ip, flags, mac, dev = parts[0], parts[2], parts[3], parts[5]
        if flags == "0x0" or (iface and dev != iface):
            continue
        if oui.is_valid_unicast(mac):
            result[ip] = oui.normalize_mac(mac)
    return result


def parse_route_print_gateway(text: str) -> str | None:
    best = None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
            try:
                ipaddress.IPv4Address(parts[2])
                metric = int(parts[4])
            except ValueError:
                continue
            if best is None or metric < best[1]:
                best = (parts[2], metric)
    return best[0] if best else None


def parse_nbtstat_name(text: str) -> str:
    for line in text.splitlines():
        m = re.match(r"^\s*([^\s<]+)\s+<00>\s+UNI", line, re.I)
        if m:
            return m.group(1)
    return ""


# ---------------------------------------------------------------- interface
@dataclass
class LocalNetwork:
    ip: str
    netmask: str
    iface: str
    mac: str
    gateway: str | None

    @property
    def network(self) -> ipaddress.IPv4Network:
        return ipaddress.IPv4Network(f"{self.ip}/{self.netmask}", strict=False)


def _primary_ip() -> str | None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # UDP connect não envia pacotes; só escolhe a rota
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def default_gateway() -> str | None:
    if IS_WINDOWS:
        return parse_route_print_gateway(run_hidden(["route", "print", "-4", "0.0.0.0"]))
    try:
        with open("/proc/net/route") as f:
            for line in f.readlines()[1:]:
                p = line.split()
                if p[1] == "00000000" and int(p[3], 16) & 2:
                    return socket.inet_ntoa(bytes.fromhex(p[2])[::-1])
    except OSError:
        pass
    return None


def local_network() -> LocalNetwork | None:
    ip = _primary_ip()
    if not ip:
        return None
    link_family = getattr(psutil, "AF_LINK", -1)
    for name, addrs in psutil.net_if_addrs().items():
        if any(a.family == socket.AF_INET and a.address == ip for a in addrs):
            mask = next(a.netmask for a in addrs if a.family == socket.AF_INET and a.address == ip)
            mac = next((a.address for a in addrs if a.family == link_family), "")
            return LocalNetwork(ip=ip, netmask=mask or "255.255.255.0", iface=name,
                                mac=oui.normalize_mac(mac) if mac else "", gateway=default_gateway())
    return LocalNetwork(ip=ip, netmask="255.255.255.0", iface="", mac="", gateway=default_gateway())


def hosts_to_scan(net: LocalNetwork) -> list[str]:
    network = net.network
    if network.num_addresses - 2 > MAX_HOSTS:  # sub-rede grande: limita a um /22 ao redor do IP local
        network = ipaddress.IPv4Network(f"{net.ip}/22", strict=False)
    return [str(h) for h in network.hosts() if str(h) != net.ip]


def read_arp_table(net: LocalNetwork) -> dict[str, str]:
    if IS_WINDOWS:
        table = parse_arp_windows(run_hidden(["arp", "-a"]), iface_ip=net.ip)
    else:
        try:
            with open("/proc/net/arp") as f:
                table = parse_proc_net_arp(f.read(), iface=net.iface or None)
        except OSError:
            table = {}
    network = net.network
    return {ip: mac for ip, mac in table.items() if ipaddress.IPv4Address(ip) in network}


# ---------------------------------------------------------- nomes de host
def reverse_dns(ip: str) -> str:
    try:
        name = socket.gethostbyaddr(ip)[0]
        return "" if name == ip else name
    except OSError:
        return ""


def mdns_name(ip: str, timeout: float = 0.6) -> str:
    """Consulta PTR via mDNS unicast (porta 5353). iPhones, Macs, Chromecasts e impressoras respondem."""
    try:
        from dnslib import QTYPE, DNSRecord
    except ImportError:
        return ""
    rev = ".".join(reversed(ip.split("."))) + ".in-addr.arpa"
    q = DNSRecord.question(rev, "PTR")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(q.pack(), (ip, 5353))
        data, _ = s.recvfrom(4096)
        resp = DNSRecord.parse(data)
        for rr in resp.rr:
            if rr.rtype == QTYPE.PTR:
                return str(rr.rdata).rstrip(".").removesuffix(".local")
    except Exception:  # noqa: BLE001
        return ""
    finally:
        s.close()
    return ""


def netbios_name(ip: str) -> str:
    if not IS_WINDOWS:
        return ""
    return parse_nbtstat_name(run_hidden(["nbtstat", "-A", ip], timeout=6))


def resolve_name(ip: str) -> str:
    return reverse_dns(ip) or mdns_name(ip) or netbios_name(ip)


# ------------------------------------------------------------------ scanner
@dataclass
class ScanResult:
    devices: list[dict]
    new: list[dict] = field(default_factory=list)
    gone: list[dict] = field(default_factory=list)
    reconnected: list[dict] = field(default_factory=list)
    method: str = ""
    duration_s: float = 0.0
    network: str = ""


class NetworkScanner:
    def __init__(self, offline_after_misses: int = 2, resolve_names: bool = True):
        self.offline_after = max(1, offline_after_misses)
        self.resolve_names = resolve_names
        self.known: dict[str, dict] = {}
        self.misses: dict[str, int] = {}
        self._name_cache: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()
        self.first_scan_done = False

    def preload(self, devices: list[dict]) -> None:
        """Carrega dispositivos já conhecidos (do banco), todos considerados offline até serem vistos."""
        for d in devices:
            d = dict(d)
            d["online"] = False
            self.known[d["mac"]] = d

    def _scapy_arp(self, net: LocalNetwork, hosts: list[str]) -> dict[str, str] | None:
        try:
            from scapy.all import ARP, Ether, conf, srp

            if IS_WINDOWS and not conf.use_pcap:
                return None
            ans, _ = srp(Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=hosts), timeout=2, retry=1,
                         verbose=False, iface=net.iface or None)
            return {r.psrc: oui.normalize_mac(r.hwsrc) for _, r in ans}
        except Exception as e:  # noqa: BLE001 - sem Npcap/sem permissão: usa alternativa
            log.debug("ARP via Scapy indisponível: %s", e)
            return None

    def _icmp_sweep(self, hosts: list[str]) -> set[str]:
        with ThreadPoolExecutor(max_workers=64) as pool:
            res = list(pool.map(lambda h: (h, ping_once(h, 400)), hosts))
        return {h for h, rtt in res if rtt is not None}

    def _name_for(self, mac: str, ip: str) -> str:
        cached = self._name_cache.get(mac)
        if cached and time.time() - cached[1] < 3600:
            return cached[0]
        name = resolve_name(ip) if self.resolve_names else ""
        self._name_cache[mac] = (name, time.time())
        return name

    def scan(self, wifi_clients: list[dict] | None = None, use_active_arp: bool = True) -> ScanResult:
        t0 = time.time()
        net = local_network()
        if net is None:
            return ScanResult(devices=list(self.known.values()), method="sem rede")
        hosts = hosts_to_scan(net)
        found: dict[str, str] = {}
        methods = []

        arp = self._scapy_arp(net, hosts) if use_active_arp else None
        if arp is not None:
            found.update(arp)
            methods.append("ARP ativo")
        else:
            self._icmp_sweep(hosts)
            methods.append("ICMP + tabela ARP")
        found.update(read_arp_table(net))

        wifi_by_mac = {c["mac"]: c for c in (wifi_clients or []) if c.get("mac")}
        if wifi_by_mac:
            methods.append("API Starlink")
            for mac, c in wifi_by_mac.items():
                if c.get("ip"):
                    found[c["ip"]] = mac

        if net.mac:
            found[net.ip] = net.mac

        now = int(time.time())
        seen_macs: dict[str, str] = {mac: ip for ip, mac in found.items()}

        # resolução de nomes em paralelo
        need = [(m, ip) for m, ip in seen_macs.items() if not wifi_by_mac.get(m, {}).get("hostname")]
        names: dict[str, str] = {}
        if need:
            with ThreadPoolExecutor(max_workers=16) as pool:
                for (m, _), n in zip(need, pool.map(lambda x: self._name_for(*x), need)):
                    names[m] = n
        if net.mac:
            names[net.mac] = socket.gethostname()

        new, gone, back = [], [], []
        with self._lock:
            baseline = not self.first_scan_done and not self.known  # 1º uso: sem histórico, sem alertas
            for mac, ip in seen_macs.items():
                w = wifi_by_mac.get(mac, {})
                prev = self.known.get(mac)
                d = dict(prev or {})
                d.update({
                    "mac": mac, "ip": ip, "online": True, "last_seen": now,
                    "hostname": w.get("hostname") or names.get(mac) or d.get("hostname") or "",
                    "vendor": oui.vendor(mac) or d.get("vendor") or "",
                    "random_mac": oui.is_randomized(mac),
                    "source": "Starlink" if w else ("Este computador" if mac == net.mac else "Scanner"),
                    "iface": w.get("iface") or d.get("iface"),
                    "signal": w.get("signal", d.get("signal")),
                    "router_rx_bytes": w.get("router_rx_bytes"),
                    "router_tx_bytes": w.get("router_tx_bytes"),
                    "is_gateway": ip == net.gateway,
                    "is_self": mac == net.mac,
                })
                d.setdefault("first_seen", now)
                if prev is None:
                    d["baseline"] = baseline
                    new.append(d)
                elif not prev.get("online"):
                    back.append(d)
                self.known[mac] = d
                self.misses[mac] = 0
            for mac, d in self.known.items():
                if mac in seen_macs:
                    continue
                self.misses[mac] = self.misses.get(mac, 0) + 1
                if d.get("online") and self.misses[mac] >= self.offline_after:
                    d["online"] = False
                    gone.append(d)
            self.first_scan_done = True
            devices = sorted(self.known.values(),
                             key=lambda x: (not x.get("online"), ipaddress.IPv4Address(x.get("ip") or "0.0.0.0")))

        return ScanResult(devices=devices, new=new, gone=gone, reconnected=back, method=" + ".join(methods),
                          duration_s=time.time() - t0, network=str(net.network))
