"""Volume do Windows (pycaw / Core Audio) e ajustes de voz do assistente."""
from __future__ import annotations

import logging
import sys
import threading

from .base import BOOL, INT, STR, ActionResult, ServiceUnavailable, action, props

log = logging.getLogger(__name__)


def _com_init() -> None:
    if sys.platform == "win32":
        import comtypes  # type: ignore

        try:
            comtypes.CoInitialize()
        except OSError:
            pass  # já inicializado nesta thread


class VolumeController:
    """Volume geral do dispositivo de saída padrão."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def _endpoint(self):
        if sys.platform != "win32":
            raise ServiceUnavailable("Controle de volume disponível apenas no Windows.")
        _com_init()
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore
        except ImportError as exc:
            raise ServiceUnavailable("Biblioteca de áudio (pycaw) não instalada.") from exc
        speakers = AudioUtilities.GetSpeakers()
        endpoint = getattr(speakers, "EndpointVolume", None)
        if endpoint is not None:
            return endpoint
        from ctypes import POINTER, cast

        from comtypes import CLSCTX_ALL  # type: ignore

        interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))

    def get(self) -> int:
        with self._lock:
            return round(self._endpoint().GetMasterVolumeLevelScalar() * 100)

    def set(self, level: int) -> int:
        level = max(0, min(100, int(level)))
        with self._lock:
            endpoint = self._endpoint()
            endpoint.SetMasterVolumeLevelScalar(level / 100.0, None)
            if level > 0 and endpoint.GetMute():
                endpoint.SetMute(0, None)
        return level

    def is_muted(self) -> bool:
        with self._lock:
            return bool(self._endpoint().GetMute())

    def mute(self, muted: bool) -> None:
        with self._lock:
            self._endpoint().SetMute(1 if muted else 0, None)


def _volume(services) -> VolumeController:
    if services.volume is None:
        services.volume = VolumeController()
    return services.volume


@action("volume_change", "Aumenta ou diminui o volume geral do Windows em pontos percentuais.",
        props(["delta"], delta=INT | {"description": "Positivo aumenta, negativo diminui (ex.: 10, -10)."}))
def volume_change(services, params):
    vol = _volume(services)
    before = vol.get()
    after = vol.set(before + int(params.get("delta", 10)))
    return ActionResult(f"Volume em {after} por cento.", undo=lambda: _restore(vol, before),
                        undo_label="ajuste de volume")


@action("volume_set", "Define o volume geral do Windows (0 a 100).", props(["level"], level=INT))
def volume_set(services, params):
    vol = _volume(services)
    before = vol.get()
    after = vol.set(int(params.get("level", 50)))
    return ActionResult(f"Volume ajustado para {after} por cento.", undo=lambda: _restore(vol, before),
                        undo_label="ajuste de volume")


@action("volume_get", "Informa o volume atual do Windows.")
def volume_get(services, params):
    vol = _volume(services)
    muted = " e está no mudo" if vol.is_muted() else ""
    return ActionResult(f"O volume está em {vol.get()} por cento{muted}.")


@action("volume_mute", "Liga ou desliga o mudo do Windows.", props(["mute"], mute=BOOL))
def volume_mute(services, params):
    vol = _volume(services)
    mute = bool(params.get("mute", True))
    before = vol.is_muted()
    vol.mute(mute)
    say = "Som desligado." if mute else "Som reativado."

    def undo() -> str:
        vol.mute(before)
        return "Mudo restaurado." if before else "Som restaurado."

    return ActionResult(say, undo=undo, undo_label="mudo")


def _restore(vol: VolumeController, level: int) -> str:
    vol.set(level)
    return f"Volume de volta para {level} por cento."


# ------------------------------------------------ voz do próprio assistente
@action("speech_rate", "Ajusta a velocidade da fala do assistente.", props(["delta"], delta=INT))
def speech_rate(services, params):
    rate = max(-50, min(50, services.settings.get("voice.rate", 0) + int(params.get("delta", 10))))
    services.settings.set("voice.rate", rate)
    return ActionResult("Velocidade ajustada." if rate != 0 else "Velocidade normal.")


@action("speech_volume", "Ajusta o volume da voz do assistente (independente do volume do Windows).",
        props(["delta"], delta=INT))
def speech_volume(services, params):
    volume = max(10, min(100, services.settings.get("voice.volume", 85) + int(params.get("delta", 10))))
    services.settings.set("voice.volume", volume)
    return ActionResult(f"Minha voz está em {volume} por cento.")


@action("set_profile", "Troca o perfil de voz entre JARVIS e FRIDAY.",
        props(["profile"], profile=STR | {"enum": ["jarvis", "friday"]}))
def set_profile(services, params):
    profile = params.get("profile", "jarvis")
    previous = services.settings.get("voice.profile", "jarvis")
    services.settings.set("voice.profile", profile)
    say = "Friday no comando. Como posso ajudar?" if profile == "friday" else "Jarvis de volta. Às suas ordens."

    def undo() -> str:
        services.settings.set("voice.profile", previous)
        return "Perfil de voz restaurado."

    return ActionResult(say, undo=undo, undo_label="troca de voz")


@action("set_verbosity", "Define respostas curtas ou detalhadas.",
        props(["verbosity"], verbosity=STR | {"enum": ["short", "detailed"]}))
def set_verbosity(services, params):
    value = params.get("verbosity", "short")
    services.settings.set("voice.verbosity", value)
    return ActionResult("Certo, respostas curtas." if value == "short" else "Certo, respostas mais detalhadas.")


@action("spoken_replies", "Ativa ou desativa as respostas faladas.", props(["enabled"], enabled=BOOL))
def spoken_replies(services, params):
    enabled = bool(params.get("enabled", True))
    services.settings.set("voice.spoken_replies", enabled)
    return ActionResult("Respostas faladas ativadas." if enabled else "Certo, vou responder só na tela.")
