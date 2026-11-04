import http.server
import socket
import threading
import time

import pytest

from netvision.core.database import Database
from netvision.services import oui
from netvision.services.appmonitor import (AppMonitor, parse_displaydns, parse_dns_answers, parse_frame,
                                           parse_tls_sni)
from netvision.services.classifier import classify_domain, friendly_process
from netvision.services.dnsproxy import DnsForwarder, ServiceHitCounter
from netvision.services.latency import LatencyTracker, ping_once
from netvision.services.reports import export_csv, export_html, fmt_bytes
from netvision.services.scanner import (parse_arp_windows, parse_nbtstat_name, parse_proc_net_arp,
                                        parse_route_print_gateway)
from netvision.services.speedtest import run_speedtest
from netvision.services.traffic import TrafficMeter

ARP_WIN_PT = """
Interface: 192.168.1.10 --- 0x7
  Endereço IP           Endereço físico       Tipo
  192.168.1.1           74-24-9f-aa-bb-cc     dinâmico
  192.168.1.20          3a-11-22-33-44-55     dinâmico
  192.168.1.255         ff-ff-ff-ff-ff-ff     estático
  224.0.0.22            01-00-5e-00-00-16     estático

Interface: 172.20.0.1 --- 0x11
  Endereço IP           Endereço físico       Tipo
  172.20.0.5            00-15-5d-01-02-03     dinâmico
"""

ROUTE_PRINT = """
IPv4 Tabela de rota
===========================================================================
Rotas ativas:
Endereço de rede             Máscara     Ender. gateway    Interface  Custo
          0.0.0.0          0.0.0.0      192.168.1.1     192.168.1.10     35
          0.0.0.0          0.0.0.0      10.0.0.1        10.0.0.5        50
"""

NBTSTAT = """
           Tabela de nomes NetBIOS de máquinas remotas

       Nome               Tipo         Status
    ---------------------------------------------
    DESKTOP-GAMER  <00>  UNIQUE      Registrado
    WORKGROUP      <00>  GROUP       Registrado
"""

DISPLAYDNS_PT = """
    www.youtube.com
    ----------------------------------------
    Nome do Registro . . . . . . : www.youtube.com
    Tipo de Registro . . . . . . : 5
    Tempo de Vida  . . . . . . . : 120
    Comprimento de Dados . . . . : 8
    Seção  . . . . . . . . . . . : Resposta
    Registro CNAME . . . . . . . : youtube-ui.l.google.com

    Nome do Registro . . . . . . : youtube-ui.l.google.com
    Tipo de Registro . . . . . . : 1
    Registro A (Host)  . . . . . : 142.250.79.46
"""


# ------------------------------------------------------------------ parsers
def test_parse_arp_windows_filters_interface_and_multicast():
    t = parse_arp_windows(ARP_WIN_PT, iface_ip="192.168.1.10")
    assert t == {"192.168.1.1": "74:24:9f:aa:bb:cc", "192.168.1.20": "3a:11:22:33:44:55"}


def test_parse_proc_net_arp():
    txt = ("IP address       HW type     Flags       HW address            Mask     Device\n"
           "192.168.1.1      0x1         0x2         74:24:9f:aa:bb:cc     *        wlan0\n"
           "192.168.1.9      0x1         0x0         00:00:00:00:00:00     *        wlan0\n")
    assert parse_proc_net_arp(txt) == {"192.168.1.1": "74:24:9f:aa:bb:cc"}


def test_parse_route_and_nbtstat():
    assert parse_route_print_gateway(ROUTE_PRINT) == "192.168.1.1"
    assert parse_nbtstat_name(NBTSTAT) == "DESKTOP-GAMER"


def test_displaydns_maps_ip_to_queried_name():
    m = parse_displaydns(DISPLAYDNS_PT)
    assert m["142.250.79.46"] == "www.youtube.com"


# ------------------------------------------------------------------ oui
def test_oui_vendor_and_random_mac():
    assert "VMware" in oui.vendor("00:0c:29:11:22:33")
    assert oui.is_randomized("3a:11:22:33:44:55")
    assert oui.vendor("3a:11:22:33:44:55") == "MAC privado (aleatório)"
    assert not oui.is_valid_unicast("01:00:5e:00:00:16")


# ------------------------------------------------------------------ classificador
@pytest.mark.parametrize("domain,service", [
    ("rr3---sn-bg0eznll.googlevideo.com", "YouTube"),
    ("youtubei.googleapis.com", "YouTube"),
    ("v16-webapp.tiktokcdn.com", "TikTok"),
    ("scontent.cdninstagram.com", "Instagram"),
    ("ipv4-c001-gru001-ix.1.oca.nflxvideo.net", "Netflix"),
    ("cache5-gru1.steamcontent.com", "Steam (downloads)"),
    ("gateway.discord.gg", "Discord"),
])
def test_classify_domain(domain, service):
    assert classify_domain(domain).service == service


