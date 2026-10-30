"""Voz do JARVIS pela Fish Audio (API oficial, com streaming).

* Endpoint: POST https://api.fish.audio/v1/tts, cabeçalho ``model`` (ex.: s2.1-pro),
  corpo com ``text``, ``reference_id`` (ID da voz escolhida), ``format`` e ``prosody``.
* O áudio é pedido em WAV e tocado enquanto chega (streaming): o cabeçalho WAV informa
  taxa e canais; os dados PCM seguem direto para o alto-falante.
* A chave fica em FISH_AUDIO_API_KEY no arquivo .env (nunca na interface nem em log).
* Falhas (sem internet, sem créditos, chave ou ID inválidos) viram TTSError com motivo
  claro; o gerenciador de vozes cai para a voz reserva.
"""
from __future__ import annotations

import logging
import os
import struct
import threading
from typing import Iterator

import httpx
import numpy as np

from .tts import AudioClip, TTSError, VoiceParams

log = logging.getLogger(__name__)

API_URL = "https://api.fish.audio"
ENV_KEY = "FISH_AUDIO_API_KEY"
DEFAULT_MODEL = "s2.1-pro"
FREE_MODEL = "s2.1-pro-free"  # nível gratuito para desenvolvedores (usado quando a conta está sem créditos)
SAMPLE_RATE = 44100


class FishError(TTSError):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def error_message(status: int, detail: str = "") -> str:
    if status == 401:
        return "chave da Fish Audio inválida (confira FISH_AUDIO_API_KEY no .env)"
    if status == 402:
        return "sem créditos na conta Fish Audio"
    if status == 403:
        return "a conta Fish Audio não tem acesso a esse modelo ou voz"
    if status in (400, 404, 422):
        return f"pedido recusado pela Fish Audio (verifique o ID da voz e o modelo){': ' + detail[:120] if detail else ''}"
    if status == 429:
        return "limite de uso da Fish Audio atingido"
    if status >= 500:
        return f"Fish Audio indisponível no momento (erro {status})"
    return f"erro {status} da Fish Audio"


