from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from netvision.ui import theme
from netvision.ui.widgets import (Card, DataTable, KpiCard, TimeChart, fmt_bytes, fmt_ms, fmt_pct, fmt_rate,
                                  quality_color, section)


class DashboardPage(QWidget):
    title = "Painel"

    def __init__(self, engine):
        super().__init__()
        self.e = engine
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(14)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.k_starlink = KpiCard("Starlink", "…", "aguardando antena", theme.ACCENT)
        self.k_devices = KpiCard("Dispositivos", "-", "conectados à rede", theme.ACCENT_2)
        self.k_down = KpiCard("Download agora", "-", "", theme.OK)
        self.k_up = KpiCard("Upload agora", "-", "", theme.ACCENT_2)
        self.k_ping = KpiCard("Ping internet", "-", "", theme.WARN)
        self.k_stab = KpiCard("Estabilidade", "-", "perda e jitter (60 s)", theme.OK)
        self.k_today = KpiCard("Consumo hoje", "-", "", theme.ACCENT)
        for i, k in enumerate([self.k_starlink, self.k_devices, self.k_down, self.k_up,
                               self.k_ping, self.k_stab, self.k_today]):
            grid.addWidget(k, 0, i)
        root.addLayout(grid)

        charts = QHBoxLayout()
        charts.setSpacing(12)
        self.c_tp = TimeChart("Tráfego em tempo real", [("Rede ↓ (antena)", theme.ACCENT), ("Rede ↑ (antena)", theme.ACCENT_2),
                                                       ("Este PC ↓", theme.OK)], fmt_rate, 300)
        self.c_lat = TimeChart("Latência", [("Internet", theme.WARN), ("Antena→PoP", theme.ACCENT)],
                               lambda v: fmt_ms(v), 300, fill=False)
        charts.addWidget(self.c_tp, 3)
        charts.addWidget(self.c_lat, 2)
        root.addLayout(charts, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        alerts = Card()
        alerts.body.addWidget(section("Alertas e eventos recentes"))
        self.t_events = DataTable(["Hora", "Tipo", "Mensagem"], stretch_col=2)
        alerts.body.addWidget(self.t_events)
        apps = Card()
        apps.body.addWidget(section("Aplicativos usando a internet (este PC)"))
        self.t_apps = DataTable(["Aplicativo", "↓ agora", "↑ agora", "Total"], stretch_col=0)
        apps.body.addWidget(self.t_apps)
        bottom.addWidget(alerts, 3)
        bottom.addWidget(apps, 2)
        root.addLayout(bottom, 1)

        self._events: list[dict] = list(reversed(engine.db.events(40)))
        self._render_events()
        e = engine
        e.starlink_updated.connect(self.on_starlink)
        e.latency_updated.connect(self.on_latency)
        e.traffic_updated.connect(self.on_traffic)
        e.devices_updated.connect(self.on_devices)
        e.apps_updated.connect(self.on_apps)
        e.event_added.connect(self.on_event)
        self._pc_down = None
        self.timer = QTimer(self, interval=1000, timeout=self.tick)
        self.timer.start()

    def tick(self):
        if not self.isVisible():
            return
        self.c_tp.refresh()
        self.c_lat.refresh()
        u = self.e.today_usage()
        net = u["net_rx"] + u["net_tx"]
        self.k_today.set(fmt_bytes(net) if net else fmt_bytes(u["pc_rx"] + u["pc_tx"]),
                         f"Rede (antena): {fmt_bytes(net)} · Este PC: {fmt_bytes(u['pc_rx'] + u['pc_tx'])}")

    def on_starlink(self, d: dict):
        st = d.get("status", {})
        if d.get("ok"):
            color = theme.OK if d["state"] == "CONNECTED" else theme.WARN
            alerts = d.get("alerts_pt") or []
            self.k_starlink.set(d["state_pt"], (f"⚠ {alerts[0]}" if alerts else
                                                f"PoP {fmt_ms(st.get('pop_ping_latency_ms'))} · "
                                                f"obstrução {fmt_pct((st.get('fraction_obstructed') or 0) * 100)}"), color)
            down, up = st.get("downlink_throughput_bps"), st.get("uplink_throughput_bps")
            self.k_down.set(fmt_rate(down), f"rede toda · este PC {fmt_rate(self._pc_down)}")
            self.k_up.set(fmt_rate(up), "rede toda (medido pela antena)")
            self.c_tp.add("Rede ↓ (antena)", down)
            self.c_tp.add("Rede ↑ (antena)", up)
            self.c_lat.add("Antena→PoP", st.get("pop_ping_latency_ms"))
        else:
            self.k_starlink.set("Sem comunicação", d.get("error") or "", theme.BAD)

    def on_latency(self, d: dict):
        p = d.get("primary") or {}
        self.c_lat.add("Internet", p.get("last_ms"))
        col = quality_color(p.get("avg_ms"), p.get("loss_pct"))
        self.k_ping.set(fmt_ms(p.get("last_ms")), f"média {fmt_ms(p.get('avg_ms'))} · {p.get('target', '')}", col)
        loss, jit = p.get("loss_pct"), p.get("jitter_ms")
        label = "Excelente" if col == theme.OK else ("Instável" if col == theme.WARN else "Ruim")
        if p.get("avg_ms") is None:
            label = "Sem resposta"
        self.k_stab.set(label, f"perda {fmt_pct(loss)} · jitter {fmt_ms(jit, 1)}", col)

    def on_traffic(self, d: dict):
        self._pc_down = d["rx_bps"]
        self.c_tp.add("Este PC ↓", d["rx_bps"], d["ts"])
        if not self.e.last_starlink.get("ok"):
            self.k_down.set(fmt_rate(d["rx_bps"]), "este PC (antena indisponível)")
            self.k_up.set(fmt_rate(d["tx_bps"]), "este PC (antena indisponível)")

    def on_devices(self, d: dict):
        devs = d["devices"]
        online = sum(1 for x in devs if x.get("online"))
        self.k_devices.set(str(online), f"{len(devs)} já vistos · {d['method']}")

    def on_apps(self, d: dict):
        rows = []
        for a in d["apps"][:8]:
            rows.append([a["app"], fmt_rate(a["rx_bps"]), fmt_rate(a["tx_bps"]),
                         fmt_bytes(a["rx_total"] + a["tx_total"]) if d["mode"] == "completo" else f"{a['connections']} conexões"])
        self.t_apps.fill(rows)

    def on_event(self, ev: dict):
        self._events.append(ev)
        self._events = self._events[-40:]
        self._render_events()

    def _render_events(self):
        rows, colors = [], {}
        for i, ev in enumerate(reversed(self._events)):
            rows.append([datetime.fromtimestamp(ev["ts"]).strftime("%d/%m %H:%M:%S"), ev["kind"], ev["message"]])
            if ev.get("level") == "alerta":
                colors[(i, 2)] = theme.WARN
        self.t_events.fill(rows, colors)
