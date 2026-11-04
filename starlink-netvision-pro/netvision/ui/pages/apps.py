from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from netvision.services.classifier import classify_domain
from netvision.ui.widgets import Card, DataTable, fmt_bytes, fmt_rate, hint, section


class AppsPage(QWidget):
    title = "Aplicativos"

    def __init__(self, engine):
        super().__init__()
        self.e = engine
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)
        self.mode = hint("Iniciando…", "notice")
        root.addWidget(self.mode)

        card = Card()
        card.body.addWidget(section("Programas usando a internet neste computador"))
        self.t_apps = DataTable(["Aplicativo", "↓ agora", "↑ agora", "Total ↓", "Total ↑", "Conexões", "Destinos (estimado)"],
                                stretch_col=6)
        card.body.addWidget(self.t_apps)
        root.addWidget(card, 3)

        row = QHBoxLayout()
        svc = Card()
        svc.body.addWidget(section("Serviços acessados por este PC (estimado por DNS/SNI)"))
        self.t_svc = DataTable(["Serviço", "Categoria", "Confiança", "Volume"], stretch_col=0)
        svc.body.addWidget(self.t_svc)
        row.addWidget(svc, 1)
        root.addLayout(row, 2)
        self.status = QLabel("")
        self.status.setObjectName("hint")
        root.addWidget(self.status)
        engine.apps_updated.connect(self.on_apps)

    def on_apps(self, d: dict):
        if not self.isVisible():
            return
        full = d["mode"] == "completo"
        if full:
            self.mode.setText(f"<b>Modo completo</b> · captura de cabeçalhos via Npcap na interface "
                              f"<code>{d['interface']}</code>. Bytes por aplicativo são medidos pacote a pacote; "
                              "o nome do serviço vem de DNS/SNI (estimativa). Conteúdo HTTPS não é lido nem decifrado.")
        elif d["mode"] == "básico":
            self.mode.setText(f"<b>Modo básico</b> · {d.get('error') or ''} "
                              "Baixe o Npcap em <a href='https://npcap.com/#download'>npcap.com</a> e reinicie o programa.")
        else:
            self.mode.setText("Monitoramento pausado.")
        rows = []
        for a in d["apps"][:60]:
            dests = ", ".join(f"{s} ({fmt_bytes(b)})" if full else s for s, b in a["services"][:4])
            rows.append([a["app"], fmt_rate(a["rx_bps"]) if full else "-", fmt_rate(a["tx_bps"]) if full else "-",
                         fmt_bytes(a["rx_total"]) if full else "-", fmt_bytes(a["tx_total"]) if full else "-",
                         a["connections"] or "-", dests])
        self.t_apps.fill(rows)
        srows = []
        for name, b in d["services"][:40]:
            m = classify_domain(name) if "." in name else None
            known = m is not None or name in {r[1] for r in _known_services()}
            cat = m.category if m else ("-" if not known else _category(name))
            conf = m.confidence if m else ("-" if not known else _confidence(name))
            srows.append([name, cat, conf, fmt_bytes(b)])
        self.t_svc.fill(srows)
        self.status.setText(f"Pacotes analisados: {d['packets']:,}".replace(",", "."))


def _known_services():
    from netvision.services.classifier import DOMAIN_RULES
    return DOMAIN_RULES


def _category(service: str) -> str:
    return next((r[2] for r in _known_services() if r[1] == service), "-")


def _confidence(service: str) -> str:
    return next((r[3] for r in _known_services() if r[1] == service), "-")
