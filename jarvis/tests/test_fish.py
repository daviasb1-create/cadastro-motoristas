"""Fish Audio: requisição, streaming WAV, fala automática, interrupção, repetição, reserva e teste do ID."""
import io
import struct
import threading
import time
import wave

import httpx
import numpy as np
import ormsgpack
import pytest

from jarvis.audio.fish import FishAudioEngine, WavStreamParser
from jarvis.audio.fish_check import check_fish_voice
from jarvis.audio.tts import AudioClip, VoiceParams
from jarvis.core.config import Settings
from jarvis.core.envfile import load_env, parse_env
from jarvis.core.events import EventBus

VOICE_ID = "a5b93aeddcc948c19ea04f0afe9d178c"


def wav_bytes(seconds=0.5, rate=44100, channels=1, extra_chunk=False):
    t = np.arange(int(rate * seconds)) / rate
    tone = (np.sin(2 * np.pi * 300 * t) * 12000).astype(np.int16)
    if channels == 2:
        tone = np.column_stack([tone, tone]).ravel()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(tone.tobytes())
    data = buf.getvalue()
    if extra_chunk:  # insere um bloco LIST antes de "data", como alguns servidores fazem
        pos = data.index(b"data")
        lst = b"LIST" + struct.pack("<I", 4) + b"INFO"
        data = data[:pos] + lst + data[pos:]
    return data


def split_irregular(data, sizes=(7, 33, 1, 500, 3)):
    out, i, k = [], 0, 0
    while i < len(data):
        n = sizes[k % len(sizes)]
        out.append(data[i:i + n])
        i += n
        k += 1
    return out


@pytest.fixture
def settings(home, monkeypatch):
    monkeypatch.setenv("FISH_AUDIO_API_KEY", "fa-test-key")
    return Settings(home / "s.json")


def test_defaults_use_selected_voice_and_model(settings):
    assert settings.get("profiles.jarvis.fish_reference_id") == VOICE_ID
    assert settings.get("fish.model") == "s2.1-pro"


def test_request_shape(settings):
    seen = {}

    def handler(request):
        seen["headers"] = request.headers
        seen["body"] = ormsgpack.unpackb(request.content)
        return httpx.Response(200, content=iter(split_irregular(wav_bytes(0.2))))

    settings.set("voice.rate", -20)
    engine = FishAudioEngine(settings, transport=httpx.MockTransport(handler))
    clip = engine.synthesize("Bom dia.", VoiceParams("jarvis", "", "+0Hz", -20, ""))
    assert clip.rate == 44100 and abs(clip.seconds - 0.2) < 0.01
    assert seen["headers"]["authorization"] == "Bearer fa-test-key"
    assert seen["headers"]["model"] == "s2.1-pro"
    assert seen["headers"]["content-type"] == "application/msgpack"
    body = seen["body"]
    assert body["reference_id"] == VOICE_ID and body["format"] == "wav" and body["text"] == "Bom dia."
    assert body["prosody"] == {"speed": 0.8, "volume": 0.0}


@pytest.mark.parametrize("channels,extra", [(1, False), (2, False), (1, True)])
def test_wav_stream_parser(channels, extra):
    data = wav_bytes(0.3, rate=24000, channels=channels, extra_chunk=extra)
    parser = WavStreamParser()
    samples = [s for chunk in split_irregular(data) if (s := parser.feed(chunk)) is not None]
    assert parser.rate == 24000 and parser.ready
    assert len(np.concatenate(samples)) == int(24000 * 0.3)


class FakePlayer:
    def __init__(self):
        self.streamed = []
        self.clips = []
        self._stop = threading.Event()

    def play_stream(self, chunks, rate, volume=None):
        self._stop.clear()
        for chunk in chunks:
            if self._stop.is_set():
                return False
            self.streamed.append(len(chunk))
            time.sleep(0.01)
        return not self._stop.is_set()

    def play(self, clip, volume=None):
        self.clips.append(clip)
        return True

    def stop(self):
        self._stop.set()


def make_speaker(settings, handler, monkeypatch):
    from jarvis.audio import speaker as speaker_mod
    from jarvis.brain.services import RuntimeState

    bus = EventBus()
    events = []
    bus.subscribe("activity", events.append)
    spk = speaker_mod.Speaker(settings, bus, RuntimeState(), secrets=None)
    spk.player = FakePlayer()
    engine = FishAudioEngine(settings, transport=httpx.MockTransport(handler))
    spk.tts.fish = engine
    spk.tts.engines["fish"] = engine

    class Edge:
        calls = 0

        def synthesize(self, text, p):
            Edge.calls += 1
            return AudioClip(np.zeros(2400, dtype=np.int16), 24000)

    spk.tts.engines["edge"] = Edge()
    spk.tts.engines["sapi"] = Edge()
    return spk, events, Edge


def wait_idle(spk, timeout=5):
    deadline = time.time() + timeout
    time.sleep(0.05)
    while (spk.speaking.is_set() or not spk._queue.empty()) and time.time() < deadline:
        time.sleep(0.02)


