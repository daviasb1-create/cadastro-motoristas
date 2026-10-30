"""Núcleo visual animado do assistente (inspirado num reator arc).

A animação roda a ~30 fps apenas com a janela visível; com a janela oculta,
minimizada ou em modo jogo, o temporizador para e o consumo de CPU é zero.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from . import theme


class ReactorWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(260, 260)
        self.state = "idle"
        self.level = 0.0
        self._smooth = 0.0
        self._angle = 0.0
        self._t0 = time.time()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.animations_enabled = True

    # ---------------------------------------------------------- controle
    def set_state(self, state: str) -> None:
        self.state = state
        self.update()

    def set_level(self, level: float) -> None:
        self.level = max(0.0, min(1.0, level))

    def start(self) -> None:
        if self.animations_enabled and not self._timer.isActive():
            self._timer.start(33)

    def stop(self) -> None:
        self._timer.stop()

    def showEvent(self, event) -> None:  # noqa: N802
        self.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        speed = {"listening": 2.6, "processing": 5.0, "speaking": 2.0}.get(self.state, 0.7)
        self._angle = (self._angle + speed) % 360
        self._smooth += (self.level - self._smooth) * 0.25
        self.level *= 0.9
        self.update()

    # ---------------------------------------------------------- desenho
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        size = min(w, h) - 10
        center = QPointF(w / 2, h / 2)
        radius = size / 2
        color = QColor(theme.STATE_COLORS.get(self.state, theme.CYAN))
        t = time.time() - self._t0
        pulse = 0.5 + 0.5 * math.sin(t * (6 if self.state == "speaking" else 2))
        energy = self._smooth if self.state in ("listening", "speaking") else 0.0

        # brilho de fundo
        glow = QRadialGradient(center, radius)
        g = QColor(color)
        g.setAlpha(int(40 + 50 * energy + 20 * pulse))
        glow.setColorAt(0.0, g)
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(center, radius, radius)

        # anel externo segmentado (gira)
        self._ring(painter, center, radius * 0.92, 36, 5, self._angle, color, 3, 150)
        # anel tracejado médio (gira ao contrário)
        self._ring(painter, center, radius * 0.78, 12, 18, -self._angle * 1.6, color, 2, 200)
        # anel fino contínuo
        pen = QPen(QColor(color.red(), color.green(), color.blue(), 90), 1.2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(center, radius * 0.66, radius * 0.66)

        # arcos de processamento
        if self.state == "processing":
            pen = QPen(QColor(theme.CYAN), 4, Qt.SolidLine, Qt.RoundCap)
            painter.setPen(pen)
            r = radius * 0.58
            rect = QRectF(center.x() - r, center.y() - r, 2 * r, 2 * r)
            painter.drawArc(rect, int(-self._angle * 16 * 3), 70 * 16)
            painter.drawArc(rect, int((-self._angle * 3 + 180) * 16), 70 * 16)

        # triângulos internos (estilo reator)
        painter.save()
        painter.translate(center)
        painter.rotate(self._angle * 0.3)
        tri = QColor(color)
        tri.setAlpha(130)
        painter.setPen(QPen(tri, 2))
        r = radius * 0.46
        for offset in (-90, 90):  # dois triângulos sobrepostos (hexagrama)
            for k in range(3):
                a = math.radians(k * 120 + offset)
                b = math.radians(k * 120 + 120 + offset)
                painter.drawLine(QPointF(r * math.cos(a), r * math.sin(a)), QPointF(r * math.cos(b), r * math.sin(b)))
        painter.restore()

        # núcleo pulsante (reage ao volume da voz)
        core_r = radius * (0.24 + 0.08 * pulse * (0.4 if self.state == "idle" else 1) + 0.12 * energy)
        core = QRadialGradient(center, core_r)
        bright = QColor("#e0fbff")
        core.setColorAt(0.0, bright)
        mid = QColor(color)
        mid.setAlpha(230)
        core.setColorAt(0.45, mid)
        edge = QColor(color)
        edge.setAlpha(0)
        core.setColorAt(1.0, edge)
        painter.setPen(Qt.NoPen)
        painter.setBrush(core)
        painter.drawEllipse(center, core_r, core_r)
        painter.end()

    @staticmethod
    def _ring(painter, center, radius, segments, gap_deg, angle, color, width, alpha) -> None:
        pen = QPen(QColor(color.red(), color.green(), color.blue(), alpha), width, Qt.SolidLine, Qt.FlatCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        rect = QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)
        step = 360 / segments
        for i in range(segments):
            start = angle + i * step
            painter.drawArc(rect, int(start * 16), int((step - gap_deg) * 16))
