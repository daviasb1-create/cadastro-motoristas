import struct
import time

import numpy as np
import pytest

from jarvis.audio.capture import resample
from jarvis.audio.player import beep
from jarvis.audio.tts import AudioClip, TTSError, TTSManager
from jarvis.audio.vad import EnergyVAD
from jarvis.core.config import Settings, deep_merge
from jarvis.core.logging_setup import RedactingFilter
from jarvis.gaming.gamepad import BUTTONS, ComboDetector, combo_mask
from jarvis.gaming.hotkeys import parse_hotkey
from jarvis.platform.lnk import parse_lnk
from jarvis.platform.steam import installed_games, parse_vdf

from fakes import silence_frame, speech_frame


def test_vdf_and_steam_library(tmp_path):
    root = tmp_path / "Steam"
    apps = root / "steamapps"
    apps.mkdir(parents=True)
    (apps / "libraryfolders.vdf").write_text('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n'
                                             % str(root).replace("\\", "\\\\"))
    (apps / "appmanifest_349040.acf").write_text(
        '"AppState"\n{\n\t"appid"\t\t"349040"\n\t"name"\t\t"NARUTO SHIPPUDEN: Ultimate Ninja STORM 4"\n'
        '\t"installdir"\t\t"NARUTO SHIPPUDEN Ultimate Ninja STORM 4"\n}\n')
    games = installed_games(root)
    assert [(g.appid, g.name) for g in games] == [("349040", "NARUTO SHIPPUDEN: Ultimate Ninja STORM 4")]
    assert parse_vdf('"a" { "b" "c\\\\d" // comentário\n }') == {"a": {"b": "c\\d"}}


def build_lnk(target: str) -> bytes:
    header = bytearray(76)
    struct.pack_into("<I", header, 0, 0x4C)
    struct.pack_into("<I", header, 20, 0x02 | 0x80)  # HasLinkInfo | IsUnicode
    base = target.encode("latin-1") + b"\x00"
    info_header = 28
    info = struct.pack("<IIIIIII", info_header + len(base) + 1, info_header, 1, 0, info_header, 0, info_header + len(base))
    return bytes(header) + info + base + b"\x00"


def test_lnk_target():
    assert parse_lnk(build_lnk(r"C:\Program Files\App\app.exe"))["target"] == r"C:\Program Files\App\app.exe"
    with pytest.raises(ValueError):
        parse_lnk(b"nope" * 30)


def test_hotkeys_and_gamepad_combo():
    assert parse_hotkey("ctrl+alt+j") == (0x0003, ord("J"))
    assert parse_hotkey("ctrl+f9")[1] == 0x78
    with pytest.raises(ValueError):
        parse_hotkey("hyper+j")
    fired = []
    detector = ComboDetector(combo_mask(["BACK", "LEFT_THUMB"]), 0.4, lambda: fired.append(1))
    pressed = BUTTONS["BACK"] | BUTTONS["LEFT_THUMB"] | BUTTONS["A"]
    detector.update(pressed, 0.0)
    detector.update(pressed, 0.3)
    assert fired == []
    detector.update(pressed, 0.45)
    detector.update(pressed, 1.0)  # segurar não repete
    assert fired == [1]
    detector.update(0, 1.1)
    detector.update(pressed, 1.2)
    detector.update(pressed, 1.7)
    assert fired == [1, 1]


def test_vad_and_resample():
    vad = EnergyVAD()
    assert not any(vad.is_speech(silence_frame()) for _ in range(10))
    results = [vad.is_speech(speech_frame()) for _ in range(4)]
    assert results[-1]
    assert len(resample(np.zeros(4800, dtype=np.int16), 48000)) == 1600


def test_beep_and_wav_roundtrip():
    clip = beep(880, 100, second=1320)
    again = AudioClip.from_wav(clip.to_wav())
    assert again.rate == clip.rate and np.array_equal(again.samples, clip.samples)


def test_tts_fallback_and_cache(home):
    settings = Settings(home / "s.json")
    manager = TTSManager(settings, secrets=None)
    calls = []

    class Broken:
        def synthesize(self, text, p):
            calls.append("edge")
            raise TTSError("offline")

    class Local:
        def synthesize(self, text, p):
            calls.append("sapi")
            return beep()

    manager.engines["edge"], manager.engines["sapi"] = Broken(), Local()
    assert manager.synthesize("Às suas ordens.").rate == 24000
    assert manager.last_engine == "sapi"
    manager.synthesize("Às suas ordens.")
    assert calls == ["edge", "sapi"]  # 2ª vez: reserva offline primeiro e do cache


