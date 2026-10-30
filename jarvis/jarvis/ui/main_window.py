"""Janela principal do JARVIS."""
from __future__ import annotations

import html
from datetime import datetime

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QPushButton,
    QSizePolicy, QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from . import theme
from .core_widget import ReactorWidget
from .tray import make_icon

SERVICES = [("microphone", "MICROFONE"), ("outlook", "OUTLOOK"), ("excel", "EXCEL"),
            ("whatsapp", "WHATSAPP"), ("spotify", "SPOTIFY"), ("ai", "IA"), ("game", "MODO JOGO")]


def panel() -> QFrame:
    frame = QFrame()
    frame.setObjectName("panel")
    return frame


class StatusChip(QLabel):
    def __init__(self, label: str) -> None:
        super().__init__()
        self.label = label
        self.set_status("off", "")

    def set_status(self, status: str, detail: str) -> None:
        color = theme.STATUS_COLORS.get(status, "#475569")
        self.setText(f"<span style='color:{color}; font-size:14px'>●</span> "
                     f"<span style='font-size:10px; letter-spacing:2px'>{self.label}</span>")
        self.setToolTip(detail or status)


class MainWindow(QMainWindow):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self.services = app.services
        self.setWindowTitle("JARVIS")
        self.setWindowIcon(make_icon())
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(1180, 720)
        self.setMinimumSize(900, 580)
        self._drag: QPoint | None = None
        self._build()
        self.apply_profile()

    # ------------------------------------------------------------ layout
    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 10, 16, 16)
        outer.setSpacing(12)

        # barra superior
        top = QHBoxLayout()
        title_box = QVBoxLayout()
        self.title = QLabel("J.A.R.V.I.S.")
        self.title.setObjectName("title")
        self.subtitle = QLabel("ASSISTENTE PESSOAL")
        self.subtitle.setObjectName("subtitle")
        title_box.addWidget(self.title)
        title_box.addWidget(self.subtitle)
        top.addLayout(title_box)
        top.addStretch(1)
        self.chips: dict[str, StatusChip] = {}
        for key, label in SERVICES:
            chip = StatusChip(label)
            self.chips[key] = chip
            top.addWidget(chip)
            top.addSpacing(8)
        top.addSpacing(10)
        for text, tip, slot in (("⚙", "Configurações", self.app.open_settings), ("−", "Minimizar para a bandeja", self.hide),
                                ("✕", "Fechar (continua na bandeja)", self.close)):
            btn = QPushButton(text)
            btn.setObjectName("flat")
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            top.addWidget(btn)
        outer.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(12)
        outer.addLayout(body, 1)

        # coluna esquerda: núcleo e controles
        left = panel()
        left.setFixedWidth(340)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(16, 16, 16, 16)
        self.reactor = ReactorWidget()
        self.reactor.animations_enabled = self.services.settings.get("general.ui_animations", True)
        lv.addWidget(self.reactor, 1)
        self.state_label = QLabel(theme.STATE_LABELS["idle"])
        self.state_label.setObjectName("state")
        self.state_label.setAlignment(Qt.AlignCenter)
        lv.addWidget(self.state_label)
        self.heard = QLabel("")
        self.heard.setObjectName("heard")
        self.heard.setAlignment(Qt.AlignCenter)
        self.heard.setWordWrap(True)
        lv.addWidget(self.heard)
        buttons = QHBoxLayout()
        self.btn_talk = QPushButton("🎙  Falar")
        self.btn_talk.setObjectName("accent")
        self.btn_talk.setToolTip("Ativa a escuta sem dizer a palavra de ativação")
        self.btn_talk.clicked.connect(self.app.push_to_talk)
        self.btn_mic = QPushButton("Microfone")
        self.btn_mic.setCheckable(True)
        self.btn_mic.setChecked(True)
        self.btn_mic.clicked.connect(lambda checked: self.app.set_mic(checked))
        self.btn_stop = QPushButton("■ Parar")
        self.btn_stop.setToolTip("Interrompe a fala")
        self.btn_stop.clicked.connect(self.app.stop_speech)
        for b in (self.btn_talk, self.btn_mic, self.btn_stop):
            buttons.addWidget(b)
        lv.addLayout(buttons)

        # painel de confirmação
        self.confirm_box = panel()
        cv = QVBoxLayout(self.confirm_box)
        self.confirm_text = QLabel("")
        self.confirm_text.setWordWrap(True)
        self.confirm_details = QLabel("")
        self.confirm_details.setWordWrap(True)
        self.confirm_details.setObjectName("heard")
        self.confirm_details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        cb = QHBoxLayout()
        yes = QPushButton("Confirmar")
        yes.setObjectName("accent")
        yes.clicked.connect(lambda: self.app.confirm(True))
        no = QPushButton("Cancelar")
        no.setObjectName("danger")
        no.clicked.connect(lambda: self.app.confirm(False))
        cb.addWidget(yes)
        cb.addWidget(no)
        cv.addWidget(self.confirm_text)
        cv.addWidget(self.confirm_details)
        cv.addLayout(cb)
        self.confirm_box.hide()
        lv.addWidget(self.confirm_box)
        body.addWidget(left)

        # centro: conversa
        center = panel()
        cvl = QVBoxLayout(center)
        cvl.setContentsMargins(14, 12, 14, 12)
        sec = QLabel("CONVERSA")
        sec.setObjectName("section")
        cvl.addWidget(sec)
        self.chat = QTextBrowser()
        self.chat.setOpenExternalLinks(False)
        cvl.addWidget(self.chat, 1)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Digite um comando (ex.: tenho e-mails novos?) e pressione Enter")
        self.input.returnPressed.connect(self._send_text)
        send = QPushButton("Enviar")
        send.setObjectName("accent")
        send.clicked.connect(self._send_text)
        row.addWidget(self.input, 1)
        row.addWidget(send)
        cvl.addLayout(row)
        body.addWidget(center, 1)

        # direita: notificações e atividades
        right = panel()
        right.setFixedWidth(330)
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 8, 8, 8)
        tabs = QTabWidget()
        self.notes = QListWidget()
        self.notes.setWordWrap(True)
        self.notes.itemDoubleClicked.connect(self._open_notification)
        self.activity = QListWidget()
        self.activity.setWordWrap(True)
        tabs.addTab(self.notes, "NOTIFICAÇÕES")
        tabs.addTab(self.activity, "ATIVIDADES")
        rv.addWidget(tabs)
        summary = QPushButton("Resumo do que chegou")
        summary.clicked.connect(lambda: self.app.submit_text("o que aconteceu enquanto eu estava ocupado"))
        rv.addWidget(summary)
        body.addWidget(right)
        for w in (left, center, right):
            w.setSizePolicy(w.sizePolicy().horizontalPolicy(), QSizePolicy.Expanding)

    # ------------------------------------------------------------ eventos
    def handle_event(self, topic: str, payload: dict) -> None:
        if topic == "state":
            state = payload.get("state", "idle")
            self.reactor.set_state(state)
            self.state_label.setText(theme.STATE_LABELS.get(state, state.upper()))
            self.state_label.setStyleSheet(f"color: {theme.STATE_COLORS.get(state, theme.CYAN)}")
            if state == "suspended":
                self.btn_mic.setChecked(False)
            elif not self.btn_mic.isChecked() and state != "suspended" and self.services.state.mic_enabled:
                self.btn_mic.setChecked(True)
        elif topic == "audio_level":
            self.reactor.set_level(payload.get("level", 0.0))
        elif topic == "transcript":
            text = payload.get("text", "")
            conf = payload.get("confidence", 1.0)
            self.heard.setText(f"“{text}”" + (f"  ({int(conf * 100)}%)" if payload.get("source") == "voice" else ""))
            self._append("user", text)
        elif topic == "reply":
            self._append("assistant", payload.get("text", ""), payload.get("display"))
        elif topic == "activity":
            self._add_activity(payload.get("text", ""), payload.get("kind", ""))
        elif topic == "notification":
            self._add_notification(payload)
        elif topic == "connection":
            service = payload.get("service")
            if service == "microsoft":
                for key in ("outlook", "excel"):
                    self.chips[key].set_status(payload.get("status", "off"), payload.get("detail", ""))
            elif service in self.chips:
                self.chips[service].set_status(payload.get("status", "off"), payload.get("detail", ""))
        elif topic == "game_mode":
            active = payload.get("active", False)
            self.chips["game"].set_status("ok" if active else "off", payload.get("reason", ""))
            if active and self.services.settings.get("gaming.pause_ui_in_game", True):
                self.reactor.stop()
            elif self.isVisible():
                self.reactor.start()
        elif topic == "confirm":
            if payload.get("id"):
                self.confirm_text.setText(payload.get("text", ""))
                details = payload.get("details", "")
                self.confirm_details.setText(details[:800])
                self.confirm_details.setVisible(bool(details))
                self.confirm_box.show()
            else:
                self.confirm_box.hide()
        elif topic == "settings":
            self.apply_profile()

    def apply_profile(self) -> None:
        profile = self.services.settings.get("voice.profile", "jarvis")
        self.title.setText("F.R.I.D.A.Y." if profile == "friday" else "J.A.R.V.I.S.")
        word = (self.services.settings.get("wake.words", ["jarvis"]) or ["jarvis"])[0].upper()
        theme.STATE_LABELS["idle"] = f"AGUARDANDO \"{word}\""
        if self.reactor.state == "idle":
            self.state_label.setText(theme.STATE_LABELS["idle"])

    def _append(self, role: str, text: str, display: str | None = None) -> None:
        if not text and not display:
            return
        when = datetime.now().strftime("%H:%M")
        if role == "user":
            block = (f"<div style='margin:6px 0; text-align:right'><span style='color:{theme.MUTED}; font-size:10px'>{when} VOCÊ</span><br>"
                     f"<span style='background:#0c2a3d; padding:6px'>{html.escape(text)}</span></div>")
        else:
            name = "FRIDAY" if self.services.settings.get("voice.profile") == "friday" else "JARVIS"
            extra = ""
            if display:
                extra = (f"<pre style='color:{theme.MUTED}; font-family:Consolas,monospace; font-size:11px; "
                         f"white-space:pre-wrap'>{html.escape(display)}</pre>")
            block = (f"<div style='margin:6px 0'><span style='color:{theme.CYAN}; font-size:10px'>{when} {name}</span><br>"
                     f"<span>{html.escape(text)}</span>{extra}</div>")
        self.chat.append(block)
        self.chat.verticalScrollBar().setValue(self.chat.verticalScrollBar().maximum())

    def _add_activity(self, text: str, kind: str) -> None:
        item = QListWidgetItem(f"{datetime.now():%H:%M}  {text}")
        if kind == "error":
            item.setForeground(Qt.red)
        self.activity.insertItem(0, item)
        while self.activity.count() > 200:
            self.activity.takeItem(self.activity.count() - 1)

    def _add_notification(self, n: dict) -> None:
        from ..notifications.center import NotificationCenter

        item = QListWidgetItem(NotificationCenter.format_line(n))
        item.setData(Qt.UserRole, n.get("link"))
        if n.get("important"):
            item.setForeground(Qt.yellow)
        self.notes.insertItem(0, item)
        while self.notes.count() > 200:
            self.notes.takeItem(self.notes.count() - 1)

    def load_history(self, notifications: list[dict], activities: list[dict]) -> None:
        for n in reversed(notifications):
            self._add_notification(n)
        for a in reversed(activities):
            item = QListWidgetItem(f"{datetime.fromtimestamp(a['ts']):%d/%m %H:%M}  {a['text']}")
            self.activity.insertItem(0, item)

    def _open_notification(self, item: QListWidgetItem) -> None:
        link = item.data(Qt.UserRole)
        if link:
            self.app.open_url(link)

    def _send_text(self) -> None:
        text = self.input.text().strip()
        if text:
            self.input.clear()
            self.app.submit_text(text)

    # --------------------------------------------------- janela sem moldura
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and event.position().y() < 60:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag = None

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.services.settings.get("general.close_to_tray", True) and not self.app.quitting:
            event.ignore()
            self.hide()
            self.app.notify_tray_once()
        else:
            event.accept()

    def changeEvent(self, event) -> None:  # noqa: N802
        if self.isMinimized():
            self.reactor.stop()
        elif self.isVisible():
            self.reactor.start()
        super().changeEvent(event)
