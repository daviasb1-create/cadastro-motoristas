from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QComboBox, QVBoxLayout, QWidget

from netvision.ui import theme
from netvision.ui.widgets import Card, DataTable, hbox

KINDS = {"Todos": None, "Novos dispositivos": "novo_dispositivo", "Dispositivos": "dispositivo",
         "Starlink": "starlink", "Qualidade": "qualidade", "Velocidade": "velocidade", "Sistema": "sistema"}


class EventsPage(QWidget):
    title = "Alertas"

    def __init__(self, engine):
        super().__init__()
        self.e = engine
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        self.filter = QComboBox()
        self.filter.addItems(list(KINDS))
        self.filter.currentIndexChanged.connect(self.reload)
        root.addLayout(hbox(self.filter, 1))
        card = Card()
        self.table = DataTable(["Data/hora", "Nível", "Tipo", "Mensagem"], stretch_col=3)
        card.body.addWidget(self.table)
        root.addWidget(card, 1)
        engine.event_added.connect(lambda _e: self.reload())
        self.reload()

    def reload(self):
        kind = KINDS[self.filter.currentText()]
        evs = [e for e in self.e.db.events(1000) if kind is None or e["kind"] == kind]
        rows, colors = [], {}
        for i, ev in enumerate(evs):
            rows.append([datetime.fromtimestamp(ev["ts"]).strftime("%d/%m/%Y %H:%M:%S"), ev["level"], ev["kind"], ev["message"]])
            if ev["level"] == "alerta":
                colors[(i, 1)] = theme.WARN
                colors[(i, 3)] = theme.WARN
        self.table.fill(rows, colors)
