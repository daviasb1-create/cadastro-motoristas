"""Paleta e folha de estilos (tema escuro com ciano/azul)."""
from __future__ import annotations

BG = "#05080d"
PANEL = "#0a121c"
PANEL_2 = "#0e1a28"
BORDER = "#12324a"
CYAN = "#22d3ee"
CYAN_DIM = "#0e7490"
BLUE = "#3b82f6"
AMBER = "#f59e0b"
RED = "#ef4444"
GREEN = "#22c55e"
TEXT = "#d7f3ff"
MUTED = "#6b8aa3"

STATE_COLORS = {
    "idle": CYAN_DIM, "listening": CYAN, "processing": BLUE, "speaking": "#67e8f9",
    "sleeping": "#1e3a5f", "suspended": "#334155",
}
STATE_LABELS = {
    "idle": "AGUARDANDO \"JARVIS\"", "listening": "OUVINDO", "processing": "PROCESSANDO",
    "speaking": "RESPONDENDO", "sleeping": "EM ESPERA", "suspended": "MICROFONE DESLIGADO",
}
STATUS_COLORS = {"ok": GREEN, "pending": AMBER, "error": RED, "off": "#475569"}

STYLESHEET = f"""
* {{ font-family: 'Segoe UI', 'Bahnschrift', sans-serif; color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QWidget#root {{ background: qradialgradient(cx:0.3, cy:0.2, radius:1.2, stop:0 #0b1a2a, stop:1 {BG});
                border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame#panel {{ background: rgba(10, 18, 28, 220); border: 1px solid {BORDER}; border-radius: 12px; }}
QLabel#title {{ font-family: 'Bahnschrift', 'Segoe UI'; font-size: 20px; letter-spacing: 6px; color: {CYAN}; }}
QLabel#subtitle {{ color: {MUTED}; font-size: 11px; letter-spacing: 2px; }}
QLabel#state {{ font-family: 'Bahnschrift', 'Segoe UI'; font-size: 13px; letter-spacing: 4px; color: {CYAN}; }}
QLabel#heard {{ color: {MUTED}; font-size: 12px; }}
QLabel#section {{ color: {CYAN}; font-size: 11px; letter-spacing: 3px; }}
QPushButton {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {CYAN}; background: #102438; }}
QPushButton:pressed {{ background: #0c3a52; }}
QPushButton#accent {{ background: #083344; border-color: {CYAN}; color: {CYAN}; font-weight: 600; }}
QPushButton#danger {{ border-color: #7f1d1d; color: #fca5a5; }}
QPushButton#flat {{ background: transparent; border: none; padding: 4px 8px; font-size: 15px; }}
QPushButton#flat:hover {{ color: {CYAN}; }}
QPushButton:checked {{ background: #0c3a52; border-color: {CYAN}; }}
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTimeEdit {{
    background: #07101a; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px; selection-background-color: {CYAN_DIM}; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: {CYAN}; }}
QComboBox QAbstractItemView {{ background: {PANEL}; border: 1px solid {BORDER}; }}
QTextBrowser, QListWidget, QTableWidget {{ background: transparent; border: none; }}
QListWidget::item {{ padding: 6px; border-bottom: 1px solid #0f2233; }}
QListWidget::item:selected {{ background: #0c2a3d; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 10px; top: -1px; background: {PANEL}; }}
QTabBar::tab {{ background: transparent; padding: 7px 12px; color: {MUTED}; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {CYAN}; border-bottom: 2px solid {CYAN}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {BORDER}; border-radius: 4px; background: #07101a; }}
QCheckBox::indicator:checked {{ background: {CYAN_DIM}; border-color: {CYAN}; }}
QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {CYAN}; width: 14px; margin: -6px 0; border-radius: 7px; }}
QScrollBar:vertical {{ background: transparent; width: 8px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QHeaderView::section {{ background: {PANEL_2}; border: none; padding: 4px; color: {MUTED}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QTabWidget QWidget#qt_scrollarea_viewport {{ background: transparent; }}
QLabel {{ background: transparent; }}
QTabBar QToolButton {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 4px; }}
QToolTip {{ background: {PANEL}; border: 1px solid {CYAN_DIM}; color: {TEXT}; }}
"""
