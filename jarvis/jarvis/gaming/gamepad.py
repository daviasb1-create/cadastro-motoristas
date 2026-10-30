"""Combinações de botões do controle Xbox (XInput) para falar com o JARVIS ou interrompê-lo.

Lê o estado do controle pela API XInput do Windows, 15 vezes por segundo
(uso de CPU desprezível). Não interfere no jogo: o jogo continua recebendo
os botões normalmente, por isso as combinações padrão usam botões pouco
usados em conjunto (View + clique do analógico) e exigem segurar 0,4 s.

Controles PlayStation: o XInput não enxerga o touchpad do DualShock/DualSense.
Com o DS4Windows (ou a Steam Input) emulando um controle Xbox, mapeie o
touchpad para uma tecla de atalho configurada no JARVIS (ver docs).
"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

BUTTONS = {
    "DPAD_UP": 0x0001, "DPAD_DOWN": 0x0002, "DPAD_LEFT": 0x0004, "DPAD_RIGHT": 0x0008,
    "START": 0x0010, "BACK": 0x0020, "LEFT_THUMB": 0x0040, "RIGHT_THUMB": 0x0080,
    "LEFT_SHOULDER": 0x0100, "RIGHT_SHOULDER": 0x0200, "A": 0x1000, "B": 0x2000, "X": 0x4000, "Y": 0x8000,
}


class _GAMEPAD(ctypes.Structure):
    _fields_ = [("wButtons", ctypes.c_ushort), ("bLeftTrigger", ctypes.c_ubyte),
                ("bRightTrigger", ctypes.c_ubyte), ("sThumbLX", ctypes.c_short), ("sThumbLY", ctypes.c_short),
                ("sThumbRX", ctypes.c_short), ("sThumbRY", ctypes.c_short)]


class _STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_ulong), ("Gamepad", _GAMEPAD)]


def combo_mask(names: list[str]) -> int:
    mask = 0
    for name in names:
        key = name.strip().upper()
        if key not in BUTTONS:
            raise ValueError(f"Botão desconhecido: {name}")
        mask |= BUTTONS[key]
    return mask


class ComboDetector:
    """Dispara uma vez quando todos os botões ficam pressionados por ``hold`` segundos."""

    def __init__(self, mask: int, hold: float, callback: Callable[[], None]) -> None:
        self.mask = mask
        self.hold = hold
        self.callback = callback
        self._since: float | None = None
        self._fired = False

    def update(self, buttons: int, now: float) -> bool:
        if self.mask and buttons & self.mask == self.mask:
            if self._since is None:
                self._since = now
            if not self._fired and now - self._since >= self.hold:
                self._fired = True
                self.callback()
                return True
        else:
            self._since = None
            self._fired = False
        return False


class GamepadWatcher:
    def __init__(self, settings) -> None:
        self.settings = settings
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._xinput = None
        self.connected = False

    def _load(self):
        for dll in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
            try:
                return getattr(ctypes.windll, dll)  # type: ignore[attr-defined]
            except OSError:
                continue
        return None

    def start(self, on_talk: Callable[[], None], on_stop: Callable[[], None]) -> None:
        if sys.platform != "win32" or not self.settings.get("gaming.gamepad.enabled", True):
            return
        self._xinput = self._load()
        if self._xinput is None:
            log.info("XInput indisponível")
            return
        hold = int(self.settings.get("gaming.gamepad.hold_ms", 400)) / 1000.0
        try:
            detectors = [
                ComboDetector(combo_mask(self.settings.get("gaming.gamepad.talk_combo", []) or []), hold, on_talk),
                ComboDetector(combo_mask(self.settings.get("gaming.gamepad.stop_combo", []) or []), hold, on_stop),
            ]
        except ValueError as exc:
            log.error("Combinação de controle inválida: %s", exc)
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, args=(detectors,), name="gamepad", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self, detectors: list[ComboDetector]) -> None:
        state = _STATE()
        idle_checks = 0
        while not self._stop.is_set():
            buttons = 0
            connected = False
            for user in range(4):
                if self._xinput.XInputGetState(user, ctypes.byref(state)) == 0:
                    connected = True
                    buttons |= state.Gamepad.wButtons
            self.connected = connected
            now = time.time()
            for detector in detectors:
                detector.update(buttons, now)
            # sem controle conectado, verifica só a cada 2 s
            if not connected:
                idle_checks += 1
                self._stop.wait(2.0)
            else:
                self._stop.wait(1 / 15)
