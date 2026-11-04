"""Componentes visuais reutilizáveis."""
from __future__ import annotations

import time
from collections import deque

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QHeaderView, QLabel, QSizePolicy, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from netvision.ui import theme

pg.setConfigOptions(antialias=True, background=theme.SURFACE, foreground=theme.MUTED)


# ------------------------------------------------------------------ formatação
def fmt_rate(bps: float | None) -> str:
    if bps is None:
        return "-"
    for unit, div in (("Gbps", 1e9), ("Mbps", 1e6), ("Kbps", 1e3)):
        if bps >= div:
            return f"{bps / div:.1f} {unit}".replace(".", ",")
    return f"{bps:.0f} bps"


def fmt_bytes(n: float | None) -> str:
    if n is None:
        return "-"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return (f"{n:.1f} {unit}" if unit != "B" else f"{n:.0f} B").replace(".", ",")
        n /= 1024
    return "-"


def fmt_ms(v: float | None, dec: int = 0) -> str:
    return "-" if v is None else f"{v:.{dec}f} ms".replace(".", ",")


def fmt_pct(v: float | None, dec: int = 1) -> str:
    return "-" if v is None else f"{v:.{dec}f}%".replace(".", ",")


def fmt_duration(s: float | None) -> str:
    if s is None:
        return "-"
    s = int(s)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, _ = divmod(s, 60)
    return f"{d}d {h}h {m}min" if d else f"{h}h {m}min"


def quality_color(ping: float | None, loss: float | None) -> str:
    if ping is None:
        return theme.MUTED
    if (loss or 0) >= 5 or ping >= 150:
        return theme.BAD
    if (loss or 0) >= 1 or ping >= 80:
        return theme.WARN
    return theme.OK


# ------------------------------------------------------------------ cartões
class Card(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 14)
        self.body.setSpacing(6)


class KpiCard(Card):
    def __init__(self, title: str, value: str = "-", sub: str = "", accent: str = theme.ACCENT):
        super().__init__()
        self.title = QLabel(title.upper())
        self.title.setObjectName("cardTitle")
        self.value = QLabel(value)
        self.value.setObjectName("cardValue")
        self.sub = QLabel(sub)
        self.sub.setObjectName("cardSub")
        self.sub.setWordWrap(True)
        bar = QFrame()
        bar.setFixedHeight(3)
        bar.setStyleSheet(f"background:{accent}; border-radius:1px;")
        self.bar = bar
        for w in (bar, self.title, self.value, self.sub):
            self.body.addWidget(w)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(170)

    def set(self, value: str, sub: str | None = None, color: str | None = None) -> None:
        self.value.setText(value)
        if sub is not None:
            self.sub.setText(sub)
        self.value.setStyleSheet(f"color:{color};" if color else "")


class Pill(QLabel):
    def __init__(self, text: str = ""):
        super().__init__(text)
        self.set(text, theme.MUTED)

    def set(self, text: str, color: str) -> None:
        self.setText(f"●  {text}")
        self.setStyleSheet(f"color:{color}; background:{theme.SURFACE_2}; border:1px solid {theme.BORDER};"
                           "border-radius:11px; padding:3px 10px; font-weight:600;")


def section(title: str) -> QLabel:
    lb = QLabel(title)
    lb.setObjectName("sectionTitle")
    return lb


def hint(text: str, kind: str = "hint") -> QLabel:
    lb = QLabel(text)
    lb.setObjectName(kind)
    lb.setWordWrap(True)
    lb.setTextFormat(Qt.RichText)
    lb.setOpenExternalLinks(True)
    return lb


def hbox(*widgets, spacing: int = 12) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    for w in widgets:
        if isinstance(w, int):
            lay.addStretch(w)
        else:
            lay.addWidget(w)
    return lay


# ------------------------------------------------------------------ gráficos
_DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


class PtDateAxis(pg.DateAxisItem):
    """Eixo de tempo com rótulos em português (independe do idioma do sistema)."""

    def tickStrings(self, values, scale, spacing):
        from datetime import datetime
        out = []
        for v in values:
            try:
                d = datetime.fromtimestamp(v)
            except (OverflowError, OSError, ValueError):
                out.append("")
                continue
            if spacing >= 86400:
                out.append(f"{_DIAS[d.weekday()]} {d:%d/%m}")
            elif spacing >= 3600:
                out.append(f"{d:%d/%m %H:%M}" if d.hour == 0 else f"{d:%H:%M}")
            elif spacing >= 60:
                out.append(f"{d:%H:%M}")
            else:
                out.append(f"{d:%H:%M:%S}")
        return out


