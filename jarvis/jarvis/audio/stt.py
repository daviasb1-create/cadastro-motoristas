"""Reconhecimento de fala em português, LOCAL (o áudio não sai do computador).

* VoskSTT (padrão): leve, em tempo real, modelo pt-BR pequeno (~31 MB).
* WhisperSTT (opcional): faster-whisper, mais preciso e mais pesado em CPU;
  o modelo é baixado automaticamente no primeiro uso.
"""
from __future__ import annotations

import json
import logging
import math

import numpy as np

log = logging.getLogger(__name__)


class STTSession:
    def feed(self, frame: bytes) -> None:
        raise NotImplementedError

    def partial(self) -> str:
        return ""

    def result(self) -> tuple[str, float]:
        raise NotImplementedError


class VoskSession(STTSession):
    def __init__(self, model) -> None:
        from vosk import KaldiRecognizer

        self._rec = KaldiRecognizer(model, 16000)
        self._rec.SetWords(True)
        self._texts: list[str] = []
        self._confs: list[float] = []
        self._partial = ""

    def _collect(self, raw: str) -> None:
        data = json.loads(raw)
        text = data.get("text", "").strip()
        if text:
            self._texts.append(text)
            self._confs += [w.get("conf", 1.0) for w in data.get("result", [])]

    def feed(self, frame: bytes) -> None:
        if self._rec.AcceptWaveform(frame):
            self._collect(self._rec.Result())
            self._partial = ""
        else:
            self._partial = json.loads(self._rec.PartialResult()).get("partial", "")

    def partial(self) -> str:
        return " ".join(self._texts + ([self._partial] if self._partial else []))

    def result(self) -> tuple[str, float]:
        self._collect(self._rec.FinalResult())
        text = " ".join(self._texts).strip()
        conf = sum(self._confs) / len(self._confs) if self._confs else (1.0 if text else 0.0)
        return text, conf


class VoskSTT:
    name = "vosk"

    def __init__(self, model) -> None:
        self.model = model

    def session(self) -> VoskSession:
        return VoskSession(self.model)


class WhisperSession(STTSession):
    def __init__(self, engine: "WhisperSTT") -> None:
        self.engine = engine
        self._chunks: list[bytes] = []

    def feed(self, frame: bytes) -> None:
        self._chunks.append(frame)

    def result(self) -> tuple[str, float]:
        audio = np.frombuffer(b"".join(self._chunks), dtype=np.int16).astype(np.float32) / 32768.0
        if audio.size < 4000:
            return "", 0.0
        segments, _info = self.engine.model.transcribe(audio, language="pt", beam_size=1, vad_filter=True,
                                                       condition_on_previous_text=False)
        texts, logprobs = [], []
        for segment in segments:
            texts.append(segment.text.strip())
            logprobs.append(segment.avg_logprob)
        text = " ".join(t for t in texts if t)
        conf = math.exp(sum(logprobs) / len(logprobs)) if logprobs else 0.0
        return text, min(1.0, conf * 1.2)


class WhisperSTT:
    name = "whisper"

    def __init__(self, size: str = "small") -> None:
        from faster_whisper import WhisperModel  # type: ignore

        self.model = WhisperModel(size, device="cpu", compute_type="int8")

    def session(self) -> WhisperSession:
        return WhisperSession(self)