def test_replies_are_spoken_by_fish_streaming_and_not_duplicated(settings, monkeypatch):
    calls = []

    def handler(request):
        calls.append(ormsgpack.unpackb(request.content)["text"])
        return httpx.Response(200, content=iter(split_irregular(wav_bytes(0.4), sizes=(4000,))))

    spk, events, edge = make_speaker(settings, handler, monkeypatch)
    text = "Você tem três e-mails novos, o mais recente é do Carlos sobre o relatório de entregas da semana passada e de hoje." * 2
    spk.say(text)
    spk.say(text)  # repetida: ignorada
    wait_idle(spk)
    assert calls == [text.strip()] and len(spk.player.streamed) > 3 and edge.calls == 0
    assert spk.tts.last_engine == "fish"


def test_short_phrases_are_cached_after_first_stream(settings, monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, content=iter([wav_bytes(0.1)]))

    spk, _, _ = make_speaker(settings, handler, monkeypatch)
    spk.say("Às suas ordens.")
    wait_idle(spk)
    time.sleep(3.1)  # passa a janela anti-repetição
    spk.say("Às suas ordens.")
    wait_idle(spk)
    assert len(calls) == 1 and len(spk.player.clips) == 1  # 2ª vez veio do cache, sem custo


def test_new_interaction_interrupts_stream(settings, monkeypatch):
    consumed = []

    def slow_audio():
        data = wav_bytes(3.0)
        for i in range(0, len(data), 2000):
            consumed.append(i)
            yield data[i:i + 2000]
            time.sleep(0.02)

    spk, _, _ = make_speaker(settings, lambda r: httpx.Response(200, content=slow_audio()), monkeypatch)
    spk.say("Uma resposta longa que vai ser interrompida no meio pela próxima pergunta do usuário.")
    time.sleep(0.3)
    assert spk.speaking.is_set()
    spk.stop()
    wait_idle(spk)
    assert not spk.speaking.is_set()
    downloaded = len(consumed)
    time.sleep(0.5)
    assert len(consumed) == downloaded  # nenhum pedaço novo baixado após a interrupção
    assert downloaded < len(wav_bytes(3.0)) // 2000  # parou antes do fim


def test_fallback_when_api_unavailable_and_cooldown(settings, monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(402, json={"message": "insufficient balance"})

    spk, events, edge = make_speaker(settings, handler, monkeypatch)
    spk.say("Primeira resposta.")
    wait_idle(spk)
    spk.say("Segunda resposta.")
    wait_idle(spk)
    assert edge.calls == 2 and len(calls) == 1  # pausa a Fish e não tenta de novo a cada frase
    assert any("sem créditos" in e["text"] and "voz reserva" in e["text"] for e in events)


def test_fallback_on_network_error(settings, monkeypatch):
    def handler(request):
        raise httpx.ConnectError("offline")

    spk, events, edge = make_speaker(settings, handler, monkeypatch)
    spk.say("Sem internet agora.")
    wait_idle(spk)
    assert edge.calls == 1 and any("sem conexão" in e["text"] for e in events)


def test_voice_id_check(settings):
    def handler(request):
        if request.url.path == f"/model/{VOICE_ID}":
            assert request.headers["authorization"] == "Bearer fa-test-key"
            return httpx.Response(200, json={"_id": VOICE_ID, "title": "Jarvis PT", "state": "trained",
                                             "languages": ["pt"]})
        if request.url.path == "/v1/tts":
            return httpx.Response(200, content=iter(split_irregular(wav_bytes(1.0), sizes=(9000,))))
        return httpx.Response(404, json={"message": "not found"})

    report = check_fish_voice(settings, transport=httpx.MockTransport(handler))
    assert report.ok and "Jarvis PT" in report.text() and report.clip.seconds == pytest.approx(1.0, abs=0.01)
    settings.set("profiles.jarvis.fish_reference_id", "id-invalido")
    report = check_fish_voice(settings, transport=httpx.MockTransport(handler))
    assert not report.ok and "id-invalido" in report.text() and "ID da voz" in report.text()


def test_missing_key_never_calls_api(home, monkeypatch):
    monkeypatch.delenv("FISH_AUDIO_API_KEY", raising=False)
    settings = Settings(home / "s.json")
    report = check_fish_voice(settings, transport=httpx.MockTransport(lambda r: pytest.fail("não deveria chamar")))
    assert not report.ok and ".env" in report.text()


def test_env_file_loading(tmp_path, monkeypatch):
    monkeypatch.delenv("FISH_AUDIO_API_KEY", raising=False)
    assert parse_env('# c\nFISH_AUDIO_API_KEY="abc 123"\nexport X=1 # nota\n') == {"FISH_AUDIO_API_KEY": "abc 123", "X": "1"}
    env = tmp_path / ".env"
    env.write_text("FISH_AUDIO_API_KEY=segredo\n", encoding="utf-8")
    assert load_env([env]) == [env]
    import os

    assert os.environ["FISH_AUDIO_API_KEY"] == "segredo"


def test_fish_key_is_redacted_from_logs():
    import logging

    from jarvis.core.logging_setup import RedactingFilter

    for message in ("chave sk-fish-ABCdef123456_xyz-987 recusada", "FISH_AUDIO_API_KEY=ABCdef123456"):
        record = logging.LogRecord("x", 20, "", 0, message, (), None)
        RedactingFilter().filter(record)
        assert "ABCdef123456" not in record.getMessage()
