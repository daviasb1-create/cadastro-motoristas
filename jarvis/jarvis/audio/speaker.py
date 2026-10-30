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
        self.tts = TTSManager(settings, secrets)
        self.player = Player(settings)
        self.cue_player = Player(settings)  # separado: um bipe não pode anular o "parar" da fala
        self.on_idle = None  # o ciclo de voz republica o próprio estado ao terminar de falar
        self.ducker = Ducker(settings, state)
        self._queue: queue.Queue[_Item | None] = queue.Queue()
        self._generation = 0
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
        done = threading.Event() if wait else None
        self._queue.put(_Item(text, done=done, generation=self._generation))
        if done:
            done.wait(timeout=120)

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
                clip = item.clip
                if clip is None:
                    try:
                        clip = self.tts.synthesize(item.text)
                    except TTSError as exc:
                        log.warning("Sem voz disponível: %s", exc)
                        self.bus.publish("activity", text="Voz indisponível: " + str(exc)[:100], kind="error")
                        continue
                if item.generation != self._generation:
                    continue
                self.speaking.set()
                self.bus.publish("state", state="speaking")
                self.ducker.duck()
                try:
                    self.player.play(clip)
                finally:
                    self.ducker.restore()
                    self.speaking.clear()
                    if self._queue.empty():
                        if self.on_idle:
                            self.on_idle()
                        else:
                            self.bus.publish("state", state="idle")
            except Exception:  # noqa: BLE001
                log.exception("Erro na fila de fala")
            finally:
                if item.done:
                    item.done.set()