def test_classify_shared_cdn_is_medium_confidence():
    m = classify_domain("scontent-gru1-1.xx.fbcdn.net")
    assert m.confidence == "média" and "Instagram" in m.service
    assert classify_domain("example.org") is None
    assert friendly_process("CS2.exe") == "Counter-Strike 2"


# ------------------------------------------------------------------ pacotes
def _client_hello(host: bytes) -> bytes:
    """ClientHello TLS 1.2 mínimo conforme RFC 5246/6066 (com extensão server_name)."""
    import struct
    sni = struct.pack("!BH", 0, len(host)) + host
    sni_list = struct.pack("!H", len(sni)) + sni
    ext = struct.pack("!HH", 0, len(sni_list)) + sni_list
    ext += struct.pack("!HH", 0x000b, 2) + b"\x01\x00"  # ec_point_formats antes/depois do SNI
    body = b"\x03\x03" + b"\x11" * 32 + b"\x00" + struct.pack("!H", 2) + b"\x13\x01" + b"\x01\x00"
    body += struct.pack("!H", len(ext)) + ext
    hs = b"\x01" + struct.pack("!I", len(body))[1:] + body
    return b"\x16\x03\x01" + struct.pack("!H", len(hs)) + hs


def test_sni_ignores_non_tls_and_truncated():
    assert parse_tls_sni(b"GET / HTTP/1.1\r\n") is None
    assert parse_tls_sni(_client_hello(b"a.com")[:30]) is None


def test_parse_frame_and_sni():
    from scapy.all import IP, TCP, UDP, Ether, Raw
    from scapy.layers.dns import DNS, DNSQR, DNSRR

    hello = _client_hello(b"www.netflix.com")
    frame = bytes(Ether() / IP(src="192.168.1.10", dst="1.2.3.4") / TCP(sport=50000, dport=443) / Raw(hello))
    p = parse_frame(frame, 1)
    assert (p.src, p.dst, p.sport, p.dport) == ("192.168.1.10", "1.2.3.4", 50000, 443)
    assert p.length == len(frame) - 14
    assert parse_tls_sni(p.payload) == "www.netflix.com"

    dns = DNS(id=1, qr=1, qd=DNSQR(qname="www.tiktok.com"),
              an=[DNSRR(rrname="www.tiktok.com", type="CNAME", rdata="a.tiktokcdn.com"),
                  DNSRR(rrname="a.tiktokcdn.com", type="A", rdata="23.1.2.3")])
    f2 = bytes(Ether() / IP(src="192.168.1.1", dst="192.168.1.10") / UDP(sport=53, dport=5353) / dns)
    p2 = parse_frame(f2, 1)
    assert parse_dns_answers(p2.payload) == [("www.tiktok.com", "23.1.2.3")]


def test_app_monitor_real_capture_on_loopback():
    """Captura real (root/Linux) no loopback: tráfego TCP gerado por este processo deve ser atribuído ao Python."""
    import os
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        pytest.skip("captura exige root no Linux / Npcap no Windows")
    mon = AppMonitor(interface="lo")
    mon.start()
    assert mon.mode == "completo", mon.error
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    port = srv.getsockname()[1]
    payload = b"x" * 200_000

    def serve():
        c, _ = srv.accept()
        while c.recv(65536):
            pass
        c.close()

    threading.Thread(target=serve, daemon=True).start()
    time.sleep(0.5)
    cli = socket.create_connection(("127.0.0.1", port))
    time.sleep(2.5)  # garante que a tabela de portas já conhece a conexão
    for _ in range(5):
        cli.sendall(payload)
        time.sleep(0.2)
    cli.close()
    time.sleep(1.0)
    snap = mon.snapshot()
    mon.stop()
    py = [a for a in snap["apps"] if a["app"] == "Python"]
    assert py, snap["apps"]
    # 1 MB enviado; a captura em espaço de usuário pode perder alguns pacotes em rajadas
    assert py[0]["tx_total"] + py[0]["rx_total"] >= 800_000


