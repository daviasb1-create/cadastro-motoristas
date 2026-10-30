"""Fila de fala: sintetiza, reduz o volume dos outros apps, toca e permite interromper."""
from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass

from ..brain.responses import for_speech
from .ducking import Ducker
from .player import Player, beep
from .tts import AudioClip, TTSError, TTSManager

log = logging.getLogger(__name__)


@dataclass
class _Item:
    text: str
    clip: AudioClip | None = None
    done: threading.Event | None = None
    generation: int = 0


class Speaker:
    def __init__(self, settings, bus, state, secrets) -> None:
        self.settings = settings
        self.bus = bus
        self.state = state
        self.tts = TTSManager(settings, secrets, bus)
        self.player = Player(settings)
        self.cue_player = Player(settings)  # separado: um bipe não pode anular o "parar" da fala
        self.on_idle = None  # o ciclo de voz republica o próprio estado ao terminar de falar
        self.ducker = Ducker(settings, state)
        self._queue: queue.Queue[_Item | None] = queue.Queue()
        self._generation = 0
        self._current_stream = None
        self._last_text = ""
        self._last_started = 0.0
        self._lock = threading.Lock()
        self.speaking = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="speaker", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------- API
    def say(self, text: str, wait: bool = False, force: bool = False) -> None:
        text = for_speech(text or "")
        if not text:
            return
        if not force and not self.settings.get("voice.spoken_replies", True):
            return
        if self._is_duplicate(text):
            log.debug("Fala repetida ignorada")
            return
        done = threading.Event() if wait else None
        self._queue.put(_Item(text, done=done, generation=self._generation))
        if done:
            done.wait(timeout=120)

    def _is_duplicate(self, text: str) -> bool:
        """A mesma frase já na fila, ou recém-iniciada, não é falada de novo."""
        import time

        with self._lock:
            queued = [i.text for i in list(self._queue.queue) if i is not None and i.generation == self._generation]
            if text in queued:
                return True
            return text == self._last_text and time.time() - self._last_started < 3.0

    def play_clip(self, clip: AudioClip, wait: bool = False) -> None:
        done = threading.Event() if wait else None
        self._queue.put(_Item("", clip=clip, done=done, generation=self._generation))
        if done:
            done.wait(timeout=30)

    def cue(self, kind: str = "listen") -> None:
        """Bipe opcional ao abrir o microfone (toca direto, sem fila)."""
        if not self.settings.get("audio.beep_on_listen", True):
            return
        volume = self.settings.get("audio.beep_volume", 35) / 100.0
        clip = beep(880, 90, volume=0.6, second=1320) if kind == "listen" else beep(660, 90, volume=0.6)
        threading.Thread(target=self.cue_player.play, args=(clip, volume), daemon=True).start()

    def stop(self) -> None:
        """Interrompe a fala atual e descarta a fila."""
        self._generation += 1
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item and item.done:
                item.done.set()
        self.player.stop()
        stream = self._current_stream
        if stream is not None:
            stream.close()  # interrompe o download do áudio em andamento

    def shutdown(self) -> None:
        self.stop()
        self._queue.put(None)

    def prewarm_async(self) -> None:
        phrases = []
        for profile in ("jarvis", "friday"):
            phrases += self.settings.get(f"profiles.{profile}.acks", []) or []
        phrases += ["Não entendi. Pode repetir?", "Cancelado. Nada foi feito.", "Feito."]
        threading.Thread(target=self.tts.prewarm, args=(list(dict.fromkeys(phrases)),), name="tts-prewarm",
                         daemon=True).start()

    # ------------------------------------------------------------ worker
    def _loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            try:
                if item.generation != self._generation:
                    continue
                self._speak_item(item)
            except Exception:  # noqa: BLE001
                log.exception("Erro na fila de fala")
            finally:
                if item.done:
                    item.done.set()

    def _speak_item(self, item: _Item) -> None:
        import time

        if item.clip is not None:
            self._play(item, clip=item.clip)
            return
        with self._lock:
            self._last_text, self._last_started = item.text, time.time()
        # 1. Fish Audio (voz principal): cache para frases curtas, streaming para o resto
        if self.tts.fish_ready():
            cached = self.tts.cached_clip("fish", item.text)
            if cached is not None:
                self._play(item, clip=cached)
                return
            try:
                stream = self.tts.fish.open_stream(item.text, self.tts.params())
            except TTSError as exc:
                self.tts.fish_failed(exc)  # cai para a voz reserva abaixo, sem atraso extra
            else:
                self.tts.fish_ok()
                self.tts.last_engine = "fish"
                self._play(item, stream=stream)
                return
        # 2. Voz reserva (neural Edge, Azure ou Windows)
        try:
            clip = self.tts.synthesize(item.text)
        except TTSError as exc:
            log.warning("Sem voz disponível: %s", exc)
            self.bus.publish("activity", text="Voz indisponível: " + str(exc)[:100], kind="error")
            return
        self._play(item, clip=clip)

    def _play(self, item: _Item, clip: AudioClip | None = None, stream=None) -> None:
        if item.generation != self._generation:
            if stream is not None:
                stream.close()
            return
        self.speaking.set()
        self.bus.publish("state", state="speaking")
        self.ducker.duck()
        try:
            if stream is not None:
                self._current_stream = stream
                collected: list = []
                keep = len(item.text) <= 160

                def chunks():
                    for chunk in stream.chunks():
                        if keep:
                            collected.append(chunk)
                        yield chunk

                finished = self.player.play_stream(chunks(), stream.rate)
                if finished and keep and collected:
                    import numpy as np

                    self.tts.save_cache("fish", item.text, AudioClip(np.concatenate(collected), stream.rate))
            else:
                self.player.play(clip)
        finally:
            if stream is not None:
                stream.close()
                self._current_stream = None
            self.ducker.restore()
            self.speaking.clear()
            if self._queue.empty():
                if self.on_idle:
                    self.on_idle()
                else:
                    self.bus.publish("state", state="idle")
