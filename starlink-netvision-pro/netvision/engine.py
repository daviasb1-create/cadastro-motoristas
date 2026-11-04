"""Motor de monitoramento: threads de coleta + agregação + alertas, com sinais Qt para a interface."""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime
from typing import Callable

from PySide6.QtCore import QObject, Signal

from netvision.core.config import Settings
from netvision.core.database import Database, day_str
from netvision.services.appmonitor import AppMonitor
from netvision.services.classifier import classify_domain
from netvision.services.dnsproxy import DnsForwarder, ServiceHitCounter
from netvision.services.latency import LatencyTracker, ping_once
from netvision.services.scanner import NetworkScanner
from netvision.services.speedtest import run_speedtest
from netvision.services.starlink import ALERT_PT, STATE_PT, StarlinkClient
from netvision.services.traffic import TrafficMeter

log = logging.getLogger(__name__)
DISH_IP = "192.168.100.1"


class MinuteAggregator:
    def __init__(self):
        self.reset(self._minute())

    @staticmethod
    def _minute(ts: float | None = None) -> int:
        return int((ts or time.time()) // 60 * 60)

    def reset(self, ts: int) -> None:
        self.ts = ts
        self.pc_rx = self.pc_tx = 0
        self.net_rx = self.net_tx = 0.0
        self.dish_ping: list[float] = []
        self.dish_drop: list[float] = []
        self.dish_state: str | None = None


class Engine(QObject):
    starlink_updated = Signal(dict)
    wifi_clients_updated = Signal(dict)
    latency_updated = Signal(dict)
    traffic_updated = Signal(dict)
    devices_updated = Signal(dict)
    apps_updated = Signal(dict)
    speedtest_progress = Signal(str, float, float)
    speedtest_done = Signal(dict)
    event_added = Signal(dict)
    dns_updated = Signal(dict)
    monitoring_changed = Signal(bool)

    def __init__(self, settings: Settings, db: Database):
        super().__init__()
        self.s = settings
        self.db = db
        self._stop = threading.Event()
        self._active = threading.Event()
        self._threads: list[threading.Thread] = []
        self._agg = MinuteAggregator()
        self._agg_lock = threading.Lock()

        self.starlink = StarlinkClient(settings.dish_target, settings.router_targets)
        self.trackers = {t: LatencyTracker(t, settings.latency_window) for t in settings.ping_targets}
        self.dish_tracker = LatencyTracker(DISH_IP, settings.latency_window)
        self.traffic = TrafficMeter()
        self.scanner = NetworkScanner(settings.scan_offline_after_misses, settings.scan_resolve_names)
        self.scanner.preload(db.get_devices())
        self.apps = AppMonitor(settings.capture_interface)
        self.hits = ServiceHitCounter()
        self.dns: DnsForwarder | None = None

        self.last_wifi_clients: list[dict] = []
        self.last_router_counters: dict[str, tuple[int, int]] = {}
        self.last_starlink: dict = {}
        self.last_state: str | None = None
        self.last_alerts: set[str] = set()
        self.devices_online = 0
        self.speedtest_running = False
        self._last_quality_alert = 0.0
        self._last_dish_poll: float | None = None
        self._scan_now = threading.Event()
        self._wifi_ready = threading.Event()
        self.traffic_history: deque = deque(maxlen=600)

    # ------------------------------------------------------------ ciclo de vida
    @property
    def active(self) -> bool:
        return self._active.is_set()

    def start(self) -> None:
        loops: list[tuple[str, Callable]] = [
            ("starlink", self._loop_starlink),
            ("wifi", self._loop_wifi),
            ("latency", self._loop_latency),
            ("traffic", self._loop_traffic),
            ("scanner", self._loop_scanner),
            ("apps", self._loop_apps),
            ("speedtest-scheduler", self._loop_speed_scheduler),
            ("minute", self._loop_minute),
        ]
        for name, fn in loops:
            t = threading.Thread(target=self._guard(fn), name=name, daemon=True)
            t.start()
            self._threads.append(t)
        if self.s.monitoring_on_start:
            self.resume()
        if self.s.dns_proxy_enabled:
            self.start_dns()

    def _guard(self, fn: Callable) -> Callable:
        def run():
            while not self._stop.is_set():
                try:
                    fn()
                    return
                except Exception:  # noqa: BLE001 - uma falha não derruba o monitoramento
                    log.exception("falha na thread %s; reiniciando em 5 s", threading.current_thread().name)
                    self._stop.wait(5)
        return run

    def resume(self) -> None:
        if not self._active.is_set():
            self._active.set()
            if self.s.app_monitor_enabled:
                self.apps.start()
            self._emit_event("sistema", "Monitoramento iniciado")
            self.monitoring_changed.emit(True)

    def pause(self) -> None:
        if self._active.is_set():
            self._active.clear()
            self.apps.stop()
            self._flush_minute(force=True)
            self._emit_event("sistema", "Monitoramento pausado")
            self.monitoring_changed.emit(False)

    def shutdown(self) -> None:
        self._flush_minute(force=True)
        self._stop.set()
        self._active.set()  # destrava loops em espera
        self.apps.stop()
        if self.dns:
            self.dns.stop()
        self.starlink.close()

    def _wait(self, seconds: float) -> bool:
        """Espera respeitando pausa e encerramento. Retorna False se o app está encerrando."""
        if self._stop.wait(seconds):
            return False
        while not self._active.is_set():
            if self._stop.wait(0.5):
                return False
        return not self._stop.is_set()

    # ------------------------------------------------------------ eventos
    def _emit_event(self, kind: str, message: str, level: str = "info") -> None:
        ev = self.db.add_event(kind, message, level)
        self.event_added.emit(ev)

    # ------------------------------------------------------------ Starlink
    def _loop_starlink(self) -> None:
        last_hist = 0.0
        hist: dict = {}
        while self._wait(0 if self._last_dish_poll is None else self.s.starlink_interval_s):
            snap = self.starlink.get_status()
            now = time.time()
            data = {"ok": snap.ok, "error": snap.error, "status": snap.status, "state": snap.state,
                    "state_pt": snap.state_pt, "alerts": snap.active_alerts,
                    "alerts_pt": [ALERT_PT.get(a, a.replace("alert_", "").replace("_", " ")) for a in snap.active_alerts],
                    "extra": snap.extra, "ts": now}
            if snap.ok:
                if now - last_hist > 60:
                    hist = self.starlink.get_history_stats(900)
                    last_hist = now
                data["history"] = hist
                st = snap.status
                with self._agg_lock:
                    if self._last_dish_poll is not None:
                        dt = min(now - self._last_dish_poll, 10.0)
                        self._agg.net_rx += (st.get("downlink_throughput_bps") or 0) * dt / 8
                        self._agg.net_tx += (st.get("uplink_throughput_bps") or 0) * dt / 8
                    if st.get("pop_ping_latency_ms") is not None:
                        self._agg.dish_ping.append(st["pop_ping_latency_ms"])
                    if st.get("pop_ping_drop_rate") is not None:
                        self._agg.dish_drop.append(st["pop_ping_drop_rate"] * 100)
                    self._agg.dish_state = snap.state
            else:
                with self._agg_lock:
                    self._agg.dish_state = "OFFLINE"
            self._last_dish_poll = now
            self._check_starlink_changes(snap.state, set(snap.active_alerts))
            self.last_starlink = data
            self.starlink_updated.emit(data)

    def _check_starlink_changes(self, state: str, alerts: set[str]) -> None:
        if self.last_state is not None and state != self.last_state:
            lvl = "info" if state == "CONNECTED" else "alerta"
            self._emit_event("starlink", f"Estado da Starlink: {STATE_PT.get(self.last_state, self.last_state)} → "
                                         f"{STATE_PT.get(state, state)}", lvl)
        for a in alerts - self.last_alerts:
            self._emit_event("starlink", f"Alerta da antena: {ALERT_PT.get(a, a)}", "alerta")
        self.last_state, self.last_alerts = state, alerts

    def _loop_wifi(self) -> None:
        first = True
        while self._wait(0 if first else self.s.wifi_clients_interval_s):
            first = False
            res = self.starlink.get_wifi_clients()
            if res.ok:
                self.last_wifi_clients = res.clients
                self._account_router_counters(res.clients)
            self._wifi_ready.set()
            self.wifi_clients_updated.emit({"ok": res.ok, "clients": res.clients, "target": res.target,
                                            "error": res.error, "log": list(self.starlink.router_probe_log)})

    def _account_router_counters(self, clients: list[dict]) -> None:
        for c in clients:
            mac, rx, tx = c.get("mac"), c.get("router_rx_bytes"), c.get("router_tx_bytes")
            if not mac or rx is None or tx is None:
                continue
            prev = self.last_router_counters.get(mac)
            self.last_router_counters[mac] = (rx, tx)
            if prev is None:
                continue
            d_up = rx - prev[0] if rx >= prev[0] else rx
            d_down = tx - prev[1] if tx >= prev[1] else tx
            if d_up or d_down:
                self.db.add_device_usage(mac, rx=d_down, tx=d_up)  # rx/tx do ponto de vista do aparelho

    # ------------------------------------------------------------ latência
    def _loop_latency(self) -> None:
        targets = list(self.trackers.items())
        while self._wait(self.s.ping_interval_s):
            for host, tr in targets:
                tr.add(ping_once(host, self.s.ping_timeout_ms))
            self.dish_tracker.add(ping_once(DISH_IP, 500))
            per = {h: vars(tr.stats()) for h, tr in targets}
            primary = per[targets[0][0]] if targets else {}
            out = {"targets": per, "primary": primary, "dish": vars(self.dish_tracker.stats()), "ts": time.time()}
            self.latency_updated.emit(out)
            self._check_quality(primary)

    def _check_quality(self, p: dict) -> None:
        if not p or p.get("samples", 0) < 20 or time.time() - self._last_quality_alert < 300:
            return
        if p.get("loss_pct", 0) >= self.s.alert_loss_pct:
            self._last_quality_alert = time.time()
            self._emit_event("qualidade", f"Perda de pacotes elevada: {p['loss_pct']:.1f}% para {p['target']}", "alerta")
        elif (p.get("avg_ms") or 0) >= self.s.alert_ping_ms:
            self._last_quality_alert = time.time()
            self._emit_event("qualidade", f"Ping médio alto: {p['avg_ms']:.0f} ms para {p['target']}", "alerta")

    # ------------------------------------------------------------ tráfego
    def _loop_traffic(self) -> None:
        self.traffic.sample()
        while self._wait(1.0):
            smp = self.traffic.sample()
            if smp is None:
                continue
            with self._agg_lock:
                self._agg.pc_rx += smp.rx_bytes
                self._agg.pc_tx += smp.tx_bytes
            self.traffic_history.append((smp.ts, smp.rx_bps, smp.tx_bps))
            self.traffic_updated.emit({"ts": smp.ts, "rx_bps": smp.rx_bps, "tx_bps": smp.tx_bps})

    # ------------------------------------------------------------ dispositivos
    def request_scan(self) -> None:
        self._scan_now.set()

    def _loop_scanner(self) -> None:
        first = True
        while not self._stop.is_set():
            if not first:
                self._scan_now.wait(self.s.scan_interval_s)
                self._scan_now.clear()
            if not self._wait(0 if first else 0.1):
                return
            if first:
                self._wifi_ready.wait(8)  # usa nomes do roteador já na 1ª varredura
            first = False
            res = self.scanner.scan(self.last_wifi_clients)
            for d in res.devices:
                if d.get("online"):
                    self.db.upsert_device(d)
            for d in res.gone:
                self.db.set_device_offline(d["mac"])
                self._emit_event("dispositivo", f"Desconectado: {self._dev_label(d)} ({d.get('ip')})")
            for d in res.reconnected:
                self._emit_event("dispositivo", f"Reconectado: {self._dev_label(d)} ({d.get('ip')})")
            for d in res.new:
                if d.get("baseline"):
                    continue
                lvl = "alerta" if self.s.notify_new_devices else "info"
                self._emit_event("novo_dispositivo",
                                 f"Novo dispositivo: {self._dev_label(d)} · {d.get('ip')} · {d.get('mac')}", lvl)
            db_devs = {r["mac"]: r for r in self.db.get_devices()}
            merged = []
            for d in res.devices:
                row = dict(d)
                if d["mac"] in db_devs:
                    row["custom_name"] = db_devs[d["mac"]].get("custom_name")
                merged.append(row)
            self.devices_online = sum(1 for d in merged if d.get("online"))
            self.devices_updated.emit({"devices": merged, "method": res.method, "duration": res.duration_s,
                                       "network": res.network, "usage": self.db.device_usage(),
                                       "new": [d for d in res.new if not d.get("baseline")]})

    def _dev_label(self, d: dict) -> str:
        row = self.db.query("SELECT custom_name FROM devices WHERE mac=?", (d.get("mac"),))
        custom = row[0]["custom_name"] if row else None
        return custom or d.get("hostname") or d.get("vendor") or "sem nome"

    # ------------------------------------------------------------ aplicativos
    def _loop_apps(self) -> None:
        last_persist = time.time()
        while self._wait(1.0):
            snap = self.apps.snapshot()
            snap["dns_hits"] = list(self.hits.recent[:200])
            self.apps_updated.emit(snap)
            if time.time() - last_persist >= 60:
                self._persist_apps()
                last_persist = time.time()

    def _persist_apps(self) -> None:
        apps, svcs = self.apps.take_unpersisted()
        if apps:
            self.db.add_app_usage(apps)
        for svc, nbytes in svcs.items():
            self.db.add_service_usage("Este computador", svc, hits=0, nbytes=nbytes)
        for (source, svc), n in self.hits.take().items():
            self.db.add_service_usage(source, svc, hits=n)

    # ------------------------------------------------------------ DNS local
    def start_dns(self) -> tuple[bool, str]:
        if self.dns and self.dns.running:
            return True, "DNS local já está ativo"

        def on_query(client_ip: str, name: str):
            m = classify_domain(name)
            if m:
                label = self._label_for_ip(client_ip)
                self.hits.add(label, m.service, name, m.confidence)
                self.dns_updated.emit({"queries": self.dns.queries if self.dns else 0})

        self.dns = DnsForwarder(self.s.dns_proxy_port, self.s.dns_upstream, on_query=on_query)
        ok = self.dns.start()
        msg = "DNS local ativo" if ok else (self.dns.error or "falha")
        self._emit_event("sistema", msg, "info" if ok else "alerta")
        return ok, msg

    def stop_dns(self) -> None:
        if self.dns:
            self.dns.stop()
            self._emit_event("sistema", "DNS local desativado")

    def _label_for_ip(self, ip: str) -> str:
        for d in self.scanner.known.values():
            if d.get("ip") == ip:
                row = self.db.query("SELECT custom_name FROM devices WHERE mac=?", (d["mac"],))
                name = (row[0]["custom_name"] if row else None) or d.get("hostname") or d.get("vendor")
                return f"{name} ({ip})" if name else ip
        return ip

    # ------------------------------------------------------------ velocidade
    def start_speedtest(self) -> bool:
        if self.speedtest_running:
            return False
        self.speedtest_running = True
        threading.Thread(target=self._run_speedtest, name="speedtest", daemon=True).start()
        return True

    def _run_speedtest(self) -> None:
        try:
            res = run_speedtest(self.s.speedtest_base_url, self.s.speedtest_duration_s, self.s.speedtest_streams,
                                ping_host=(self.s.ping_targets or ["1.1.1.1"])[0],
                                progress=lambda ph, v, f: self.speedtest_progress.emit(ph, float(v), float(f)))
            self.db.add_speedtest(res)
            if res["ok"]:
                msg = (f"Teste de velocidade: ↓ {res['down_mbps']:.1f} Mbps · ↑ {res['up_mbps']:.1f} Mbps · "
                       f"ping {res['ping_ms'] or 0:.0f} ms").replace(".", ",")
                self._emit_event("velocidade", msg)
            else:
                self._emit_event("velocidade", f"Teste de velocidade falhou: {res['error']}", "alerta")
            self.speedtest_done.emit(res)
        finally:
            self.speedtest_running = False

    def _loop_speed_scheduler(self) -> None:
        last = self.db.speedtests(1)
        last_ts = last[0]["ts"] if last else 0
        while self._wait(30):
            if not self.s.speedtest_auto:
                continue
            if time.time() - last_ts >= self.s.speedtest_interval_min * 60 and not self.speedtest_running:
                last_ts = time.time()
                self.start_speedtest()

    # ------------------------------------------------------------ agregação por minuto
    def _loop_minute(self) -> None:
        last_purge = 0.0
        while not self._stop.wait(5):
            self._flush_minute()
            if time.time() - last_purge > 6 * 3600:
                self.db.purge(self.s.data_retention_days)
                last_purge = time.time()

    def _flush_minute(self, force: bool = False) -> None:
        now_min = MinuteAggregator._minute()
        with self._agg_lock:
            a = self._agg
            if not force and a.ts == now_min:
                return
            values = {"pc_rx": a.pc_rx, "pc_tx": a.pc_tx, "net_rx": int(a.net_rx), "net_tx": int(a.net_tx)}
            if a.dish_ping:
                values["dish_ping"] = sum(a.dish_ping) / len(a.dish_ping)
            if a.dish_drop:
                values["dish_drop"] = sum(a.dish_drop) / len(a.dish_drop)
            values["dish_state"] = a.dish_state
            ts = a.ts
            a.reset(now_min)
        if self.trackers:
            p = next(iter(self.trackers.values())).stats()
            values.update(ping_avg=p.avg_ms, ping_min=p.min_ms, ping_max=p.max_ms, jitter=p.jitter_ms,
                          loss_pct=p.loss_pct if p.samples else None)
        values["devices"] = self.devices_online
        if any(v for k, v in values.items() if k in ("pc_rx", "pc_tx", "net_rx", "net_tx", "ping_avg")) or values.get("dish_state"):
            self.db.upsert_minute(ts, **values)

    # ------------------------------------------------------------ utilidades UI
    def today_usage(self) -> dict:
        u = self.db.usage_today()
        with self._agg_lock:
            u["pc_rx"] += self._agg.pc_rx
            u["pc_tx"] += self._agg.pc_tx
            u["net_rx"] += int(self._agg.net_rx)
            u["net_tx"] += int(self._agg.net_tx)
        return u

    def today_str(self) -> str:
        return day_str()

    def now_str(self) -> str:
        return datetime.now().strftime("%H:%M:%S")