# ------------------------------------------------------------------ latência
def test_ping_loopback_and_stats():
    rtt = ping_once("127.0.0.1", 1000)
    assert rtt is not None and rtt < 50
    tr = LatencyTracker("x", window=10)
    for v in [10, 20, None, 10, 30]:
        tr.add(v)
    s = tr.stats()
    assert s.loss_pct == pytest.approx(20)
    assert s.avg_ms == pytest.approx(17.5)
    assert s.jitter_ms == pytest.approx((10 + 10 + 20) / 3)


def test_traffic_meter_counts_real_bytes():
    m = TrafficMeter(nics=None)
    assert m.sample() is None
    time.sleep(0.2)
    s = m.sample()
    assert s is not None and s.rx_bps >= 0 and s.tx_bps >= 0


# ------------------------------------------------------------------ speedtest
class _SpeedHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        n = 25_000_000
        self.send_response(200)
        self.send_header("Content-Length", str(n))
        self.end_headers()
        chunk = b"0" * 65536
        sent = 0
        try:
            while sent < n:
                self.wfile.write(chunk)
                sent += len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        if self.headers.get("Transfer-Encoding") == "chunked":
            while True:
                size = int(self.rfile.readline().strip() or b"0", 16)
                if size == 0:
                    self.rfile.readline()
                    break
                self.rfile.read(size + 2)
        else:
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


def test_speedtest_against_local_server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SpeedHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = run_speedtest(f"http://127.0.0.1:{srv.server_address[1]}", duration=2.0, streams=2, ping_host="127.0.0.1")
    finally:
        srv.shutdown()
    assert r["ok"], r["error"]
    assert r["down_mbps"] > 50 and r["up_mbps"] > 50
    assert r["ping_ms"] is not None


# ------------------------------------------------------------------ DNS local
def test_dns_forwarder_relays_and_logs():
    from dnslib import QTYPE, RR, A, DNSRecord

    up = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    up.bind(("127.0.0.1", 0))
    up_port = up.getsockname()[1]

    def upstream():
        data, addr = up.recvfrom(4096)
        q = DNSRecord.parse(data)
        r = q.reply()
        r.add_answer(RR(q.q.qname, QTYPE.A, rdata=A("142.250.0.1"), ttl=60))
        up.sendto(r.pack(), addr)

    threading.Thread(target=upstream, daemon=True).start()
    seen = []
    fwd = DnsForwarder(listen_port=0, listen_ip="127.0.0.1", upstream="127.0.0.1", upstream_port=up_port,
                       on_query=lambda ip, name: seen.append((ip, name)))
    assert fwd.start()
    port = fwd._sock.getsockname()[1]
    resp = DNSRecord.question("rr1.googlevideo.com").send("127.0.0.1", port, timeout=3)
    fwd.stop()
    up.close()
    assert str(DNSRecord.parse(resp).rr[0].rdata) == "142.250.0.1"
    assert seen == [("127.0.0.1", "rr1.googlevideo.com")]

    hc = ServiceHitCounter(dedup_s=30)
    hc.add("celular", "YouTube", "a.googlevideo.com", "alta")
    hc.add("celular", "YouTube", "b.googlevideo.com", "alta")
    assert hc.take() == {("celular", "YouTube"): 1}


# ------------------------------------------------------------------ banco e relatórios
def test_database_and_reports(tmp_path):
    db = Database(tmp_path / "t.sqlite3")
    now = int(time.time() // 60 * 60)
    db.upsert_minute(now, pc_rx=1000, pc_tx=500, net_rx=10_000, ping_avg=40.0, loss_pct=0.0, dish_state="CONNECTED")
    db.upsert_minute(now, pc_rx=1000)
    assert db.usage_today()["pc_rx"] == 2000
    db.upsert_device({"mac": "aa:bb:cc:dd:ee:ff", "ip": "192.168.1.5", "hostname": "pc", "vendor": "X", "source": "Scanner"})
    db.set_custom_name("aa:bb:cc:dd:ee:ff", "PC do escritório")
    assert db.get_devices()[0]["custom_name"] == "PC do escritório"
    db.add_app_usage({"Steam": (5000, 100)})
    db.add_app_usage({"Steam": (5000, 100)})
    assert db.app_usage("2000-01-01")[0]["rx"] == 10000
    db.add_speedtest({"ok": True, "down_mbps": 100, "up_mbps": 10, "ping_ms": 30, "server": "x"})
    db.add_event("teste", "evento")
    files = export_csv(db, tmp_path / "out")
    assert len(files) == 8 and all(f.exists() for f in files)
    html = export_html(db, tmp_path / "out").read_text(encoding="utf-8")
    assert "PC do escritório" in html and "Steam" in html
    assert db.daily_summary()[0]["pc_rx"] == 2000
    assert fmt_bytes(1536) == "1,5 KB"
