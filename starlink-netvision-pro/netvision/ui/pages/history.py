from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QMessageBox, QPushButton, QTabWidget, QVBoxLayout, QWidget

from netvision.core import paths
from netvision.services.reports import export_csv, export_html
from netvision.ui import theme
from netvision.ui.widgets import (Card, DataTable, TimeChart, fmt_bytes, fmt_ms, fmt_pct, fmt_rate, hbox, hint)


class HistoryPage(QWidget):
    title = "Histórico e relatórios"

    def __init__(self, engine):
        super().__init__()
        self.e = engine
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)
        self.range = QComboBox()
        self.range.addItems(["Últimas 24 horas", "Últimos 7 dias", "Últimos 30 dias"])
        self.range.currentIndexChanged.connect(self.reload)
        b_reload = QPushButton("Atualizar")
        b_reload.clicked.connect(self.reload)
        b_csv = QPushButton("Exportar CSV")
        b_csv.clicked.connect(self.do_csv)
        b_html = QPushButton("Exportar relatório HTML")
        b_html.setObjectName("primary")
        b_html.clicked.connect(self.do_html)
        b_dir = QPushButton("Abrir pasta")
        b_dir.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.reports_dir()))))
        root.addLayout(hbox(self.range, b_reload, 1, b_dir, b_csv, b_html))

        tabs = QTabWidget()
        root.addWidget(tabs, 1)
        g = QWidget()
        gl = QVBoxLayout(g)
        self.c_usage = TimeChart("Consumo por minuto", [("Rede ↓ (antena)", theme.ACCENT), ("Este PC ↓", theme.OK)],
                                 fmt_rate, 86400, height=200)
        self.c_q = TimeChart("Qualidade por minuto", [("Ping médio", theme.WARN), ("Jitter", theme.ACCENT_2),
                                                      ("Antena→PoP", theme.ACCENT)], fmt_ms, 86400, height=200, fill=False)
        self.c_loss = TimeChart("Perda de pacotes por minuto (%)", [("Perda", theme.BAD)], fmt_pct, 86400, height=140)
        for c in (self.c_usage, self.c_q, self.c_loss):
            gl.addWidget(c)
        tabs.addTab(g, "Gráficos")

        self.t_day = DataTable(["Dia", "Rede ↓", "Rede ↑", "PC ↓", "PC ↑", "Ping médio", "Jitter", "Perda",
                                "Antena→PoP", "Min. monitorados", "Min. sem conexão Starlink"], stretch_col=None)
        tabs.addTab(self._wrap(self.t_day, "“Rede” = estimado pela antena (todos os aparelhos). “PC” = medido nas "
                                           "placas de rede deste computador."), "Diário")
        self.t_month = DataTable(["Mês", "Rede ↓", "Rede ↑", "PC ↓", "PC ↑", "Ping médio", "Jitter", "Perda", "Min. monitorados"],
                                 stretch_col=None)
        tabs.addTab(self._wrap(self.t_month), "Mensal")
        self.t_apps = DataTable(["Aplicativo", "Download", "Upload", "Total"], stretch_col=0)
        tabs.addTab(self._wrap(self.t_apps), "Aplicativos (período)")
        self.tabs = tabs
        self.reload()

    @staticmethod
    def _wrap(widget, note: str | None = None) -> QWidget:
        c = Card()
        if note:
            c.body.addWidget(hint(note))
        c.body.addWidget(widget)
        return c

    def showEvent(self, ev):
        super().showEvent(ev)
        self.reload()

    def reload(self):
        days = [1, 7, 30][self.range.currentIndex()]
        since = int(time.time()) - days * 86400
        mins = self.e.db.minutes(since)
        win = days * 86400
        for c in (self.c_usage, self.c_q, self.c_loss):
            c.window_s = win
        self.c_usage.set_series("Rede ↓ (antena)", [(m["ts"], (m["net_rx"] or 0) * 8 / 60) for m in mins])
        self.c_usage.set_series("Este PC ↓", [(m["ts"], (m["pc_rx"] or 0) * 8 / 60) for m in mins])
        self.c_q.set_series("Ping médio", [(m["ts"], m["ping_avg"]) for m in mins])
        self.c_q.set_series("Jitter", [(m["ts"], m["jitter"]) for m in mins])
        self.c_q.set_series("Antena→PoP", [(m["ts"], m["dish_ping"]) for m in mins])
        self.c_loss.set_series("Perda", [(m["ts"], m["loss_pct"]) for m in mins])
        for c in (self.c_usage, self.c_q, self.c_loss):
            c.refresh(live=False)
            c.plot.setXRange(since, time.time(), padding=0)

        self.t_day.fill([[r["dia"], fmt_bytes(r["net_rx"]), fmt_bytes(r["net_tx"]), fmt_bytes(r["pc_rx"]),
                          fmt_bytes(r["pc_tx"]), fmt_ms(r["ping_avg"], 1), fmt_ms(r["jitter"], 1), fmt_pct(r["loss_pct"], 2),
                          fmt_ms(r["dish_ping"], 1), r["minutos"], r["minutos_fora"]] for r in self.e.db.daily_summary(62)])
        self.t_month.fill([[r["mes"], fmt_bytes(r["net_rx"]), fmt_bytes(r["net_tx"]), fmt_bytes(r["pc_rx"]),
                            fmt_bytes(r["pc_tx"]), fmt_ms(r["ping_avg"], 1), fmt_ms(r["jitter"], 1),
                            fmt_pct(r["loss_pct"], 2), r["minutos"]] for r in self.e.db.monthly_summary()])
        since_day = datetime.fromtimestamp(since).strftime("%Y-%m-%d")
        self.t_apps.fill([[r["app"], fmt_bytes(r["rx"]), fmt_bytes(r["tx"]), fmt_bytes(r["rx"] + r["tx"])]
                          for r in self.e.db.app_usage(since_day)])

    def do_csv(self):
        files = export_csv(self.e.db, paths.reports_dir(), days=[1, 7, 30][self.range.currentIndex()] or 31)
        QMessageBox.information(self, "Exportação concluída", f"{len(files)} arquivos CSV salvos em:\n{files[0].parent}")

    def do_html(self):
        p = export_html(self.e.db, paths.reports_dir())
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