class UnitAxis(pg.AxisItem):
    def __init__(self, fmt, *a, **kw):
        super().__init__(*a, **kw)
        self._fmt = fmt

    def tickStrings(self, values, scale, spacing):
        if not self._fmt:
            return super().tickStrings(values, scale, spacing)
        return [self._fmt(v) if v >= 0 else "" for v in values]


def _short_rate(v: float) -> str:
    return fmt_rate(v).replace(",0 ", " ")


class TimeChart(Card):
    """Gráfico de séries temporais em tempo real (pyqtgraph)."""

    def __init__(self, title: str, series: list[tuple[str, str]], unit_fmt=None, window_s: int = 300,
                 height: int = 220, fill: bool = True):
        super().__init__()
        self.window_s = window_s
        self.unit_fmt = unit_fmt
        head = QHBoxLayout()
        t = QLabel(title)
        t.setObjectName("sectionTitle")
        head.addWidget(t)
        head.addStretch(1)
        self.legend = QLabel("")
        self.legend.setObjectName("hint")
        head.addWidget(self.legend)
        self.body.addLayout(head)
        axis_fmt = _short_rate if unit_fmt is fmt_rate else None
        self.plot = pg.PlotWidget(axisItems={"bottom": PtDateAxis(orientation="bottom"),
                                             "left": UnitAxis(axis_fmt, orientation="left")})
        self.plot.getViewBox().setLimits(yMin=0)
        self.plot.getAxis("left").setWidth(64 if axis_fmt else 40)
        self.plot.setMinimumHeight(height)
        self.plot.showGrid(x=True, y=True, alpha=0.12)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.hideButtons()
        self.plot.getPlotItem().setMenuEnabled(False)
        for ax in ("left", "bottom"):
            self.plot.getAxis(ax).setPen(pg.mkPen(theme.BORDER))
            self.plot.getAxis(ax).setTextPen(pg.mkPen(theme.MUTED))
        self.body.addWidget(self.plot)
        self.data: dict[str, deque] = {}
        self.curves = {}
        self.names = {}
        for key, color in series:
            name = key
            self.names[key] = name
            self.data[key] = deque(maxlen=max(window_s * 2, 600))
            c = QColor(color)
            brush = QColor(c.red(), c.green(), c.blue(), 40) if fill else None
            self.curves[key] = self.plot.plot([], [], pen=pg.mkPen(color, width=2),
                                              fillLevel=0 if fill else None, brush=brush, connect="finite")

    def add(self, key: str, value: float | None, ts: float | None = None) -> None:
        self.data[key].append((ts or time.time(), float("nan") if value is None else value))

    def set_series(self, key: str, points: list[tuple[float, float | None]]) -> None:
        self.data[key].clear()
        for ts, v in points:
            self.add(key, v, ts)

    def refresh(self, live: bool = True) -> None:
        now = time.time()
        parts = []
        for key, pts in self.data.items():
            if live:
                while pts and pts[0][0] < now - self.window_s:
                    pts.popleft()
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            few = len(xs) < 4
            self.curves[key].setData(xs, ys, symbol="o" if few else None, symbolSize=6,
                                     symbolBrush=self.curves[key].opts["pen"].color())
            if ys and self.unit_fmt:
                last = next((y for y in reversed(ys) if y == y), None)
                if last is not None:
                    parts.append(f"<span style='color:{self.curves[key].opts['pen'].color().name()}'>● {key}: "
                                 f"{self.unit_fmt(last)}</span>")
        self.legend.setText("   ".join(parts))
        self.legend.setTextFormat(Qt.RichText)
        if live:
            self.plot.setXRange(now - self.window_s, now, padding=0)


# ------------------------------------------------------------------ tabela
class DataTable(QTableWidget):
    def __init__(self, headers: list[str], stretch_col: int | None = 0):
        super().__init__(0, len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setShowGrid(False)
        self.setWordWrap(False)
        h = self.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeToContents)
        if stretch_col is not None:
            h.setSectionResizeMode(stretch_col, QHeaderView.Stretch)
        self.setSortingEnabled(False)

    def fill(self, rows: list[list], colors: dict[tuple[int, int], str] | None = None,
             keys: list | None = None) -> None:
        self.setUpdatesEnabled(False)
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                it = self.item(r, c)
                text = "" if val is None else str(val)
                if it is None:
                    it = QTableWidgetItem(text)
                    self.setItem(r, c, it)
                elif it.text() != text:
                    it.setText(text)
                color = (colors or {}).get((r, c))
                it.setForeground(QColor(color) if color else QColor(theme.TEXT))
                if keys is not None and c == 0:
                    it.setData(Qt.UserRole, keys[r])
        self.setUpdatesEnabled(True)

    def selected_key(self):
        rows = self.selectionModel().selectedRows()
        if not rows:
            return None
        it = self.item(rows[0].row(), 0)
        return it.data(Qt.UserRole) if it else None
