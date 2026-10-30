"""Música de fundo escolhida pelo usuário (ex.: a trilha que você associa ao Homem de Ferro).

* O arquivo é seu (MP3, WAV, FLAC ou OGG); o JARVIS não inclui músicas com direitos autorais.
* Toca em fluxo (não carrega o arquivo inteiro na memória), com entrada e saída suaves.
* Abaixa sozinha enquanto o JARVIS escuta (para não atrapalhar o reconhecimento)
  e enquanto ele fala, voltando ao volume normal depois.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

RATE = 44100
CHANNELS = 2
BLOCK = 2048
SUPPORTED = (".mp3", ".wav", ".flac", ".ogg")

# fator de volume da música conforme o estado do assistente
DUCK = {"listening": 0.08, "processing": 0.4, "speaking": 0.3}


def fade_gain(position: int, total: int | None, fade_frames: int) -> float:
    """Ganho de entrada/saída suave para a posição atual (em quadros)."""
    gain = 1.0
    if position < fade_frames:
        gain = position / fade_frames
    if total is not None and total - position < fade_frames:
        gain = min(gain, max(0.0, (total - position) / fade_frames))
    return gain


class MusicPlayer:
    def __init__(self, settings, bus=None) -> None:
        self.settings = settings
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._duck = 1.0
        self._lock = threading.Lock()
        self.current: str = ""
        if bus is not None:
            bus.subscribe("state", self._on_state)

    @property
    def playing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _on_state(self, event: dict) -> None:
        self._duck = DUCK.get(event.get("state", "idle"), 1.0)

    def validate(self, path: str) -> str | None:
        """Retorna mensagem de erro ou None se o arquivo pode ser tocado."""
        if not path:
            return "Nenhuma música escolhida. Selecione um arquivo em Configurações > Música."
        file = Path(path)
        if not file.exists():
            return f"Não encontrei o arquivo {file.name}."
        if file.suffix.lower() not in SUPPORTED:
            return "Formato não suportado. Use MP3, WAV, FLAC ou OGG."
        return None

    def play(self, path: str | None = None, max_seconds: float | None = None, loop: bool | None = None) -> str | None:
        path = path or self.settings.get("music.file", "")
        error = self.validate(path)
        if error:
            return error
        self.stop(fade=False)
        self._stop.clear()
        loop = self.settings.get("music.loop", False) if loop is None else loop
        if max_seconds is None:
            max_seconds = float(self.settings.get("music.max_seconds", 0) or 0) or None
        self.current = path
        self._thread = threading.Thread(target=self._run, args=(path, max_seconds, loop), name="music", daemon=True)
        self._thread.start()
        return None

    def stop(self, fade: bool = True) -> None:
        with self._lock:
            thread = self._thread
            if thread is None:
                return
            self._fade_out = fade
            self._stop.set()
        thread.join(timeout=2.5)
        self._thread = None

    def _run(self, path: str, max_seconds: float | None, loop: bool) -> None:
        import miniaudio
        import sounddevice as sd

        fade_frames = int(RATE * 1.5)
        limit = int(max_seconds * RATE) if max_seconds else None
        self._fade_out = True
        position = 0
        smoothed = self._duck
        try:
            with sd.OutputStream(samplerate=RATE, channels=CHANNELS, dtype="int16", blocksize=BLOCK,
                                 device=self.settings.get("audio.output_device")) as stream:
                while True:
                    stream_iter = miniaudio.stream_file(path, nchannels=CHANNELS, sample_rate=RATE, frames_to_read=BLOCK)
                    for chunk in stream_iter:
                        samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
                        frames = len(samples) // CHANNELS
                        if self._stop.is_set():
                            if self._fade_out:
                                self._fade_tail(stream, samples, smoothed)
                            return
                        volume = max(0, min(100, int(self.settings.get("music.volume", 30)))) / 100.0
                        smoothed += (self._duck - smoothed) * 0.35  # transição suave do "abaixar"
                        gain = volume * smoothed * fade_gain(position, limit, fade_frames)
                        stream.write((samples * gain).astype(np.int16).reshape(-1, CHANNELS))
                        position += frames
                        if limit is not None and position >= limit:
                            return
                    if not loop:
                        return
        except Exception:  # noqa: BLE001 - arquivo corrompido, dispositivo removido etc.
            log.exception("Falha ao tocar a música de fundo")
        finally:
            self.current = ""

    def _fade_tail(self, stream, samples: np.ndarray, duck: float) -> None:
        """Encerra com saída rápida (0,5 s) em vez de cortar o som."""
        volume = max(0, min(100, int(self.settings.get("music.volume", 30)))) / 100.0
        steps = max(1, int(RATE * 0.5) // BLOCK)
        for step in range(steps):
            gain = volume * duck * (1 - (step + 1) / steps)
            stream.write((samples * gain).astype(np.int16).reshape(-1, CHANNELS))
