"""Consumo de rede por aplicativo no computador local.

Modo completo (Npcap instalado):
    Captura somente cabeçalhos dos pacotes (IPs, portas, tamanho) e dois metadados não
    cifrados: respostas DNS e o SNI do TLS ClientHello (nome do site informado em claro
    pelo próprio navegador). Nenhum conteúdo é armazenado nem decifrado. Cada porta local
    é associada ao processo dono via tabela de conexões do Windows (psutil).

Modo básico (sem Npcap):
    Lista processos com conexões ativas e os serviços remotos estimados pelo cache DNS do
    Windows (``ipconfig /displaydns``). Não há bytes por aplicativo nesse modo.
"""
from __future__ import annotations

import ipaddress
import logging
import re
import socket
import struct
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field

import psutil

from netvision.core.winsys import run_hidden
from netvision.services.classifier import classify_domain, friendly_process

log = logging.getLogger(__name__)
IS_WINDOWS = sys.platform.startswith("win")

PROTO_TCP, PROTO_UDP = 6, 17


# ------------------------------------------------------------ parsing de pacotes
@dataclass(slots=True)
class PacketInfo:
    src: str
    dst: str
    proto: int
    sport: int
    dport: int
    length: int
    payload: bytes


def parse_frame(data: bytes, linktype: int = 1) -> PacketInfo | None:
    """Interpreta um quadro Ethernet (DLT 1) ou IP bruto (DLT 101/12/228/229)."""
    off = 0
    if linktype == 1:
        if len(data) < 14:
            return None
        etype = struct.unpack_from("!H", data, 12)[0]
        off = 14
        while etype in (0x8100, 0x88A8) and len(data) >= off + 4:  # VLAN
            etype = struct.unpack_from("!H", data, off + 2)[0]
            off += 4
        if etype not in (0x0800, 0x86DD):
            return None
    elif linktype not in (12, 101, 228, 229):
        return None
    if len(data) < off + 1:
        return None
    ver = data[off] >> 4
    if ver == 4:
        if len(data) < off + 20:
            return None
        ihl = (data[off] & 0x0F) * 4
        total_len = struct.unpack_from("!H", data, off + 2)[0]
        proto = data[off + 9]
        src = socket.inet_ntop(socket.AF_INET, data[off + 12:off + 16])
        dst = socket.inet_ntop(socket.AF_INET, data[off + 16:off + 20])
        l4 = off + ihl
        length = total_len or (len(data) - off)
    elif ver == 6:
        if len(data) < off + 40:
            return None
        payload_len = struct.unpack_from("!H", data, off + 4)[0]
        proto = data[off + 6]
        src = socket.inet_ntop(socket.AF_INET6, data[off + 8:off + 24])
        dst = socket.inet_ntop(socket.AF_INET6, data[off + 24:off + 40])
        l4 = off + 40
        length = payload_len + 40
    else:
        return None
    sport = dport = 0
    payload = b""
    if proto == PROTO_TCP and len(data) >= l4 + 20:
        sport, dport = struct.unpack_from("!HH", data, l4)
        doff = (data[l4 + 12] >> 4) * 4
        payload = data[l4 + doff:]
    elif proto == PROTO_UDP and len(data) >= l4 + 8:
        sport, dport = struct.unpack_from("!HH", data, l4)
        payload = data[l4 + 8:]
    return PacketInfo(src, dst, proto, sport, dport, length, payload)


