"""Reprodução de áudio com volume próprio e interrupção imediata."""
from __future__ import annotations

import logging
import threading

import numpy as np

from .tts import AudioClip

log = logging.getLogger(__name__)


def beep(freq: float = 880.0, ms: int = 120, rate: int = 24000, volume: float = 0.35,
         second: float | None = None) -> AudioClip:
    """Bipe curto com rampa (sem estalos). ``second`` cria um bipe duplo ascendente."""
    t = np.arange(int(rate * ms / 1000)) / rate
    tone = np.sin(2 * np.pi * freq * t)
    ramp = min(len(t) // 4, int(rate * 0.01))
    if ramp:
        envelope = np.ones_like(tone)
        envelope[:ramp] = np.linspace(0, 1, ramp)
        envelope[-ramp:] = np.linspace(1, 0, ramp)
        tone *= envelope
    if second:
        gap = np.zeros(int(rate * 0.03))
        t2 = np.arange(int(rate * ms / 1000)) / rate
        tone2 = np.sin(2 * np.pi * second * t2)
        if ramp:
            tone2[:ramp] *= np.linspace(0, 1, ramp)
            tone2[-ramp:] *= np.linspace(1, 0, ramp)
        tone = np.concatenate([tone, gap, tone2])
    return AudioClip((tone * volume * 32767).astype(np.int16), rate)


class Player:
    def __init__(self, settings) -> None:
        self.settings = settings
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.playing = False

    def stop(self) -> None:
        self._stop.set()

    def play(self, clip: AudioClip, volume: float | None = None) -> bool:
        """Toca o clipe (bloqueante). Retorna False se foi interrompido."""
        import sounddevice as sd

        if volume is None:
            volume = self.settings.get("voice.volume", 85) / 100.0
        samples = (clip.samples.astype(np.float32) * max(0.0, min(1.0, volume))).astype(np.int16)
        self._stop.clear()
        device = self.settings.get("audio.output_device")
        block = 1024
        with self._lock:
            self.playing = True
            try:
                with sd.OutputStream(samplerate=clip.rate, channels=1, dtype="int16", device=device,
                                     blocksize=block) as stream:
                    for start in range(0, len(samples), block):
                        if self._stop.is_set():
                            return False
                        stream.write(samples[start:start + block].reshape(-1, 1))
                return True
            except Exception:  # noqa: BLE001 - dispositivo removido etc.
                log.exception("Falha ao reproduzir áudio")
                return False
            finally:
                self.playing = False
