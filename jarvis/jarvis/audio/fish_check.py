"""Teste da voz Fish Audio: confirma chave, ID da voz, modelo e tempo até o primeiro áudio."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from .fish import FishAudioEngine, FishError
from .tts import AudioClip, VoiceParams

SAMPLE_TEXT = "Olá. Sistemas online. Estou pronto para ajudar."


@dataclass
class FishReport:
    ok: bool
    steps: list[str] = field(default_factory=list)
    voice: dict = field(default_factory=dict)
    first_audio_ms: int = 0
    seconds: float = 0.0
    clip: AudioClip | None = None

    def text(self) -> str:
        lines = list(self.steps)
        if self.ok:
            lines.append(f"Primeiro áudio em {self.first_audio_ms} ms; {self.seconds:.1f} s de fala gerados.")
        return "\n".join(lines)


def check_fish_voice(settings, profile: str = "jarvis", text: str = SAMPLE_TEXT, transport=None) -> FishReport:
    engine = FishAudioEngine(settings, transport=transport)
    report = FishReport(ok=False)
    if not engine.api_key:
        report.steps.append("✗ Chave FISH_AUDIO_API_KEY não encontrada no arquivo .env.")
        return report
    report.steps.append("✓ Chave encontrada no .env.")
    reference = engine.reference_id(profile)
    if not reference:
        report.steps.append(f"✗ Nenhum ID de voz configurado para o perfil {profile}.")
        return report
    try:
        report.voice = engine.check_voice(reference)
        title = report.voice.get("title") or "(sem título)"
        report.steps.append(f"✓ Voz encontrada: {title} (ID {reference}).")
    except FishError as exc:
        report.steps.append(f"✗ ID da voz {reference}: {exc}.")
        return report
    params = VoiceParams(profile=profile, voice="", pitch="+0Hz", rate=int(settings.get("voice.rate", 0)), sapi_hint="")
    started = time.time()
    try:
        stream = engine.open_stream(text, params)
        report.first_audio_ms = int((time.time() - started) * 1000)
        parts = list(stream.chunks())
    except FishError as exc:
        report.steps.append(f"✗ Geração de fala com o modelo {settings.get('fish.model')}: {exc}.")
        return report
    if not parts:
        report.steps.append("✗ A Fish Audio não retornou áudio.")
        return report
    report.clip = AudioClip(np.concatenate(parts), stream.rate)
    report.seconds = report.clip.seconds
    report.steps.append(f"✓ Fala gerada com o modelo {settings.get('fish.model')} em streaming ({stream.rate} Hz).")
    report.ok = True
    return report
