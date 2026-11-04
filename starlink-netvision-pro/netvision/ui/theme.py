"""Tema escuro "central de controle"."""

BG = "#070b14"
SURFACE = "#0e1526"
SURFACE_2 = "#131c31"
BORDER = "#1f2a44"
TEXT = "#e2e8f0"
MUTED = "#8b9ab4"
ACCENT = "#22d3ee"
ACCENT_2 = "#818cf8"
OK = "#34d399"
WARN = "#fbbf24"
BAD = "#f87171"

QSS = f"""
* {{ font-family: "Segoe UI", "Inter", sans-serif; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QWidget#root {{ background: {BG}; }}
QWidget {{ background: transparent; }}
QToolTip {{ background: {SURFACE_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px; }}

#sidebar {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
#brand {{ font-size: 13pt; font-weight: 700; color: {ACCENT}; letter-spacing: 1px; }}
#brandSub {{ color: {MUTED}; font-size: 7.5pt; letter-spacing: 1px; }}
QListWidget#nav {{ border: none; outline: 0; padding: 4px; }}
QListWidget#nav::item {{ padding: 10px 12px; border-radius: 8px; margin: 2px 4px; color: {MUTED}; }}
QListWidget#nav::item:hover {{ background: {SURFACE_2}; color: {TEXT}; }}
QListWidget#nav::item:selected {{ background: #0f2a3a; color: {ACCENT}; border-left: 3px solid {ACCENT}; }}

#topbar {{ background: {BG}; border-bottom: 1px solid {BORDER}; }}
#pageTitle {{ font-size: 15pt; font-weight: 600; }}

QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
#cardTitle {{ color: {MUTED}; font-size: 8.5pt; letter-spacing: 1px; text-transform: uppercase; }}
#cardValue {{ font-size: 17pt; font-weight: 600; }}
#cardSub {{ color: {MUTED}; font-size: 8.5pt; }}
#sectionTitle {{ font-size: 11pt; font-weight: 600; color: {TEXT}; padding: 4px 0; }}
#hint {{ color: {MUTED}; font-size: 9pt; }}
#notice {{ background: #1a1630; border: 1px solid #3b3470; border-radius: 8px; padding: 8px 10px; color: #c7d2fe; }}
#warnbox {{ background: #2a1f0b; border: 1px solid #6b4e12; border-radius: 8px; padding: 8px 10px; color: #fde68a; }}

QPushButton {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: #0f2a3a; }}
QPushButton:disabled {{ color: #4b5568; }}
QPushButton#primary {{ background: #0e7490; border-color: #0891b2; font-weight: 600; }}
QPushButton#primary:hover {{ background: #0891b2; }}
QPushButton#danger {{ background: #4c1d1d; border-color: #7f1d1d; }}

QTableWidget, QTreeWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px;
    gridline-color: {BORDER}; selection-background-color: #0f2a3a; alternate-background-color: #101830; }}
QHeaderView::section {{ background: {SURFACE_2}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
    padding: 6px 8px; font-weight: 600; }}
QTableCornerButton::section {{ background: {SURFACE_2}; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 5px; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{ background: {SURFACE_2}; border: 1px solid {BORDER};
    border-radius: 6px; padding: 5px 8px; selection-background-color: #0e7490; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {SURFACE_2}; border: 1px solid {BORDER}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {BORDER}; background: {SURFACE_2}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 8px 14px; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {ACCENT}; border-bottom-color: {ACCENT}; }}
QProgressBar {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 6px; text-align: center; height: 14px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 6px; }}
QScrollArea {{ border: none; }}
QMenu {{ background: {SURFACE_2}; border: 1px solid {BORDER}; }}
QMenu::item:selected {{ background: #0f2a3a; }}
"""