class WavStreamParser:
    """Lê um WAV que chega em pedaços: interpreta o cabeçalho e devolve amostras int16 mono."""

    def __init__(self, fallback_rate: int = SAMPLE_RATE) -> None:
        self._buffer = b""
        self._in_data = False
        self.rate = 0
        self.channels = 1
        self.bits = 16
        self._fallback_rate = fallback_rate
        self._raw = False

    @property
    def ready(self) -> bool:
        return self._in_data

    def feed(self, chunk: bytes) -> np.ndarray | None:
        self._buffer += chunk
        if not self._in_data and not self._parse_header():
            return None
        frame = self.channels * (self.bits // 8)
        usable = len(self._buffer) - (len(self._buffer) % frame)
        if usable <= 0:
            return None
        data, self._buffer = self._buffer[:usable], self._buffer[usable:]
        samples = np.frombuffer(data, dtype=np.int16 if self.bits == 16 else np.int32)
        if self.bits == 32:
            samples = (samples >> 16).astype(np.int16)
        if self.channels > 1:
            samples = samples.reshape(-1, self.channels).mean(axis=1).astype(np.int16)
        return samples

    def _parse_header(self) -> bool:
        buf = self._buffer
        if len(buf) < 12:
            return False
        if buf[:4] != b"RIFF" or buf[8:12] != b"WAVE":
            # resposta sem cabeçalho: trata como PCM 16 bits mono na taxa pedida
            self._raw, self._in_data, self.rate = True, True, self._fallback_rate
            return True
        pos = 12
        while pos + 8 <= len(buf):
            chunk_id = buf[pos:pos + 4]
            size = struct.unpack_from("<I", buf, pos + 4)[0]
            if chunk_id == b"data":
                self._buffer = buf[pos + 8:]
                self._in_data = True
                self.rate = self.rate or self._fallback_rate
                return True
            if pos + 8 + size > len(buf):
                return False  # chunk ainda incompleto
            if chunk_id == b"fmt ":
                fmt, channels, rate = struct.unpack_from("<HHI", buf, pos + 8)
                bits = struct.unpack_from("<H", buf, pos + 22)[0]
                if fmt not in (1, 0xFFFE) or bits not in (16, 32):
                    raise FishError(f"formato de áudio inesperado (fmt={fmt}, bits={bits})")
                self.channels, self.rate, self.bits = channels, rate, bits
            pos += 8 + size + (size % 2)
        return False


class FishStream:
    """Requisição em andamento: ``rate`` fica disponível após ``start()``; ``chunks()`` entrega o áudio."""

    def __init__(self, engine: "FishAudioEngine", text: str, p: VoiceParams) -> None:
        self.engine = engine
        self.text = text
        self.params = p
        self.parser = WavStreamParser()
        self.rate = 0
        self._response = None
        self._context = None
        self._iterator: Iterator[bytes] | None = None
        self._pending: list[np.ndarray] = []
        self._closed = threading.Event()

    def start(self) -> "FishStream":
        """Abre a conexão e lê até o início do áudio. Erros aqui permitem usar a voz reserva."""
        engine = self.engine
        try:
            self._context = engine.client.stream("POST", "/v1/tts", headers=engine.headers(),
                                                 content=engine.body(self.text, self.params))
            self._response = self._context.__enter__()
        except httpx.HTTPError as exc:
            raise FishError(f"sem conexão com a Fish Audio ({type(exc).__name__})") from exc
        if self._response.status_code != 200:
            detail = ""
            try:
                detail = self._response.read().decode("utf-8", "ignore")
            except Exception:  # noqa: BLE001
                pass
            status = self._response.status_code
            self.close()
            raise FishError(error_message(status, detail), status)
        self._iterator = self._response.iter_bytes()
        try:
            for chunk in self._iterator:
                samples = self.parser.feed(chunk)
                if samples is not None and len(samples):
                    self._pending.append(samples)
                if self.parser.ready and self._pending:
                    break
        except httpx.HTTPError as exc:
            self.close()
            raise FishError(f"a conexão com a Fish Audio caiu ({type(exc).__name__})") from exc
        if not self.parser.ready:
            self.close()
            raise FishError("a Fish Audio não retornou áudio")
        self.rate = self.parser.rate
        return self

    def chunks(self) -> Iterator[np.ndarray]:
        try:
            while self._pending:
                yield self._pending.pop(0)
            if self._iterator is None:
                return
            for chunk in self._iterator:
                if self._closed.is_set():
                    return
                samples = self.parser.feed(chunk)
                if samples is not None and len(samples):
                    yield samples
        except httpx.HTTPError as exc:
            log.warning("Streaming da Fish Audio interrompido: %s", type(exc).__name__)
        finally:
            self.close()

    def close(self) -> None:
        """Encerra a conexão (usado também para interromper a fala no meio).

        Pode ser chamado de outra thread: marca o fechamento e a thread que lê o áudio
        conclui o encerramento ao receber o próximo pedaço (chamadas repetidas são seguras)."""
        self._closed.set()
        iterator = self._iterator
        if iterator is not None and hasattr(iterator, "close"):
            try:
                iterator.close()  # interrompe o download em andamento
            except Exception:  # noqa: BLE001
                pass
        if self._response is not None:
            try:
                self._response.close()
            except Exception:  # noqa: BLE001
                pass
        if self._context is not None:
            try:
                self._context.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass


class FishAudioEngine:
    name = "fish"

    def __init__(self, settings, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self._model_override = ""
        self.client = httpx.Client(base_url=API_URL, transport=transport,
                                   timeout=httpx.Timeout(30.0, connect=6.0, read=20.0))

    # ------------------------------------------------------------ config
    @property
    def api_key(self) -> str:
        return os.environ.get(ENV_KEY, "").strip()

    def reference_id(self, profile: str) -> str:
        return (self.settings.get(f"profiles.{profile}.fish_reference_id", "") or "").strip()

    def configured(self, profile: str) -> bool:
        return bool(self.api_key and self.reference_id(profile) and self.settings.get("fish.enabled", True))

    def headers(self) -> dict[str, str]:
        if not self.api_key:
            raise FishError(f"chave {ENV_KEY} não encontrada no arquivo .env")
        return {"Authorization": f"Bearer {self.api_key}", "model": self.model,
                "Content-Type": "application/msgpack" if _msgpack() else "application/json"}

    def payload(self, text: str, p: VoiceParams) -> dict:
        speed = max(0.5, min(2.0, 1.0 + int(p.rate) / 100.0))
        volume_db = max(-20.0, min(20.0, float(self.settings.get("fish.volume_db", 0) or 0)))
        return {
            "text": text,
            "reference_id": self.reference_id(p.profile),
            "format": "wav",
            "sample_rate": SAMPLE_RATE,
            "latency": self.settings.get("fish.latency", "balanced"),
            "normalize": True,
            "prosody": {"speed": round(speed, 2), "volume": volume_db},
        }

    def body(self, text: str, p: VoiceParams) -> bytes:
        payload = self.payload(text, p)
        packer = _msgpack()
        if packer is not None:
            return packer.packb(payload)
        import json

        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    # ------------------------------------------------------------- uso
    @property
    def model(self) -> str:
        """Modelo em uso: o configurado ou, se a conta ficou sem créditos, o gratuito."""
        return self._model_override or self.settings.get("fish.model", DEFAULT_MODEL) or DEFAULT_MODEL

    def open_stream(self, text: str, p: VoiceParams) -> FishStream:
        if not self.reference_id(p.profile):
            raise FishError("ID da voz Fish Audio não configurado para este perfil")
        try:
            return FishStream(self, text, p).start()
        except FishError as exc:
            free = self.settings.get("fish.free_model", FREE_MODEL)
            if exc.status != 402 or not free or self.model == free or not self.settings.get("fish.use_free_when_no_credits", True):
                raise
            # Sem créditos no modelo pago: tenta o modelo gratuito e passa a usá-lo nesta sessão
            log.warning("Fish Audio sem créditos para %s; tentando %s", self.model, free)
            self._model_override = free
            try:
                return FishStream(self, text, p).start()
            except FishError:
                self._model_override = ""
                raise

    def synthesize(self, text: str, p: VoiceParams) -> AudioClip:
        """Gera o áudio completo (usado para frases curtas em cache e testes)."""
        stream = self.open_stream(text, p)
        parts = list(stream.chunks())
        if not parts:
            raise FishError("a Fish Audio não retornou áudio")
        return AudioClip(np.concatenate(parts), stream.rate)

    def check_voice(self, reference_id: str) -> dict:
        """Consulta a voz pelo ID (GET /model/{id}). Usado no teste de configuração."""
        if not self.api_key:
            raise FishError(f"chave {ENV_KEY} não encontrada no arquivo .env")
        try:
            response = self.client.get(f"/model/{reference_id}", headers={"Authorization": f"Bearer {self.api_key}"})
        except httpx.HTTPError as exc:
            raise FishError(f"sem conexão com a Fish Audio ({type(exc).__name__})") from exc
        if response.status_code != 200:
            raise FishError(error_message(response.status_code, response.text), response.status_code)
        data = response.json()
        return {"id": data.get("_id") or data.get("id") or reference_id, "title": data.get("title", ""),
                "state": data.get("state", ""), "languages": data.get("languages", [])}


def _msgpack():
    try:
        import ormsgpack  # type: ignore

        return ormsgpack
    except ImportError:
        return None
