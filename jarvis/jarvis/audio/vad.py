"""Detector simples de voz por energia, com piso de ruído adaptativo.

Serve para economizar CPU (o reconhecedor só trabalha quando há som) e para
saber quando o usuário terminou de falar.
"""
from __future__ import annotations

from collections import deque

import numpy as np


def rms(frame: bytes) -> float:
    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples * samples)))


class EnergyVAD:
    def __init__(self, gate: float = 1.0, min_level: float = 260.0) -> None:
        self.gate = gate
        self.min_level = min_level
        self.noise = 200.0
        self.level = 0.0
        self._history: deque[bool] = deque(maxlen=4)

    def is_speech(self, frame: bytes) -> bool:
        self.level = rms(frame)
        threshold = max(self.min_level, self.noise * 2.6) * self.gate
        speech = self.level > threshold
        if not speech:
            # piso de ruído acompanha o ambiente (ventilador, jogo ao fundo)
            self.noise = 0.95 * self.noise + 0.05 * max(self.level, 50.0)
        self._history.append(speech)
        # exige 2 de 4 quadros para considerar fala (ignora estalos)
        return sum(self._history) >= 2

    def normalized_level(self) -> float:
        return min(1.0, self.level / 6000.0)
