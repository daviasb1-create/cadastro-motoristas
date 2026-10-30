"""Ícone e menu da bandeja do sistema."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import theme


def make_icon(color: str = theme.CYAN, size: int = 64) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    c = QPointF(size / 2, size / 2)
    p.setPen(QPen(QColor(color), size * 0.07))
    p.setBrush(QColor(theme.BG))
    p.drawEllipse(c, size * 0.44, size * 0.44)
    g = QRadialGradient(c, size * 0.26)
    g.setColorAt(0, QColor("#e0fbff"))
    g.setColorAt(0.6, QColor(color))
    g.setColorAt(1, QColor(0, 0, 0, 0))
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawEllipse(c, size * 0.26, size * 0.26)
    p.end()
    return QIcon(pix)


class Tray(QSystemTrayIcon):
    def __init__(self, app) -> None:
        super().__init__(make_icon())
        self.app = app
        self.setToolTip("JARVIS")
        menu = QMenu()
        self.act_show = QAction("Mostrar JARVIS", menu)
        self.act_show.triggered.connect(app.show_window)
        self.act_talk = QAction("Falar agora", menu)
        self.act_talk.triggered.connect(app.push_to_talk)
        self.act_mic = QAction("Microfone ligado", menu, checkable=True)
        self.act_mic.setChecked(True)
        self.act_mic.triggered.connect(lambda checked: app.set_mic(checked))
        self.act_game = QAction("Modo jogo", menu, checkable=True)
        self.act_game.triggered.connect(lambda checked: app.run_action("game_mode", {"active": checked}))
        self.act_mute = QAction("Silenciar notificações", menu, checkable=True)
        self.act_mute.triggered.connect(
            lambda checked: app.run_action("notifications_mute" if checked else "notifications_unmute", {}))
        profile_menu = QMenu("Voz", menu)
        self.act_jarvis = QAction("JARVIS", profile_menu, checkable=True)
        self.act_friday = QAction("FRIDAY", profile_menu, checkable=True)
        self.act_jarvis.triggered.connect(lambda: app.run_action("set_profile", {"profile": "jarvis"}))
        self.act_friday.triggered.connect(lambda: app.run_action("set_profile", {"profile": "friday"}))
        profile_menu.addAction(self.act_jarvis)
        profile_menu.addAction(self.act_friday)
        self.act_music = QAction("Música de fundo", menu, checkable=True)
        self.act_music.triggered.connect(lambda checked: app.run_action("music_play" if checked else "music_stop", {}))
        act_settings = QAction("Configurações", menu)
        act_settings.triggered.connect(app.open_settings)
        act_quit = QAction("Sair", menu)
        act_quit.triggered.connect(app.quit)
        for action in (self.act_show, self.act_talk, self.act_mic, self.act_game, self.act_mute):
            menu.addAction(action)
        menu.addMenu(profile_menu)
        menu.addAction(self.act_music)
        menu.addSeparator()
        menu.addAction(act_settings)
        menu.addAction(act_quit)
        self.setContextMenu(menu)
        self._menu = menu
        self.activated.connect(self._on_activated)
        self.refresh()

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.app.show_window()

    def refresh(self) -> None:
        settings = self.app.services.settings
        state = self.app.services.state
        profile = settings.get("voice.profile", "jarvis")
        self.act_jarvis.setChecked(profile == "jarvis")
        self.act_friday.setChecked(profile == "friday")
        self.act_mic.setChecked(state.mic_enabled)
        self.act_game.setChecked(state.game_mode)
        music = self.app.services.extras.get("music")
        self.act_music.setChecked(bool(music and music.playing))
        muted = settings.get("notifications.muted_until")
        self.act_mute.setChecked(bool(muted))
        color = theme.CYAN if state.mic_enabled else "#475569"
        self.setIcon(make_icon(color))
