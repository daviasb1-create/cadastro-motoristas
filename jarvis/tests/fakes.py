"""Dublês de teste para microfone, voz e reconhecimento."""
from __future__ import annotations

import queue
import threading

import numpy as np

FRAME = 800


def speech_frame(amplitude: int = 4000) -> bytes:
    t = np.arange(FRAME) / 16000
    return (np.sin(2 * np.pi * 220 * t) * amplitude).astype(np.int16).tobytes()


def silence_frame() -> bytes:
    return np.zeros(FRAME, dtype=np.int16).tobytes()


class FakeMic:
    def __init__(self, realtime: bool = False) -> None:
        self.frames: queue.Queue[bytes] = queue.Queue()
        self.opened = 0
        self.realtime = realtime

    def open(self) -> bool:
        self.opened += 1
        return True

    def close(self) -> None:
        pass

    def read(self, timeout: float = 0.5):
        try:
            frame = self.frames.get(timeout=min(timeout, 0.05))
            if self.realtime:
                import time

                time.sleep(0.05)  # simula o ritmo real do microfone (50 ms por quadro)
            return frame
        except queue.Empty:
            return None

    def drain(self) -> None:
        pass

    def push(self, frames: list[bytes]) -> None:
        for f in frames:
            self.frames.put(f)


class FakeWake:
    """Dispara quando recebe o quadro marcado."""

    def __init__(self, marker: bytes) -> None:
        self.marker = marker
        self.resets = 0

    def process(self, frame: bytes) -> bool:
        return frame == self.marker

    def reset(self) -> None:
        self.resets += 1


class FakeSession:
    def __init__(self, stt: "FakeSTT") -> None:
        self.stt = stt
        self.fed = 0

    def feed(self, frame: bytes) -> None:
        if any(frame):
            self.fed += 1

    def partial(self) -> str:
        return self.stt.text if self.fed >= self.stt.after_frames else ""

    def result(self):
        return (self.stt.text if self.fed >= self.stt.after_frames else ""), self.stt.confidence


class FakeSTT:
    def __init__(self, text: str = "", confidence: float = 0.9, after_frames: int = 1) -> None:
        self.text = text
        self.confidence = confidence
        self.after_frames = after_frames

    def session(self) -> FakeSession:
        return FakeSession(self)


class FakeSpeaker:
    def __init__(self) -> None:
        self.said: list[str] = []
        self.speaking = threading.Event()
        self._queue: queue.Queue = queue.Queue()
        self.stops = 0
        self.cues = 0

    def say(self, text: str, wait: bool = False, force: bool = False) -> None:
        self.said.append(text)

    def stop(self) -> None:
        self.stops += 1
        self.speaking.clear()

    def cue(self, kind: str = "listen") -> None:
        self.cues += 1
