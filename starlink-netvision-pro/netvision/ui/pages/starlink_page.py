from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget

from netvision.ui import theme
from netvision.ui.widgets import Card, KpiCard, fmt_duration, fmt_ms, fmt_pct, fmt_rate, hint, section


class StarlinkPage(QWidget):
    title = "Starlink Mini"

    def __init__(self, engine):
        super().__init__()
        self.e = engine
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        inner = QWidget()
        scroll.setWidget(inner)
        root = QVBoxLayout(inner)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(14)

        root.addWidget(hint(
            "Dados lidos da <b>API gRPC local</b> da Starlink (<code>192.168.100.1:9200</code>), a mesma usada pelo app "
            "oficial. A SpaceX não publica documentação oficial dessa API; as definições são obtidas por reflection do "
            "próprio equipamento, sem campos inventados. Campos ausentes no seu firmware aparecem como “-”.", "notice"))

        row = QHBoxLayout()
        row.setSpacing(12)
        self.k_state = KpiCard("Estado", "…")
        self.k_pop = KpiCard("Ping até o PoP", "-", "latência antena → gateway Starlink", theme.WARN)
        self.k_drop = KpiCard("Perda (PoP)", "-", "taxa de queda de ping da antena", theme.BAD)
        self.k_obs = KpiCard("Obstrução", "-", "fração do céu obstruída", theme.ACCENT_2)
        self.k_up = KpiCard("Ligada há", "-", "", theme.OK)
        for k in (self.k_state, self.k_pop, self.k_drop, self.k_obs, self.k_up):
            row.addWidget(k)
        root.addLayout(row)

        info = Card()
        info.body.addWidget(section("Antena / terminal"))
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(30)
        self.grid.setVerticalSpacing(6)
        self.fields: dict[str, QLabel] = {}
        labels = [
            ("id", "ID do terminal"), ("hardware_version", "Hardware"), ("software_version", "Firmware"),
            ("country_code", "País"), ("downlink_throughput_bps", "Download atual (rede)"),
            ("uplink_throughput_bps", "Upload atual (rede)"), ("direction_azimuth", "Azimute"),
            ("direction_elevation", "Elevação"), ("gps", "GPS"), ("is_snr_above_noise_floor", "Sinal acima do ruído"),
            ("currently_obstructed", "Obstruída agora"), ("mobility_class", "Classe de mobilidade"),
            ("class_of_service", "Classe de serviço"), ("alerts", "Alertas ativos"),
        ]
        for i, (key, label) in enumerate(labels):
            lb = QLabel(label)
            lb.setObjectName("hint")
            val = QLabel("-")
            val.setWordWrap(True)
            self.fields[key] = val
            r, c = divmod(i, 2)
            self.grid.addWidget(lb, r, c * 2)
            self.grid.addWidget(val, r, c * 2 + 1)
        info.body.addLayout(self.grid)
        root.addWidget(info)

        hist = Card()
        hist.body.addWidget(section("Últimos 15 minutos (calculado pela própria antena)"))
        self.hist_label = QLabel("Aguardando histórico…")
        self.hist_label.setWordWrap(True)
        hist.body.addWidget(self.hist_label)
        root.addWidget(hist)

        router = Card()
        router.body.addWidget(section("Roteador integrado (lista de clientes Wi-Fi)"))
        self.router_label = QLabel("Sondando…")
        self.router_label.setWordWrap(True)
        router.body.addWidget(self.router_label)
        router.body.addWidget(hint(
            "A Starlink Mini integra antena e roteador Wi-Fi. A lista de clientes é solicitada pelo método "
            "<code>wifi_get_clients</code>. O programa testa os endereços configurados (Configurações) e memoriza o "
            "que responder. Se o firmware não liberar o método, a lista de dispositivos vem do scanner ARP/ICMP."))
        self.router_log = QPlainTextEdit()
        self.router_log.setReadOnly(True)
        self.router_log.setMaximumHeight(120)
        router.body.addWidget(self.router_log)
        root.addWidget(router)
        root.addStretch(1)

        engine.starlink_updated.connect(self.on_starlink)
        engine.wifi_clients_updated.connect(self.on_wifi)

    def on_starlink(self, d: dict):
        st, ex = d.get("status", {}), d.get("extra", {})
        if not d.get("ok"):
            self.k_state.set("Sem comunicação", d.get("error") or "", theme.BAD)
            return
        self.k_state.set(d["state_pt"], d["state"], theme.OK if d["state"] == "CONNECTED" else theme.WARN)
        self.k_pop.set(fmt_ms(st.get("pop_ping_latency_ms"), 1))
        drop = st.get("pop_ping_drop_rate")
        self.k_drop.set(fmt_pct(drop * 100 if drop is not None else None, 2))
        obs = st.get("fraction_obstructed")
        self.k_obs.set(fmt_pct(obs * 100 if obs is not None else None, 2))
        self.k_up.set(fmt_duration(st.get("uptime")))

        def yn(v):
            return "-" if v is None else ("Sim" if v else "Não")

        vals = {
            "id": st.get("id"), "hardware_version": st.get("hardware_version"),
            "software_version": st.get("software_version"), "country_code": ex.get("country_code"),
            "downlink_throughput_bps": fmt_rate(st.get("downlink_throughput_bps")),
            "uplink_throughput_bps": fmt_rate(st.get("uplink_throughput_bps")),
            "direction_azimuth": f"{st['direction_azimuth']:.1f}°" if st.get("direction_azimuth") is not None else None,
            "direction_elevation": f"{st['direction_elevation']:.1f}°" if st.get("direction_elevation") is not None else None,
            "gps": (f"{'válido' if st.get('gps_ready') else 'sem fix'} · {st.get('gps_sats')} satélites"
                    if st.get("gps_ready") is not None else None),
            "is_snr_above_noise_floor": yn(st.get("is_snr_above_noise_floor")),
            "currently_obstructed": yn(st.get("currently_obstructed")),
            "mobility_class": ex.get("mobility_class"), "class_of_service": ex.get("class_of_service"),
            "alerts": ", ".join(d.get("alerts_pt") or []) or "Nenhum",
        }
        for k, v in vals.items():
            self.fields[k].setText("-" if v in (None, "") else str(v))
        h = d.get("history") or {}
        if h and "error" not in h:
            self.hist_label.setText(
                f"Amostras: {h.get('samples', '-')} s  ·  Ping médio: {fmt_ms(h.get('mean_full_ping_latency'), 1)}  ·  "
                f"Perda total: {fmt_pct((h.get('total_ping_drop') or 0) / max(h.get('samples') or 1, 1) * 100, 2)}  ·  "
                f"Perda por obstrução: {h.get('total_obstructed_ping_drop', 0):.0f} s  ·  "
                f"Download: {fmt_rate((h.get('download_usage') or 0) * 8 / max(h.get('samples') or 1, 1))} médio  ·  "
                f"Upload: {fmt_rate((h.get('upload_usage') or 0) * 8 / max(h.get('samples') or 1, 1))} médio")
        elif h.get("error"):
            self.hist_label.setText(f"Histórico indisponível: {h['error']}")

    def on_wifi(self, d: dict):
        if d["ok"]:
            self.router_label.setText(f"<span style='color:{theme.OK}'>● Respondendo em {d['target']}</span> · "
                                      f"{len(d['clients'])} clientes informados pelo roteador")
        else:
            self.router_label.setText(f"<span style='color:{theme.WARN}'>● Lista de clientes indisponível</span> · "
                                      "usando scanner da rede local como alternativa")
        self.router_log.setPlainText("\n".join(d.get("log") or []))
