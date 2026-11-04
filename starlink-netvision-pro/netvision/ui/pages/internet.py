from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from netvision.ui import theme
from netvision.ui.widgets import (Card, DataTable, KpiCard, TimeChart, fmt_ms, fmt_pct, fmt_rate, hint,
                                  quality_color, section)


class InternetPage(QWidget):
    title = "Internet"

    def __init__(self, engine):
        super().__init__()
        self.e = engine
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        st = Card()
        st.body.addWidget(section("Teste de velocidade"))
        self.k_down = KpiCard("Download", "-", "", theme.OK)
        self.k_up = KpiCard("Upload", "-", "", theme.ACCENT_2)
        self.k_lat = KpiCard("Ping no teste", "-", "", theme.WARN)
        self.btn = QPushButton("Iniciar teste")
        self.btn.setObjectName("primary")
        self.btn.clicked.connect(self.start_test)
        self.prog = QProgressBar()
        self.prog.setRange(0, 100)
        self.prog.setValue(0)
        self.phase = QLabel("")
        self.phase.setObjectName("hint")
        row = QHBoxLayout()
        row.setSpacing(12)
        for k in (self.k_down, self.k_up, self.k_lat):
            row.addWidget(k)
        side = QVBoxLayout()
        side.addWidget(self.btn)
        side.addWidget(self.prog)
        side.addWidget(self.phase)
        row.addLayout(side)
        st.body.addLayout(row)
        st.body.addWidget(hint("Mede a capacidade real com 4 conexões HTTP simultâneas (servidores da Cloudflare, "
                               "configurável). O teste consome dados: de 50 a 300 MB dependendo da velocidade."))
        root.addWidget(st)

        kp = QHBoxLayout()
        kp.setSpacing(12)
        self.k_targets: dict[str, KpiCard] = {}
        for t in list(engine.trackers) + ["192.168.100.1"]:
            label = "Antena (LAN)" if t == "192.168.100.1" else f"Ping {t}"
            k = KpiCard(label, "-", "")
            self.k_targets[t] = k
            kp.addWidget(k)
        root.addLayout(kp)

        charts = QHBoxLayout()
        self.c_lat = TimeChart("Ping em tempo real (ms)",
                               [(t, c) for t, c in zip(engine.trackers, [theme.WARN, theme.ACCENT_2, theme.OK])],
                               lambda v: fmt_ms(v), 300, fill=False)
        self.c_pc = TimeChart("Consumo deste computador", [("↓", theme.OK), ("↑", theme.ACCENT_2)], fmt_rate, 300)
        charts.addWidget(self.c_lat, 1)
        charts.addWidget(self.c_pc, 1)
        root.addLayout(charts, 1)

        hist = Card()
        hist.body.addWidget(section("Últimos testes"))
        self.t_hist = DataTable(["Data", "Download", "Upload", "Ping", "Jitter", "Servidor", "Resultado"], stretch_col=6)
        hist.body.addWidget(self.t_hist)
        root.addWidget(hist, 1)

        engine.latency_updated.connect(self.on_latency)
        engine.traffic_updated.connect(self.on_traffic)
        engine.speedtest_progress.connect(self.on_progress)
        engine.speedtest_done.connect(self.on_done)
        self.load_history()
        QTimer(self, interval=1000, timeout=self.tick).start()

    def tick(self):
        if self.isVisible():
            self.c_lat.refresh()
            self.c_pc.refresh()

    def start_test(self):
        if self.e.start_speedtest():
            self.btn.setEnabled(False)
            self.phase.setText("Medindo ping…")
            self.prog.setValue(0)

    def on_progress(self, phase: str, value: float, frac: float):
        self.btn.setEnabled(False)
        if phase == "download":
            self.k_down.set(f"{value:.1f} Mbps".replace(".", ","))
            self.prog.setValue(int(frac * 50))
            self.phase.setText("Testando download…")
        elif phase == "upload":
            self.k_up.set(f"{value:.1f} Mbps".replace(".", ","))
            self.prog.setValue(50 + int(frac * 50))
            self.phase.setText("Testando upload…")
        else:
            self.k_lat.set(fmt_ms(value))

    def on_done(self, r: dict):
        self.btn.setEnabled(True)
        self.prog.setValue(100 if r["ok"] else 0)
        if r["ok"]:
            self.k_down.set(f"{r['down_mbps']:.1f} Mbps".replace(".", ","), datetime.now().strftime("%d/%m %H:%M"))
            self.k_up.set(f"{r['up_mbps']:.1f} Mbps".replace(".", ","))
            self.k_lat.set(fmt_ms(r["ping_ms"]), f"jitter {fmt_ms(r['jitter_ms'], 1)}")
            self.phase.setText("Concluído")
        else:
            self.phase.setText(f"Falhou: {r['error']}")
        self.load_history()

    def load_history(self):
        rows, colors = [], {}
        for i, r in enumerate(self.e.db.speedtests(50)):
            rows.append([datetime.fromtimestamp(r["ts"]).strftime("%d/%m/%Y %H:%M"),
                         f"{r['down_mbps']:.1f} Mbps".replace(".", ",") if r["down_mbps"] else "-",
                         f"{r['up_mbps']:.1f} Mbps".replace(".", ",") if r["up_mbps"] else "-",
                         fmt_ms(r["ping_ms"]), fmt_ms(r["jitter_ms"], 1), r["server"],
                         "OK" if r["ok"] else (r["error"] or "falha")])
            if not r["ok"]:
                colors[(i, 6)] = theme.BAD
        self.t_hist.fill(rows, colors)
        last_ok = next((r for r in self.e.db.speedtests(20) if r["ok"]), None)
        if last_ok and self.k_down.value.text() == "-":
            self.k_down.set(f"{last_ok['down_mbps']:.1f} Mbps".replace(".", ","),
                            "último: " + datetime.fromtimestamp(last_ok["ts"]).strftime("%d/%m %H:%M"))
            self.k_up.set(f"{last_ok['up_mbps']:.1f} Mbps".replace(".", ","))
            self.k_lat.set(fmt_ms(last_ok["ping_ms"]))

    def on_latency(self, d: dict):
        for t, s in d["targets"].items():
            self.c_lat.add(t, s["last_ms"], d["ts"])
            self._set_target(t, s)
        self._set_target("192.168.100.1", d["dish"])

    def _set_target(self, t: str, s: dict):
        k = self.k_targets.get(t)
        if not k:
            return
        k.set(fmt_ms(s["avg_ms"], 1), f"jitter {fmt_ms(s['jitter_ms'], 1)} · perda {fmt_pct(s['loss_pct'])} · "
                                      f"mín {fmt_ms(s['min_ms'])} / máx {fmt_ms(s['max_ms'])}",
              quality_color(s["avg_ms"], s["loss_pct"]))

    def on_traffic(self, d: dict):
        self.c_pc.add("↓", d["rx_bps"], d["ts"])
        self.c_pc.add("↑", d["tx_bps"], d["ts"])
