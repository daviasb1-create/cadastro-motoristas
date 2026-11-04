from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from netvision.core import winsys
from netvision.services.scanner import local_network
from netvision.ui import theme
from netvision.ui.widgets import Card, DataTable, hbox, hint, section


class NetworkServicesPage(QWidget):
    title = "Serviços na rede"

    def __init__(self, engine):
        super().__init__()
        self.e = engine
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)
        root.addWidget(hint(
            "<b>Por que isto é opcional:</b> a Starlink Mini não fornece logs de DNS nem espelhamento de tráfego, e o "
            "Wi-Fi cifra o tráfego de cada aparelho separadamente. Por isso este PC não consegue ver o que um celular "
            "acessa. A alternativa real é usar este PC como <b>servidor DNS</b> dos aparelhos que você quer monitorar: "
            "as consultas são repassadas sem alteração ao DNS público e apenas o <i>nome do site</i> é registrado e "
            "classificado (YouTube, TikTok, Instagram, Netflix, jogos…). Isso é <b>estimativa</b>: indica uso, não "
            "volume exato, e não funciona se o aparelho usar DNS privado/criptografado (DoH/DoT).", "notice"))

        ctl = Card()
        ctl.body.addWidget(section("DNS local"))
        self.state = QLabel("")
        self.b_on = QPushButton("Ativar DNS local")
        self.b_on.setObjectName("primary")
        self.b_on.clicked.connect(self.toggle)
        self.b_fw = QPushButton("Liberar no Firewall (pede administrador)")
        self.b_fw.clicked.connect(self.firewall)
        ctl.body.addLayout(hbox(self.state, 1, self.b_fw, self.b_on))
        self.howto = hint("")
        ctl.body.addWidget(self.howto)
        root.addWidget(ctl)

        row = QHBoxLayout()
        rec = Card()
        rec.body.addWidget(section("Acessos recentes por aparelho"))
        self.t_recent = DataTable(["Hora", "Aparelho", "Serviço", "Domínio", "Confiança"], stretch_col=3)
        rec.body.addWidget(self.t_recent)
        agg = Card()
        agg.body.addWidget(section("Resumo de hoje"))
        self.t_agg = DataTable(["Aparelho", "Serviço", "Ocorrências"], stretch_col=0)
        agg.body.addWidget(self.t_agg)
        row.addWidget(rec, 3)
        row.addWidget(agg, 2)
        root.addLayout(row, 1)
        self._recent: list[dict] = []
        engine.apps_updated.connect(lambda d: setattr(self, "_recent", d.get("dns_hits") or []))
        QTimer(self, interval=2000, timeout=self.refresh).start()
        self.refresh()

    def showEvent(self, ev):
        super().showEvent(ev)
        self._recent = list(self.e.hits.recent[:200])
        self.refresh()

    def toggle(self):
        if self.e.dns and self.e.dns.running:
            self.e.stop_dns()
            self.e.s.dns_proxy_enabled = False
        else:
            ok, msg = self.e.start_dns()
            self.e.s.dns_proxy_enabled = ok
            if not ok:
                QMessageBox.warning(self, "DNS local", msg)
        self.e.s.save()
        self.refresh()

    def firewall(self):
        if not winsys.add_firewall_rule_dns(self.e.s.dns_proxy_port):
            QMessageBox.information(self, "Firewall", "A regra não foi criada (UAC negado ou sistema não Windows).")

    def refresh(self):
        running = bool(self.e.dns and self.e.dns.running)
        import time
        if time.time() - getattr(self, "_ip_ts", 0) > 60:
            net = local_network()
            self._ip, self._ip_ts = (net.ip if net else "?"), time.time()
        ip = self._ip
        self.state.setText(f"<span style='color:{theme.OK if running else theme.MUTED}'>● "
                           f"{'Ativo' if running else 'Desativado'}</span> · consultas atendidas: "
                           f"{self.e.dns.queries if self.e.dns else 0}")
        self.b_on.setText("Desativar DNS local" if running else "Ativar DNS local")
        self.howto.setText(
            f"<b>Como usar:</b> 1) Ative aqui e clique em liberar no Firewall. 2) No celular/TV, abra o Wi-Fi da "
            f"Starlink → configurações da rede → DNS <b>manual</b> = <code>{ip}</code> (deixe um DNS público como "
            f"segundo, para o aparelho continuar navegando se o PC desligar). 3) No Android, desative o “DNS privado”. "
            f"Atenção: o IP deste PC pode mudar quando o DHCP do roteador renovar a concessão; se isso ocorrer, "
            f"refaça o passo 2 ou defina um IP fixo no Windows (fora da faixa distribuída pelo roteador).")
        if not self.isVisible():
            return
        rows = []
        for h in self._recent[:150]:
            rows.append([datetime.fromtimestamp(h["ts"]).strftime("%H:%M:%S"), h["source"], h["service"],
                         h["domain"], h["confidence"]])
        self.t_recent.fill(rows)
        agg: dict[tuple[str, str], int] = {}
        for r in self.e.db.service_usage(self.e.today_str()):
            if r["hits"]:
                agg[(r["source"], r["service"])] = r["hits"]
        for k, n in dict(self.e.hits.pending).items():  # ainda não gravados no banco
            agg[k] = agg.get(k, 0) + n
        rows = sorted(([s, svc, n] for (s, svc), n in agg.items()), key=lambda r: -r[2])
        self.t_agg.fill(rows[:100])
