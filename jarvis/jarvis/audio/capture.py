"""Captura do microfone em 16 kHz mono (formato exigido pelos reconhecedores).

O áudio fica só na memória do processo; nada é gravado em disco nem enviado
para a internet pelo reconhecimento local.
"""
from __future__ import annotations

import logging
import queue
import threading
import time

import numpy as np

log = logging.getLogger(__name__)

RATE = 16000
FRAME_MS = 50
FRAME_SAMPLES = RATE * FRAME_MS // 1000  # 800 amostras = 1600 bytes


def resample(samples: np.ndarray, src_rate: int, dst_rate: int = RATE) -> np.ndarray:
    if src_rate == dst_rate or len(samples) == 0:
        return samples
    duration = len(samples) / src_rate
    target_len = int(round(duration * dst_rate))
    x_old = np.linspace(0, duration, num=len(samples), endpoint=False)
    x_new = np.linspace(0, duration, num=target_len, endpoint=False)
    return np.interp(x_new, x_old, samples.astype(np.float32)).astype(np.int16)


class MicStream:
    def __init__(self, device=None) -> None:
        self.device = device
        self.frames: queue.Queue[bytes] = queue.Queue(maxsize=400)
        self._stream = None
        self._src_rate = RATE
        self._lock = threading.Lock()
        self.error: str = ""
        self._buffer = np.zeros(0, dtype=np.int16)

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        samples = np.frombuffer(bytes(indata), dtype=np.int16)
        if self._src_rate != RATE:
            samples = resample(samples, self._src_rate)
        self._buffer = np.concatenate([self._buffer, samples])
        while len(self._buffer) >= FRAME_SAMPLES:
            frame, self._buffer = self._buffer[:FRAME_SAMPLES], self._buffer[FRAME_SAMPLES:]
            try:
                self.frames.put_nowait(frame.tobytes())
            except queue.Full:
                try:
                    self.frames.get_nowait()  # descarta o mais antigo para não acumular atraso
                    self.frames.put_nowait(frame.tobytes())
                except queue.Empty:
                    pass

    def open(self) -> bool:
        import sounddevice as sd

        with self._lock:
            if self._stream is not None:
                return True
            for rate in (RATE, None):
                try:
                    if rate is None:
                        info = sd.query_devices(self.device, "input")
                        rate = int(info["default_samplerate"])
                    self._src_rate = rate
                    blocksize = int(rate * FRAME_MS / 1000)
                    self._stream = sd.RawInputStream(samplerate=rate, channels=1, dtype="int16", device=self.device,
                                                     blocksize=blocksize, callback=self._callback)
                    self._stream.start()
                    self.error = ""
                    log.info("Microfone aberto (%s Hz)", rate)
                    return True
                except Exception as exc:  # noqa: BLE001
                    self._stream = None
                    self.error = str(exc)
            log.error("Não foi possível abrir o microfone: %s", self.error)
            return False

    def close(self) -> None:
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:  # noqa: BLE001
                    pass
                self._stream = None
            self.drain()

    @property
    def is_open(self) -> bool:
        return self._stream is not None and bool(getattr(self._stream, "active", False))

    def read(self, timeout: float = 0.5) -> bytes | None:
        try:
            return self.frames.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self) -> None:
        while True:
            try:
                self.frames.get_nowait()
            except queue.Empty:
                return

    def reopen(self) -> bool:
        self.close()
        time.sleep(0.5)
        return self.open()


def list_input_devices() -> list[tuple[int, str]]:
    try:
        import sounddevice as sd

        hostapis = sd.query_hostapis()
        return [(i, f"{d['name']} ({hostapis[d['hostapi']]['name']})")
                for i, d in enumerate(sd.query_devices()) if d.get("max_input_channels", 0) > 0]
    except Exception:  # noqa: BLE001
        return []


def list_output_devices() -> list[tuple[int, str]]:
    try:
        import sounddevice as sd

        hostapis = sd.query_hostapis()
        return [(i, f"{d['name']} ({hostapis[d['hostapi']]['name']})")
                for i, d in enumerate(sd.query_devices()) if d.get("max_output_channels", 0) > 0]
    except Exception:  # noqa: BLE001
        return []