def test_settings_merge_and_redaction(home):
    merged = deep_merge({"a": {"b": 1, "c": 2}, "aliases": {"x": 1}}, {"a": {"b": 9}, "aliases": {"y": 2}})
    assert merged == {"a": {"b": 9, "c": 2}, "aliases": {"y": 2}}
    settings = Settings(home / "s.json")
    settings.set("voice.rate", 10)
    assert Settings(home / "s.json").get("voice.rate") == 10
    (home / "bad.json").write_text("{quebrado")
    assert Settings(home / "bad.json").get("voice.profile") == "jarvis"
    import logging

    record = logging.LogRecord("x", 20, "", 0, "Authorization: Bearer abc.def.ghi", (), None)
    RedactingFilter().filter(record)
    assert "abc" not in record.getMessage()


def test_reminder_service_fires(services):
    from datetime import datetime, timedelta

    fired = []
    services.reminders.on_due = fired.append
    services.reminders.add(datetime.now() + timedelta(seconds=1), "teste")
    assert services.reminders.check_due() == []
    assert len(services.reminders.check_due(time.time() + 2)) == 1 and fired[0]["text"] == "teste"


def test_music_rules_actions_and_fades(services, tmp_path):
    from jarvis.audio.music import DUCK, MusicPlayer, fade_gain
    from jarvis.brain.assistant import Assistant
    from jarvis.nlu.intents import IntentParser
    from jarvis.nlu.normalize import normalize

    parser = IntentParser()
    for text, name in [("modo homem de ferro", "music_play"), ("cheguei em casa", "music_play"),
                       ("toca a música", "music_play"), ("para a música", "music_stop"),
                       ("abaixa a música", "music_volume"), ("aumenta a trilha", "music_volume")]:
        assert parser.parse(normalize(text)).name == name
    assert parser.parse(normalize("aumenta o volume")).name == "volume_change"

    assert fade_gain(0, None, 100) == 0 and fade_gain(50, None, 100) == 0.5 and fade_gain(500, None, 100) == 1
    assert fade_gain(950, 1000, 100) == 0.5

    player = MusicPlayer(services.settings, services.bus)
    assert "Nenhuma música" in player.validate("")
    assert "Formato" in player.validate(str(tmp_path / "x.txt")) or "Não encontrei" in player.validate(str(tmp_path / "x.txt"))
    services.bus.publish("state", state="listening")
    assert player._duck == DUCK["listening"]
    services.bus.publish("state", state="idle")
    assert player._duck == 1.0

    services.extras["music"] = player
    reply = Assistant(services).handle("modo homem de ferro", source="text")
    assert not reply.ok and "Nenhuma música" in reply.text
    reply = Assistant(services).handle("abaixa a música", source="text")
    assert services.settings.get("music.volume") == 20


def test_music_really_plays_file_with_ducking_and_stop(services, tmp_path, monkeypatch):
    import sys
    import types
    import wave

    from jarvis.audio import music as music_mod

    path = tmp_path / "trilha.wav"
    t = np.arange(44100 * 3) / 44100
    tone = (np.sin(2 * np.pi * 440 * t) * 20000).astype(np.int16)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(44100)
        wav.writeframes(tone.tobytes())

    written = []

    class FakeStream:
        def __init__(self, **kwargs):
            assert kwargs["samplerate"] == 44100 and kwargs["channels"] == 2

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def write(self, block):
            written.append(np.abs(block.astype(np.float32)).max())
            time.sleep(len(block) / 44100 / 2)  # metade do tempo real

    # o Windows traz o PortAudio na roda do sounddevice; aqui um módulo falso recebe o áudio
    monkeypatch.setitem(sys.modules, "sounddevice", types.SimpleNamespace(OutputStream=FakeStream))
    services.settings.set("music.file", str(path))
    services.settings.set("music.volume", 50)
    player = music_mod.MusicPlayer(services.settings, services.bus)
    assert player.play() is None
    time.sleep(0.3)
    assert player.playing and written and written[0] < written[-1]  # entrada suave
    peak = max(written)
    services.bus.publish("state", state="listening")
    time.sleep(0.15)
    assert written[-1] < peak * 0.3  # abaixou enquanto o assistente escuta
    player.stop()
    assert not player.playing and written[-1] < peak * 0.1  # saída suave até o silêncio
    assert peak <= 20000 * 0.5 + 1  # respeita o volume configurado
