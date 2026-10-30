"""Ciclo de voz: palavra de ativação -> captura do comando -> resposta.

Estados publicados no barramento (``state``):
  idle        aguardando "Jarvis" (detecção local)
  listening   capturando o comando
  processing  interpretando/executando
  speaking    falando (publicado pelo Speaker)
  sleeping    em espera: só reage a "Jarvis, acorda"
  suspended   microfone desligado

Comportamentos:
* "Jarvis" sozinho -> resposta instantânea ("Às suas ordens", pré-gerada).
* "Jarvis, abre o navegador" numa frase só -> sem pausa: o áudio anterior à
  detecção (pré-roll) entra no reconhecimento e a palavra é removida do texto.
* Chamar "Jarvis" enquanto ele fala interrompe a fala na hora.
* Após uma pergunta do assistente (ex.: confirmação), o microfone reabre por
  alguns segundos sem precisar da palavra de ativação.
"""
from __future__ import annotations

import collections
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from ..audio.vad import EnergyVAD
from ..brain import responses
from ..nlu.normalize import normalize, strip_wake_words

log = logging.getLogger(__name__)
FRAME_SECONDS = 0.05


class VoicePipeline:
    def __init__(self, settings, bus, state, speaker, mic, wake_factory: Callable[[], object],
                 stt, handler: Callable[[str, float, str], object]) -> None:
        self.settings = settings
        self.bus = bus
        self.state = state
        self.speaker = speaker
        self.mic = mic
        self.wake_factory = wake_factory
        self.stt = stt
        self.handler = handler  # (texto, confiança, origem) -> Reply
        self.vad = EnergyVAD(gate=float(settings.get("audio.noise_gate", 1.0)))
        self.wake = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="command")
        self._preroll: collections.deque[bytes] = collections.deque()
        self._trigger = threading.Event()
        self._trigger_source = "manual"
        self._follow_up_at: float | None = None
        self._mic_enabled = True
        self._sleeping = False
        self._last_level_pub = 0.0
        self._hangover = 0
        self._calibration: list[str] | None = None
        self.on_calibrated: Callable[[list[str]], None] | None = None
        self.mode = "idle"

    # ---------------------------------------------------------------- API
    def start(self) -> None:
        self.wake = self.wake_factory()
        self._thread = threading.Thread(target=self._run, name="voice", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._executor.shutdown(wait=False, cancel_futures=True)
        try:
            self.mic.close()
        except Exception:  # noqa: BLE001
            pass

    def trigger(self, source: str = "manual") -> None:
        """Ativação sem palavra (atalho de teclado, botão do controle, botão da tela)."""
        self._trigger_source = source
        self._trigger.set()

    def set_mic_enabled(self, enabled: bool) -> None:
        self._mic_enabled = enabled
        self.state.mic_enabled = enabled
        self._publish_state()

    def set_sleeping(self, sleeping: bool) -> None:
        self._sleeping = sleeping
        self.state.sleeping = sleeping
        self._publish_state()

    def request_follow_up(self, delay: float = 0.0) -> None:
        self._follow_up_at = time.time() + delay

    def reload_wake(self) -> None:
        try:
            self.wake = self.wake_factory()
        except Exception:  # noqa: BLE001
            log.exception("Falha ao recarregar detector de ativação")

    def _publish_state(self, mode: str | None = None) -> None:
        if mode:
            self.mode = mode
        if not self._mic_enabled:
            state = "suspended"
        elif self._sleeping and self.mode == "idle":
            state = "sleeping"
        else:
            state = self.mode
        self.bus.publish("state", state=state)

    # --------------------------------------------------------------- laço
    def _run(self) -> None:
        mic_open = False
        self._publish_state("idle")
        while not self._stop.is_set():
            if not self._mic_enabled:
                if mic_open:
                    self.mic.close()
                    mic_open = False
                if self._trigger.wait(0.3):
                    self._trigger.clear()  # com microfone desligado, gatilhos só religam pela interface
                continue
            if not mic_open:
                mic_open = self.mic.open()
                if not mic_open:
                    self.bus.publish("connection", service="microphone", status="error",
                                     detail="Microfone indisponível")
                    self._stop.wait(5)
                    continue
                self.bus.publish("connection", service="microphone", status="ok", detail="Microfone ativo")
            if self._trigger.is_set():
                self._trigger.clear()
                self._on_wake(self._trigger_source)
                continue
            if self._follow_up_at and time.time() >= self._follow_up_at and not self.speaker.speaking.is_set():
                self._follow_up_at = None
                self._capture("follow_up", listen_timeout=float(self.settings.get("wake.follow_up_seconds", 6)))
                continue
            frame = self.mic.read(timeout=0.3)
            if frame is None:
                continue
            self._remember(frame)
            speech = self.vad.is_speech(frame)
            self._publish_level()
            if speech:
                self._hangover = 10  # 0,5 s após o fim da fala
            elif self._hangover:
                self._hangover -= 1
            else:
                continue  # silêncio: o detector nem roda (economia de CPU)
            if self.wake is not None and self.wake.process(frame):
                self._on_wake("voice")

    def _remember(self, frame: bytes) -> None:
        self._preroll.append(frame)
        limit = int(float(self.settings.get("wake.preroll_seconds", 1.2)) / FRAME_SECONDS)
        while len(self._preroll) > limit:
            self._preroll.popleft()

    def _publish_level(self) -> None:
        now = time.time()
        if now - self._last_level_pub >= 0.1:
            self._last_level_pub = now
            self.bus.publish("audio_level", level=self.vad.normalized_level())

    # --------------------------------------------------------- ativação
    def _on_wake(self, source: str) -> None:
        log.info("Ativação (%s)", source)
        if self.speaker.speaking.is_set():
            self.speaker.stop()  # interrompe a fala imediatamente
        if self.wake is not None:
            self.wake.reset()
        self._capture(source, listen_timeout=float(self.settings.get("wake.listen_timeout", 6)))

    def _capture(self, source: str, listen_timeout: float) -> None:
        settings = self.settings
        self._publish_state("listening")
        ack_mode = settings.get("wake.ack_mode", "voice")
        session = self.stt.session()
        variants = (settings.get("wake.variants", []) or []) + (settings.get("wake.words", []) or [])
        if source == "voice":
            for frame in self._preroll:
                session.feed(frame)
        self._preroll.clear()
        if source != "voice" or ack_mode in ("beep", "both"):
            self.speaker.cue("listen")
        started = time.time()
        wait_started = started
        last_voice = started
        heard_command = False
        acked = source != "voice"  # gatilho manual e follow-up não precisam de "Às suas ordens"
        end_silence = float(settings.get("wake.end_silence_ms", 900)) / 1000.0
        max_seconds = float(settings.get("wake.command_max_seconds", 12))
        while not self._stop.is_set():
            frame = self.mic.read(timeout=0.3)
            now = time.time()
            if frame is not None:
                session.feed(frame)
                if self.vad.is_speech(frame):
                    last_voice = now
                    if now - started > 0.25:
                        heard_command = heard_command or bool(strip_wake_words(normalize(session.partial()), variants))
                self._publish_level()
            command_text = strip_wake_words(normalize(session.partial()), variants)
            if command_text:
                heard_command = True
            if not acked and not heard_command and now - started > 0.7 and now - last_voice > 0.45:
                acked = True
                if ack_mode in ("voice", "both"):
                    self.speaker.say(responses.ack(settings), wait=True, force=True)
                    self.mic.drain()  # descarta o eco da própria fala
                    session = self.stt.session()
                    if ack_mode == "both":
                        self.speaker.cue("listen")
                wait_started = time.time()
                last_voice = wait_started
                continue
            if heard_command and now - last_voice >= end_silence:
                break
            if not heard_command and acked and now - wait_started >= listen_timeout:
                break
            if now - started >= max_seconds + (listen_timeout if acked else 0):
                break
        text, confidence = session.result()
        if self._calibration is not None:
            if text:
                self._calibration.append(text)
            self._publish_state("idle")
            return
        text = self._clean(text, variants)
        self._publish_state("processing" if text else "idle")
        if not text:
            if acked and source == "voice":
                log.info("Nenhum comando após a ativação")
            self._publish_state("idle")
            return
        if self._sleeping and not re.search(r"\b(acorda|acorde|desperta|reativa|volta)\b", normalize(text)):
            self._publish_state("idle")
            return
        self._executor.submit(self._dispatch, text, confidence)

    @staticmethod
    def _clean(text: str, variants: list[str]) -> str:
        words = text.split()
        normalized_variants = {normalize(v) for v in variants}
        while words and normalize(words[0]) in normalized_variants:
            words.pop(0)
        return " ".join(words).strip()

    def _dispatch(self, text: str, confidence: float) -> None:
        try:
            reply = self.handler(text, confidence, "voice")
        except Exception:  # noqa: BLE001
            log.exception("Falha ao processar comando")
            self.speaker.say("Tive um problema ao executar isso. Os detalhes estão no registro.")
            self._publish_state("idle")
            return
        if reply is not None and getattr(reply, "speak", True) and reply.text:
            self.speaker.say(reply.text)
        if reply is not None and getattr(reply, "expects_reply", False):
            # espera a fala terminar antes de reabrir o microfone
            threading.Thread(target=self._follow_up_after_speech, daemon=True).start()
        self._publish_state("idle")

    def _follow_up_after_speech(self) -> None:
        time.sleep(0.3)
        deadline = time.time() + 60
        while (self.speaker.speaking.is_set() or not self.speaker._queue.empty()) and time.time() < deadline:
            time.sleep(0.1)
        self.request_follow_up(0.2)

    # -------------------------------------------------------- calibração
    def calibrate(self, rounds: int = 3, on_progress: Callable[[str], None] | None = None) -> list[str]:
        """Pede para o usuário dizer "Jarvis" algumas vezes e aprende como o modelo
        transcreve a pronúncia dele. As variantes novas são salvas nas configurações."""
        heard: list[str] = []
        self._calibration = heard
        try:
            for index in range(rounds):
                if on_progress:
                    on_progress(f"Diga \"Jarvis\" ({index + 1}/{rounds})")
                before = len(heard)
                self.trigger("calibration")
                deadline = time.time() + 8
                while len(heard) == before and time.time() < deadline:
                    time.sleep(0.1)
        finally:
            self._calibration = None
        words = set()
        for text in heard:
            tokens = normalize(text).split()
            if tokens:
                words.add(tokens[0] if len(tokens) == 1 else " ".join(tokens[:2]) if len(tokens[0]) <= 3 else tokens[0])
        if words:
            variants = list(dict.fromkeys((self.settings.get("wake.variants", []) or []) + sorted(words)))
            self.settings.set("wake.variants", variants)
            self.reload_wake()
            if self.on_calibrated:
                self.on_calibrated(sorted(words))
        return sorted(words)
