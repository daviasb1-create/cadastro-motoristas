"""Síntese de voz em português do Brasil com perfis JARVIS e FRIDAY.

Motores (escolha em Configurações > Voz):
* edge   Vozes neurais da Microsoft (pt-BR-AntonioNeural / pt-BR-FranciscaNeural)
         pelo pacote ``edge-tts``. Gratuito, alta qualidade, exige internet.
         Usa o serviço de leitura em voz alta do Edge, que não é uma API
         comercial oficial: pode mudar sem aviso; por isso há fallback.
* azure  Azure AI Speech (oficial, mesmas vozes neurais e controle SSML).
         Exige chave e região; nível gratuito com cota mensal.
* sapi   Vozes instaladas no Windows (Daniel/Maria). Offline, mais robóticas.
* auto   edge -> sapi, conforme disponibilidade.

As vozes originais dos filmes não são licenciadas para uso; os perfis usam
as vozes sintéticas mais próximas em estilo (grave e calmo / clara e
confiante), sem prometer reprodução idêntica.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import sys
import tempfile
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np

from ..core import paths

log = logging.getLogger(__name__)


@dataclass
class AudioClip:
    samples: np.ndarray  # int16 mono
    rate: int

    @property
    def seconds(self) -> float:
        return len(self.samples) / float(self.rate or 1)

    def to_wav(self) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.rate)
            wav.writeframes(self.samples.astype(np.int16).tobytes())
        return buffer.getvalue()

    @classmethod
    def from_wav(cls, data: bytes) -> "AudioClip":
        with wave.open(io.BytesIO(data), "rb") as wav:
            frames = wav.readframes(wav.getnframes())
            rate, channels, width = wav.getframerate(), wav.getnchannels(), wav.getsampwidth()
        if width != 2:
            raise ValueError("WAV precisa ser 16 bits")
        samples = np.frombuffer(frames, dtype=np.int16)
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1).astype(np.int16)
        return cls(samples.copy(), rate)


class TTSError(Exception):
    pass


@dataclass
class VoiceParams:
    profile: str
    voice: str
    pitch: str
    rate: int  # -50..50 (%)
    sapi_hint: str


class EdgeEngine:
    name = "edge"

    def synthesize(self, text: str, p: VoiceParams) -> AudioClip:
        try:
            import edge_tts
            import miniaudio
        except ImportError as exc:
            raise TTSError("edge-tts/miniaudio não instalados") from exc

        async def collect() -> bytes:
            communicate = edge_tts.Communicate(text, p.voice, rate=f"{p.rate:+d}%", pitch=p.pitch,
                                               connect_timeout=5, receive_timeout=20)
            chunks = []
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio":
                    chunks.append(chunk["data"])
            return b"".join(chunks)

        try:
            mp3 = asyncio.run(collect())
        except Exception as exc:  # noqa: BLE001 - rede/serviço
            raise TTSError(f"Voz online indisponível: {exc}") from exc
        if not mp3:
            raise TTSError("Voz online não retornou áudio")
        decoded = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=24000)
        return AudioClip(np.frombuffer(decoded.samples, dtype=np.int16).copy(), 24000)


class AzureEngine:
    name = "azure"

    def __init__(self, secrets, settings) -> None:
        self.secrets = secrets
        self.settings = settings

    def synthesize(self, text: str, p: VoiceParams) -> AudioClip:
        import httpx

        key = self.secrets.get("azure_speech_key")
        if not key:
            raise TTSError("Chave do Azure Speech não configurada")
        region = self.settings.get("voice.azure_region", "brazilsouth")
        voice = self.settings.get(f"profiles.{p.profile}.azure_voice", p.voice)
        ssml = (f"<speak version='1.0' xml:lang='pt-BR'><voice name='{voice}'>"
                f"<prosody rate='{p.rate:+d}%' pitch='{p.pitch}'>{escape(text)}</prosody></voice></speak>")
        try:
            response = httpx.post(
                f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1", content=ssml.encode("utf-8"),
                headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/ssml+xml",
                         "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm", "User-Agent": "Jarvis"},
                timeout=15)
        except httpx.HTTPError as exc:
            raise TTSError("Azure Speech sem conexão") from exc
        if response.status_code != 200:
            raise TTSError(f"Azure Speech erro {response.status_code}")
        return AudioClip.from_wav(response.content)


class SapiEngine:
    """Vozes do Windows via SAPI (inclui vozes OneCore como Daniel e Maria)."""

    name = "sapi"
    ONECORE = r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices"

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def voices(self) -> list[tuple[str, object]]:
        import comtypes.client  # type: ignore

        found = []
        voice = comtypes.client.CreateObject("SAPI.SpVoice")
        tokens = list(voice.GetVoices())
        try:
            category = comtypes.client.CreateObject("SAPI.SpObjectTokenCategory")
            category.SetId(self.ONECORE, False)
            tokens += list(category.EnumerateTokens())
        except Exception:  # noqa: BLE001
            pass
        for token in tokens:
            found.append((token.GetDescription(), token))
        return found

    def synthesize(self, text: str, p: VoiceParams) -> AudioClip:
        if sys.platform != "win32":
            raise TTSError("SAPI só existe no Windows")
        import comtypes  # type: ignore
        import comtypes.client  # type: ignore

        with self._lock:
            try:
                comtypes.CoInitialize()
            except OSError:
                pass
            voice = comtypes.client.CreateObject("SAPI.SpVoice")
            chosen = None
            for description, token in self.voices():
                desc = description.lower()
                if p.sapi_hint.lower() in desc and ("portug" in desc or "brazil" in desc or "brasil" in desc):
                    chosen = token
                    break
            if chosen is None:
                for description, token in self.voices():
                    if "portug" in description.lower() or "brazil" in description.lower():
                        chosen = token
                        break
            if chosen is not None:
                voice.Voice = chosen
            voice.Rate = max(-10, min(10, round(p.rate / 5)))
            tmp = Path(tempfile.gettempdir()) / f"jarvis_sapi_{threading.get_ident()}.wav"
            stream = comtypes.client.CreateObject("SAPI.SpFileStream")
            stream.Open(str(tmp), 3)  # SSFMCreateForWrite
            voice.AudioOutputStream = stream
            voice.Speak(text)
            stream.Close()
            data = tmp.read_bytes()
            tmp.unlink(missing_ok=True)
        return AudioClip.from_wav(data)


class TTSManager:
    def __init__(self, settings, secrets, bus=None, fish_transport=None) -> None:
        from .fish import FishAudioEngine

        self.settings = settings
        self.bus = bus
        self.fish = FishAudioEngine(settings, transport=fish_transport)
        self.engines = {"fish": self.fish, "edge": EdgeEngine(), "azure": AzureEngine(secrets, settings),
                        "sapi": SapiEngine()}
        self._cache_dir = paths.cache_dir() / "tts"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self.last_engine = ""
        self._edge_failed_at = 0.0
        self._fish_blocked_until = 0.0
        self.fish_last_error = ""

    def params(self, profile: str | None = None) -> VoiceParams:
        profile = profile or self.settings.get("voice.profile", "jarvis")
        prof = self.settings.get(f"profiles.{profile}", {}) or {}
        return VoiceParams(profile=profile, voice=prof.get("edge_voice", "pt-BR-AntonioNeural"),
                           pitch=prof.get("edge_pitch", "+0Hz"), rate=int(self.settings.get("voice.rate", 0)),
                           sapi_hint=prof.get("sapi_hint", "Daniel"))

    # --------------------------------------------------------- Fish Audio
    def fish_ready(self, profile: str | None = None) -> bool:
        import time

        profile = profile or self.settings.get("voice.profile", "jarvis")
        return (self.settings.get("voice.engine", "auto") in ("auto", "fish") and self.fish.configured(profile)
                and time.time() >= self._fish_blocked_until)

    def fish_failed(self, error: Exception) -> None:
        """Pausa a Fish Audio por um tempo e avisa uma vez; as falas seguem pela voz reserva."""
        import time

        status = getattr(error, "status", 0)
        pause = 600 if status in (401, 402, 403, 404, 422) else int(self.settings.get("fish.retry_seconds", 60))
        self._fish_blocked_until = time.time() + pause
        message = str(error)
        log.warning("Fish Audio indisponível: %s", message)
        if message != self.fish_last_error and self.bus is not None:
            self.bus.publish("activity", text=f"Voz Fish Audio indisponível ({message}). Usando a voz reserva.",
                             kind="error")
            self.bus.publish("connection", service="voice", status="error", detail=message[:80])
        self.fish_last_error = message

    def fish_ok(self) -> None:
        if self.fish_last_error and self.bus is not None:
            self.bus.publish("connection", service="voice", status="ok", detail="Fish Audio")
        self.fish_last_error = ""

    def cached_clip(self, engine: str, text: str, profile: str | None = None) -> AudioClip | None:
        path = self._cache_path(engine, text, self.params(profile))
        if path.exists():
            try:
                return AudioClip.from_wav(path.read_bytes())
            except (OSError, ValueError, EOFError):
                path.unlink(missing_ok=True)
        return None

    def save_cache(self, engine: str, text: str, clip: AudioClip, profile: str | None = None) -> None:
        if len(text) > 160:
            return
        try:
            self._cache_path(engine, text, self.params(profile)).write_bytes(clip.to_wav())
        except OSError:
            pass

    def order(self) -> list[str]:
        choice = self.settings.get("voice.engine", "auto")
        fish = ["fish"] if self.fish_ready() else []
        if choice == "fish":
            return fish + ["edge", "sapi"]
        if choice == "auto":
            import time

            # Depois de uma falha da voz online, usa a local por 2 minutos (sem atrasar respostas)
            if time.time() - self._edge_failed_at < 120:
                return fish + ["sapi", "edge"]
            return fish + ["edge", "sapi"]
        return [choice] + [e for e in ("edge", "sapi") if e != choice]

    def _cache_path(self, engine: str, text: str, p: VoiceParams) -> Path:
        extra = ""
        if engine == "fish":
            extra = (f"|{self.fish.reference_id(p.profile)}|{self.settings.get('fish.model', '')}"
                     f"|{self.settings.get('fish.volume_db', 0)}")
        digest = hashlib.sha1(f"{engine}|{p.voice}|{p.pitch}|{p.rate}|{p.sapi_hint}{extra}|{text}".encode()).hexdigest()
        return self._cache_dir / f"{digest}.wav"

    def synthesize(self, text: str, profile: str | None = None, cache: bool | None = None) -> AudioClip:
        import time

        p = self.params(profile)
        use_cache = cache if cache is not None else len(text) <= 160
        errors = []
        for name in self.order():
            path = self._cache_path(name, text, p)
            if use_cache and path.exists():
                try:
                    self.last_engine = name
                    return AudioClip.from_wav(path.read_bytes())
                except (OSError, ValueError, EOFError):
                    path.unlink(missing_ok=True)
            try:
                clip = self.engines[name].synthesize(text, p)
            except TTSError as exc:
                errors.append(f"{name}: {exc}")
                if name == "edge":
                    self._edge_failed_at = time.time()
                if name == "fish":
                    self.fish_failed(exc)
                continue
            except Exception as exc:  # noqa: BLE001
                log.exception("Falha no motor de voz %s", name)
                errors.append(f"{name}: {exc}")
                continue
            self.last_engine = name
            if name == "fish":
                self.fish_ok()
            if use_cache:
                try:
                    path.write_bytes(clip.to_wav())
                except OSError:
                    pass
            return clip
        raise TTSError("; ".join(errors) or "Nenhum motor de voz disponível")

    def prewarm(self, phrases: list[str]) -> None:
        """Pré-gera frases curtas (confirmações) para resposta instantânea."""
        for profile in ("jarvis", "friday"):
            for phrase in phrases or []:
                try:
                    self.synthesize(phrase, profile=profile, cache=True)
                except TTSError:
                    return

    def clear_cache(self) -> None:
        for file in self._cache_dir.glob("*.wav"):
            file.unlink(missing_ok=True)
