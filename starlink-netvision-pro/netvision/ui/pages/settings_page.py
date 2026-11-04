from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QFormLayout, QLineEdit, QMessageBox, QPushButton,
                               QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from netvision.core import paths, winsys
from netvision.ui import theme
from netvision.ui.widgets import Card, hbox, hint, section


class SettingsPage(QWidget):
    title = "Configurações"

    def __init__(self, engine):
        super().__init__()
        self.e = engine
        s = engine.s
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        inner = QWidget()
        scroll.setWidget(inner)
        root = QVBoxLayout(inner)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        sysc = Card()
        sysc.body.addWidget(section("Sistema"))
        admin = winsys.is_admin()
        npcap = winsys.npcap_installed()
        sysc.body.addWidget(hint(
            f"Privilégios: <b style='color:{theme.OK if admin else theme.MUTED}'>{'Administrador' if admin else 'Usuário comum'}</b>"
            " (o programa funciona sem administrador). "
            f"Npcap: <b style='color:{theme.OK if npcap else theme.WARN}'>{'instalado' if npcap else 'não encontrado'}</b>"
            + ("" if npcap else ": necessário para consumo por aplicativo e ARP ativo. "
                                "<a href='https://npcap.com/#download'>Baixar Npcap</a>.")
            + f"<br>Dados: <code>{paths.data_dir()}</code>"))
        b_admin = QPushButton("Reiniciar como administrador")
        b_admin.setEnabled(not admin and winsys.is_windows())
        b_admin.setToolTip("Só é necessário se o Npcap foi instalado com a opção “restringir a administradores”.")
        b_admin.clicked.connect(self.relaunch_admin)
        sysc.body.addLayout(hbox(1, b_admin))
        root.addWidget(sysc)

        form_card = Card()
        form_card.body.addWidget(section("Monitoramento"))
        f = QFormLayout()
        f.setHorizontalSpacing(24)
        f.setVerticalSpacing(8)
        self.w = {}

        def line(key, label, tip=""):
            w = QLineEdit(", ".join(getattr(s, key)) if isinstance(getattr(s, key), list) else str(getattr(s, key)))
            w.setToolTip(tip)
            self.w[key] = w
            f.addRow(label, w)

        def spin(key, label, lo, hi, dec=False, suffix=""):
            w = QDoubleSpinBox() if dec else QSpinBox()
            w.setRange(lo, hi)
            if dec:
                w.setDecimals(1)
            w.setValue(getattr(s, key))
            w.setSuffix(suffix)
            self.w[key] = w
            f.addRow(label, w)

        def check(key, label):
            w = QCheckBox(label)
            w.setChecked(bool(getattr(s, key)))
            self.w[key] = w
            f.addRow("", w)

        line("dish_target", "Endereço da antena (gRPC)")
        line("router_targets", "Alvos para lista Wi-Fi", "Separados por vírgula; testados em ordem.")
        spin("starlink_interval_s", "Intervalo Starlink", 1, 60, True, " s")
        spin("wifi_clients_interval_s", "Intervalo lista Wi-Fi", 5, 600, True, " s")
        line("ping_targets", "Destinos de ping", "Separados por vírgula. O primeiro é usado no painel e alertas.")
        spin("ping_interval_s", "Intervalo de ping", 0.5, 60, True, " s")
        spin("scan_interval_s", "Intervalo do scanner", 15, 3600, True, " s")
        check("scan_resolve_names", "Resolver nomes (DNS reverso, mDNS, NetBIOS)")
        check("speedtest_auto", "Teste de velocidade automático")
        spin("speedtest_interval_min", "Intervalo do teste automático", 15, 1440, False, " min")
        spin("speedtest_duration_s", "Duração de cada fase", 4, 30, True, " s")
        line("speedtest_base_url", "Servidor do teste")
        check("app_monitor_enabled", "Monitorar aplicativos deste PC")
        line("capture_interface", "Interface de captura", "Vazio = automática (rota padrão).")
        spin("alert_ping_ms", "Alerta de ping acima de", 20, 2000, True, " ms")
        spin("alert_loss_pct", "Alerta de perda acima de", 0.5, 100, True, " %")
        check("notify_new_devices", "Notificar novos dispositivos")
        spin("dns_proxy_port", "Porta do DNS local", 1, 65535)
        line("dns_upstream", "DNS upstream")
        spin("data_retention_days", "Guardar histórico por", 7, 3650, False, " dias")
        check("monitoring_on_start", "Iniciar monitoramento ao abrir")
        check("start_minimized", "Abrir minimizado na bandeja")
        check("start_with_windows", "Iniciar com o Windows (usuário atual, sem administrador)")
        form_card.body.addLayout(f)
        save = QPushButton("Salvar configurações")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        form_card.body.addLayout(hbox(1, save))
        form_card.body.addWidget(hint("Alterações de endereços e intervalos de ping/scanner são aplicadas ao reiniciar o programa."))
        root.addWidget(form_card)
        root.addStretch(1)

    def relaunch_admin(self):
        if winsys.relaunch_as_admin():
            from PySide6.QtWidgets import QApplication
            QApplication.instance().quit()

    def save(self):
        s = self.e.s
        for key, w in self.w.items():
            cur = getattr(s, key)
            if isinstance(w, QCheckBox):
                setattr(s, key, w.isChecked())
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                setattr(s, key, type(cur)(w.value()))
            elif isinstance(cur, list):
                setattr(s, key, [x.strip() for x in w.text().split(",") if x.strip()])
            else:
                setattr(s, key, w.text().strip())
        if winsys.is_windows():
            if not winsys.set_autostart(s.start_with_windows):
                QMessageBox.warning(self, "Inicialização", "Não foi possível alterar a inicialização automática.")
        s.save()
        if s.app_monitor_enabled and self.e.active and self.e.apps.mode == "parado":
            self.e.apps.start()
        elif not s.app_monitor_enabled:
            self.e.apps.stop()
        QMessageBox.information(self, "Configurações", "Configurações salvas.")