def parse_tls_sni(payload: bytes) -> str | None:
    """Extrai o Server Name Indication de um TLS ClientHello (texto em claro no handshake)."""
    try:
        if len(payload) < 43 or payload[0] != 0x16 or payload[5] != 0x01:
            return None
        p = 9 + 2 + 32  # header registro(5) + handshake(4) + versão + random
        sid_len = payload[p]
        p += 1 + sid_len
        cs_len = struct.unpack_from("!H", payload, p)[0]
        p += 2 + cs_len
        cm_len = payload[p]
        p += 1 + cm_len
        ext_total = struct.unpack_from("!H", payload, p)[0]
        p += 2
        end = min(len(payload), p + ext_total)
        while p + 4 <= end:
            etype, elen = struct.unpack_from("!HH", payload, p)
            p += 4
            if etype == 0x0000:  # server_name
                q = p + 2
                if payload[q] == 0:
                    nlen = struct.unpack_from("!H", payload, q + 1)[0]
                    return payload[q + 3:q + 3 + nlen].decode("ascii", "ignore").lower() or None
            p += elen
    except (IndexError, struct.error):
        return None
    return None


def parse_dns_answers(payload: bytes) -> list[tuple[str, str]]:
    """Retorna pares (nome consultado, IP) de uma resposta DNS. A cadeia CNAME é atribuída ao nome original."""
    try:
        from dnslib import QTYPE, DNSRecord

        rec = DNSRecord.parse(payload)
    except Exception:  # noqa: BLE001
        return []
    if not rec.header.qr or not rec.questions:
        return []
    qname = str(rec.questions[0].qname).rstrip(".").lower()
    out = []
    for rr in rec.rr:
        if rr.rtype in (QTYPE.A, QTYPE.AAAA):
            out.append((qname, str(rr.rdata)))
    return out


_DISPLAYDNS_VALUE = re.compile(r"^\s*[^:]+?:\s*(\S+)\s*$")
_HOSTNAME = re.compile(r"^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)+$")


def parse_displaydns(text: str) -> dict[str, str]:
    """Interpreta ``ipconfig /displaydns`` em qualquer idioma.

    Cada bloco começa com o nome consultado (linha sem ':' seguida de '-----'); todos os IPs
    do bloco, inclusive os obtidos via CNAME, são atribuídos a esse nome.
    """
    out: dict[str, str] = {}
    lines = text.splitlines()
    current = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if ":" not in stripped and _HOSTNAME.match(stripped) and nxt.startswith("---"):
            current = stripped.lower().rstrip(".")
            continue
        m = _DISPLAYDNS_VALUE.match(line)
        if not m or current is None:
            continue
        val = m.group(1).rstrip(".")
        try:
            ipaddress.ip_address(val)
        except ValueError:
            continue
        out.setdefault(val, current)
    return out


