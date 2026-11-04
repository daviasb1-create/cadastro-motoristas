from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
                               QMenu, QPushButton, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget)

from netvision import APP_NAME, __version__
from netvision.core import paths
from netvision.ui import theme
from netvision.ui.pages.apps import AppsPage
from netvision.ui.pages.dashboard import DashboardPage
from netvision.ui.pages.devices import DevicesPage
from netvision.ui.pages.events import EventsPage
from netvision.ui.pages.history import HistoryPage
from netvision.ui.pages.internet import InternetPage
from netvision.ui.pages.network_services import NetworkServicesPage
from netvision.ui.pages.settings_page import SettingsPage
from netvision.ui.pages.starlink_page import StarlinkPage
from netvision.ui.widgets import Pill


def app_icon() -> QIcon:
    ico = paths.resource_path("assets/icon.ico")
    if ico.exists():
        return QIcon(str(ico))
    return QIcon(render_icon_pixmap(256))


def render_icon_pixmap(size: int) -> QPixmap:
    """Ícone vetorial: antena parabólica estilizada com ondas."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 64
    p.setBrush(QColor(theme.SURFACE))
    p.setPen(QPen(QColor(theme.ACCENT), 2.5 * s))
    p.drawRoundedRect(QRectF(2 * s, 2 * s, 60 * s, 60 * s), 14 * s, 14 * s)
    path = QPainterPath()
    path.moveTo(14 * s, 26 * s)
    path.quadTo(18 * s, 50 * s, 42 * s, 50 * s)
    path.closeSubpath()
    p.setBrush(QColor(theme.ACCENT))
    p.setPen(Qt.NoPen)
    p.drawPath(path)
    p.setPen(QPen(QColor(theme.ACCENT), 3 * s, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(27 * s, 39 * s), QPointF(38 * s, 28 * s))
    p.setPen(QPen(QColor(theme.ACCENT_2), 3 * s, Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    for r in (8, 15):
        p.drawArc(QRectF((40 - r) * s, (24 - r) * s, 2 * r * s, 2 * r * s), 0 * 16, 90 * 16)
    p.end()
    return pm


class MainWindow(QMainWindow):
    def __init__(self, engine):
        super().__init__()
        self.e = engine
        self._quitting = False
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setWindowIcon(app_icon())
        self.resize(1480, 920)
        self.setMinimumSize(1100, 700)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(232)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(12, 18, 12, 12)
        logo = QLabel()
        logo.setPixmap(render_icon_pixmap(44))
        brand = QLabel("STARLINK\nNETVISION PRO")
        brand.setObjectName("brand")
        b = QHBoxLayout()
        b.addWidget(logo)
        b.addWidget(brand, 1)
        sl.addLayout(b)
        sub = QLabel("CENTRAL DE MONITORAMENTO")
        sub.setObjectName("brandSub")
        sl.addWidget(sub)
        sl.addSpacing(14)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        sl.addWidget(self.nav, 1)
        ver = QLabel(f"v{__version__} · Starlink Mini")
        ver.setObjectName("brandSub")
        sl.addWidget(ver)
        lay.addWidget(side)

        main = QVBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        top = QFrame()
        top.setObjectName("topbar")
        top.setFixedHeight(62)
        tl = QHBoxLayout(top)
        tl.setContentsMargins(20, 8, 20, 8)
        self.page_title = QLabel("Painel")
        self.page_title.setObjectName("pageTitle")
        self.pill_star = Pill("Starlink")
        self.pill_mon = Pill("Monitorando")
        self.btn_speed = QPushButton("Teste de velocidade")
        self.btn_speed.clicked.connect(self.run_speedtest)
        self.btn_toggle = QPushButton("Pausar")
        self.btn_toggle.setObjectName("primary")
        self.btn_toggle.setMinimumWidth(170)
        self.btn_toggle.clicked.connect(self.toggle)
        tl.addWidget(self.page_title)
        tl.addStretch(1)
        for w in (self.pill_star, self.pill_mon, self.btn_speed, self.btn_toggle):
            tl.addWidget(w)
        main.addWidget(top)
        self.stack = QStackedWidget()
        main.addWidget(self.stack, 1)
        lay.addLayout(main, 1)

        pages = [("◉  Painel", DashboardPage), ("🛰  Starlink Mini", StarlinkPage), ("⌂  Dispositivos", DevicesPage),
                 ("↯  Internet", InternetPage), ("▤  Aplicativos", AppsPage), ("◎  Serviços na rede", NetworkServicesPage),
                 ("▦  Histórico", HistoryPage), ("⚠  Alertas", EventsPage), ("⚙  Configurações", SettingsPage)]
        self.pages = []
        for label, cls in pages:
            page = cls(engine)
            self.pages.append(page)
            self.stack.addWidget(page)
            it = QListWidgetItem(label)
            it.setSizeHint(QSize(200, 40))
            self.nav.addItem(it)
        self.nav.currentRowChanged.connect(self.go)
        self.nav.setCurrentRow(0)

        self._setup_tray()
        engine.monitoring_changed.connect(self.on_monitoring)
        engine.starlink_updated.connect(self.on_starlink)
        engine.devices_updated.connect(self.on_devices)
        engine.speedtest_done.connect(lambda _r: self.btn_speed.setEnabled(True))
        self.on_monitoring(engine.active)

    # ------------------------------------------------------------ navegação
    def go(self, idx: int):
        self.stack.setCurrentIndex(idx)
        self.page_title.setText(self.pages[idx].title)

    def toggle(self):
        if self.e.active:
            self.e.pause()
        else:
            self.e.resume()

    def run_speedtest(self):
        if self.e.start_speedtest():
            self.btn_speed.setEnabled(False)
            self.nav.setCurrentRow(3)

    def on_monitoring(self, active: bool):
        self.btn_toggle.setText("⏸  Pausar monitoramento" if active else "▶  Iniciar monitoramento")
        self.pill_mon.set("Monitorando" if active else "Pausado", theme.OK if active else theme.WARN)
        if hasattr(self, "act_toggle"):
            self.act_toggle.setText("Pausar monitoramento" if active else "Iniciar monitoramento")

    def on_starlink(self, d: dict):
        if d.get("ok"):
            self.pill_star.set(f"Starlink: {d['state_pt']}", theme.OK if d["state"] == "CONNECTED" else theme.WARN)
        else:
            self.pill_star.set("Starlink: sem comunicação", theme.BAD)

    def on_devices(self, d: dict):
        if not self.e.s.notify_new_devices or not self.tray:
            return
        for dev in d.get("new") or []:
            name = dev.get("hostname") or dev.get("vendor") or "dispositivo sem nome"
            self.tray.showMessage("Novo dispositivo na rede", f"{name}\n{dev.get('ip')} · {dev.get('mac')}",
                                  QSystemTrayIcon.Warning, 8000)

    # ------------------------------------------------------------ bandeja
    def _setup_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        a_show = QAction("Abrir painel", self, triggered=self.show_normal)
        self.act_toggle = QAction("Pausar monitoramento", self, triggered=self.toggle)
        a_speed = QAction("Teste de velocidade", self, triggered=self.run_speedtest)
        a_quit = QAction("Sair", self, triggered=self.quit)
        for a in (a_show, self.act_toggle, a_speed):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(a_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.show_normal() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def show_normal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit(self):
        self._quitting = True
        self.close()

    def closeEvent(self, ev):
        if self.tray and not self._quitting:
            ev.ignore()
            self.hide()
            self.tray.showMessage(APP_NAME, "Continua monitorando na bandeja. Use “Sair” no menu para encerrar.",
                                  QSystemTrayIcon.Information, 3000)
            return
        self.e.shutdown()
        if self.tray:
            self.tray.hide()
        ev.accept()
        QApplication.instance().quit()
