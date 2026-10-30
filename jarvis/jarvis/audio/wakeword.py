"""Detecção LOCAL da palavra de ativação ("Jarvis").

* VoskWakeDetector (padrão, gratuito, sem conta): reconhecedor com gramática
  restrita às variantes da palavra. Funciona offline. A calibração ensina
  como o modelo transcreve a SUA pronúncia de "Jarvis".
* PorcupineWakeDetector (opcional): palavra "jarvis" embutida da Picovoice,
  mais precisa; exige AccessKey gratuita para uso pessoal.

Nenhum áudio sai do computador nesta etapa.
"""
from __future__ import annotations

import json
import logging

import numpy as np

from ..nlu.normalize import normalize

log = logging.getLogger(__name__)


class WakeDetector:
    name = "base"

    def process(self, frame: bytes) -> bool:
        raise NotImplementedError

    def reset(self) -> None:
        pass


class VoskWakeDetector(WakeDetector):
    name = "vosk"

    def __init__(self, model, variants: list[str], sensitivity: float = 0.5) -> None:
        from vosk import KaldiRecognizer

        self.variants = sorted({normalize(v) for v in variants if v})
        self.sensitivity = sensitivity
        grammar = json.dumps(self.variants + ["[unk]"], ensure_ascii=False)
        self._rec = KaldiRecognizer(model, 16000, grammar)
        self._hits = 0

    def _contains(self, text: str) -> bool:
        words = normalize(text).split()
        return any(v in words for v in self.variants) or any(
            " " in v and v in " ".join(words) for v in self.variants)

    def process(self, frame: bytes) -> bool:
        if self._rec.AcceptWaveform(frame):
            text = json.loads(self._rec.Result()).get("text", "")
            self._hits = 0
            if self._contains(text):
                self._rec.Reset()
                return True
            return False
        partial = json.loads(self._rec.PartialResult()).get("partial", "")
        if self._contains(partial):
            self._hits += 1
            needed = 1 if self.sensitivity >= 0.7 else 2
            if self._hits >= needed:
                self._hits = 0
                self._rec.Reset()
                return True
        else:
            self._hits = 0
        return False

    def reset(self) -> None:
        self._hits = 0
        self._rec.Reset()


class PorcupineWakeDetector(WakeDetector):
    name = "porcupine"

    def __init__(self, access_key: str, keyword: str = "jarvis", sensitivity: float = 0.5) -> None:
        import pvporcupine  # type: ignore

        self._porcupine = pvporcupine.create(access_key=access_key, keywords=[keyword],
                                             sensitivities=[max(0.0, min(1.0, sensitivity))])
        self._frame = self._porcupine.frame_length
        self._buffer = np.zeros(0, dtype=np.int16)

    def process(self, frame: bytes) -> bool:
        self._buffer = np.concatenate([self._buffer, np.frombuffer(frame, dtype=np.int16)])
        detected = False
        while len(self._buffer) >= self._frame:
            chunk, self._buffer = self._buffer[: self._frame], self._buffer[self._frame:]
            if self._porcupine.process(chunk.tolist()) >= 0:
                detected = True
        return detected

    def reset(self) -> None:
        self._buffer = np.zeros(0, dtype=np.int16)

    def close(self) -> None:
        self._porcupine.delete()