# ------------------------------------------------------------ dono das portas
class PortOwners:
    def __init__(self):
        self._map: dict[tuple[int, int], int] = {}
        self._names: dict[int, str] = {}
        self._last = 0.0
        self._lock = threading.Lock()

    def refresh(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last < 2.0:
            return
        self._last = now
        m: dict[tuple[int, int], int] = {}
        try:
            conns = psutil.net_connections(kind="inet")
        except (psutil.AccessDenied, OSError):
            conns = []
        for c in conns:
            if not c.laddr or not c.pid:
                continue
            proto = PROTO_TCP if c.type == socket.SOCK_STREAM else PROTO_UDP
            m[(proto, c.laddr.port)] = c.pid
        with self._lock:
            self._map = m

    def owner(self, proto: int, port: int) -> int | None:
        with self._lock:
            pid = self._map.get((proto, port))
        if pid is None and time.monotonic() - self._last > 0.5:
            self.refresh(force=True)
            with self._lock:
                pid = self._map.get((proto, port))
        return pid

    def name(self, pid: int | None) -> str:
        if pid is None:
            return "Desconhecido"
        n = self._names.get(pid)
        if n is None:
            try:
                n = psutil.Process(pid).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                n = "Processo protegido" if pid in (0, 4) else f"PID {pid}"
            self._names[pid] = n
        return n

    def connections_by_process(self) -> dict[str, dict]:
        out: dict[str, dict] = defaultdict(lambda: {"connections": 0, "remotes": set(), "pids": set()})
        try:
            conns = psutil.net_connections(kind="inet")
        except (psutil.AccessDenied, OSError):
            return {}
        for c in conns:
            if not c.raddr or not c.pid:
                continue
            app = friendly_process(self.name(c.pid))
            out[app]["connections"] += 1
            out[app]["remotes"].add(c.raddr.ip)
            out[app]["pids"].add(c.pid)
        return out


# ------------------------------------------------------------ monitor
@dataclass
class AppStat:
    rx: int = 0
    tx: int = 0
    rx_total: int = 0
    tx_total: int = 0
    pids: set = field(default_factory=set)
    services: dict = field(default_factory=lambda: defaultdict(int))
    connections: int = 0


def local_ips() -> set[str]:
    ips = set()
    for addrs in psutil.net_if_addrs().values():
        for a in addrs:
            if a.family in (socket.AF_INET, socket.AF_INET6):
                ips.add(a.address.split("%")[0])
    return ips


class AppMonitor:
    def __init__(self, interface: str = ""):
        self.interface = interface
        self.mode = "parado"
        self.error: str | None = None
        self.owners = PortOwners()
        self.ip_domain: dict[str, str] = {}
        self.stats: dict[str, AppStat] = defaultdict(AppStat)
        self.unpersisted: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        self.service_bytes: dict[str, int] = defaultdict(int)
        self.service_unpersisted: dict[str, int] = defaultdict(int)
        self._local = local_ips()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_tick = time.monotonic()
        self.packets = 0

    # -------- captura
    def _open_socket(self):
        from scapy.all import conf

        if IS_WINDOWS and not conf.use_pcap:
            raise RuntimeError("Npcap não instalado")
        iface = self.interface or conf.route.route("8.8.8.8")[0] or conf.iface
        try:
            sock = conf.L2listen(iface=iface, filter="ip or ip6", promisc=False)
        except Exception as e:  # noqa: BLE001 - sem compilador BPF: captura tudo e filtra no parser
            log.info("filtro BPF indisponível (%s); filtrando em Python", e)
            sock = conf.L2listen(iface=iface, promisc=False)
        raw = getattr(sock, "ins", None)  # Linux: socket do kernel; aumenta o buffer contra perdas em rajadas
        if hasattr(raw, "setsockopt"):
            try:
                raw.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
            except OSError:
                pass
        return sock, str(iface)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        try:
            sock, iface = self._open_socket()
        except Exception as e:  # noqa: BLE001
            self.mode = "básico"
            self.error = (f"Captura indisponível ({e}). Instale o Npcap para ver consumo por aplicativo; "
                          "exibindo apenas conexões ativas.")
            log.info(self.error)
            self._thread = threading.Thread(target=self._basic_loop, name="appmon-basic", daemon=True)
            self._thread.start()
            return
        self.mode = "completo"
        self.error = None
        self.interface = iface
        self._thread = threading.Thread(target=self._capture_loop, args=(sock,), name="appmon", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self.mode = "parado"

    @staticmethod
    def _linktype_for(cls) -> int:
        name = getattr(cls, "__name__", "")
        if name in ("Ether", "Dot3", "CookedLinux", ""):
            return 1 if name != "CookedLinux" else -1
        if name in ("IP", "IPv6", "IPv46"):
            return 101
        return -1

    def _capture_loop(self, sock) -> None:
        from scapy.automaton import select_objects

        self.owners.refresh(force=True)
        last_refresh = time.monotonic()
        try:
            while not self._stop.is_set():
                if not select_objects([sock], 0.5):
                    continue
                try:
                    cls, data, _ts = sock.recv_raw()
                except Exception:  # noqa: BLE001
                    continue
                if data:
                    lt = self._linktype_for(cls)
                    if lt > 0:
                        self._handle(bytes(data), lt)
                if time.monotonic() - last_refresh > 30:
                    self._local = local_ips()
                    last_refresh = time.monotonic()
        except Exception as e:  # noqa: BLE001
            self.error = f"Captura interrompida: {e}"
            log.exception("captura interrompida")
        finally:
            try:
                sock.close()
            except Exception:  # noqa: BLE001
                pass

    def _handle(self, data: bytes, linktype: int) -> None:
        pkt = parse_frame(data, linktype)
        if pkt is None:
            return
        self.packets += 1
        if pkt.proto == PROTO_UDP and pkt.sport == 53 and pkt.payload:
            for name, ip in parse_dns_answers(pkt.payload):
                self.ip_domain[ip] = name
        if pkt.src in self._local:
            outbound, lport, remote = True, pkt.sport, pkt.dst
            if pkt.proto == PROTO_TCP and pkt.dport == 443 and pkt.payload:
                sni = parse_tls_sni(pkt.payload)
                if sni:
                    self.ip_domain[remote] = sni
        elif pkt.dst in self._local:
            outbound, lport, remote = False, pkt.dport, pkt.src
        else:
            return
        if pkt.proto not in (PROTO_TCP, PROTO_UDP):
            app = "Outros (ICMP etc.)"
            pid = None
        else:
            pid = self.owners.owner(pkt.proto, lport)
            app = friendly_process(self.owners.name(pid))
        svc = "Não identificado"
        dom = self.ip_domain.get(remote)
        if dom:
            m = classify_domain(dom)
            svc = m.service if m else dom
        with self._lock:
            st = self.stats[app]
            if pid:
                st.pids.add(pid)
            if outbound:
                st.tx += pkt.length
                st.tx_total += pkt.length
                self.unpersisted[app][1] += pkt.length
            else:
                st.rx += pkt.length
                st.rx_total += pkt.length
                self.unpersisted[app][0] += pkt.length
            st.services[svc] += pkt.length
            self.service_bytes[svc] += pkt.length
            self.service_unpersisted[svc] += pkt.length

    def _basic_loop(self) -> None:
        while not self._stop.is_set():
            if IS_WINDOWS:
                self.ip_domain.update(parse_displaydns(run_hidden(["ipconfig", "/displaydns"], timeout=20)))
            procs = self.owners.connections_by_process()
            with self._lock:
                for st in self.stats.values():
                    st.connections = 0
                for app, info in procs.items():
                    st = self.stats[app]
                    st.connections = info["connections"]
                    st.pids = info["pids"]
                    st.services = defaultdict(int)
                    for r in info["remotes"]:
                        dom = self.ip_domain.get(r)
                        m = classify_domain(dom) if dom else None
                        st.services[m.service if m else (dom or r)] += 1
            self._stop.wait(5)

    # -------- leitura
    def snapshot(self) -> dict:
        """Taxas desde a última chamada (bits/s), totais e serviços por aplicativo."""
        now = time.monotonic()
        dt = max(now - self._last_tick, 1e-3)
        self._last_tick = now
        rows = []
        with self._lock:
            for app, st in self.stats.items():
                rows.append({
                    "app": app,
                    "rx_bps": st.rx * 8 / dt,
                    "tx_bps": st.tx * 8 / dt,
                    "rx_total": st.rx_total,
                    "tx_total": st.tx_total,
                    "connections": st.connections,
                    "pids": sorted(st.pids)[:8],
                    "services": sorted(st.services.items(), key=lambda kv: -kv[1])[:6],
                })
                st.rx = st.tx = 0
            services = sorted(self.service_bytes.items(), key=lambda kv: -kv[1])
        rows.sort(key=lambda r: -(r["rx_total"] + r["tx_total"] + r["connections"]))
        return {"mode": self.mode, "error": self.error, "interface": self.interface,
                "apps": rows, "services": services, "packets": self.packets}

    def take_unpersisted(self) -> tuple[dict[str, tuple[int, int]], dict[str, int]]:
        with self._lock:
            apps = {k: (v[0], v[1]) for k, v in self.unpersisted.items() if v[0] or v[1]}
            svcs = dict(self.service_unpersisted)
            self.unpersisted.clear()
            self.service_unpersisted.clear()
        return apps, svcs
