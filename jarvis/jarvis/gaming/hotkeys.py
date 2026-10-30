"""Atalhos globais de teclado (RegisterHotKey da API do Windows).

Funcionam com o jogo em tela cheia, sem gancho de teclado e sem injetar nada
no processo do jogo. Exemplo: "ctrl+alt+s" para interromper a fala.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import threading
from typing import Callable

log = logging.getLogger(__name__)

MODIFIERS = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002, "shift": 0x0004, "win": 0x0008}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
SPECIAL_KEYS = {
    **{f"f{i}": 0x6F + i for i in range(1, 25)},
    "space": 0x20, "espaco": 0x20, "enter": 0x0D, "esc": 0x1B, "tab": 0x09, "pause": 0x13,
    "scrolllock": 0x91, "home": 0x24, "end": 0x23, "insert": 0x2D, "delete": 0x2E,
    "pageup": 0x21, "pagedown": 0x22, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
}


def parse_hotkey(text: str) -> tuple[int, int]:
    """'ctrl+alt+j' -> (modificadores, código virtual da tecla)."""
    parts = [p.strip().lower() for p in text.replace(" ", "").split("+") if p.strip()]
    if not parts:
        raise ValueError("Atalho vazio")
    mods = 0
    for part in parts[:-1]:
        if part not in MODIFIERS:
            raise ValueError(f"Modificador inválido: {part}")
        mods |= MODIFIERS[part]
    key = parts[-1]
    if key in SPECIAL_KEYS:
        vk = SPECIAL_KEYS[key]
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    else:
        raise ValueError(f"Tecla inválida: {key}")
    return mods, vk


class HotkeyManager:
    def __init__(self) -> None:
        self._bindings: dict[int, tuple[str, Callable[[], None]]] = {}
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._requested: list[tuple[str, Callable[[], None]]] = []
        self.errors: list[str] = []

    def start(self, bindings: list[tuple[str, Callable[[], None]]]) -> None:
        if sys.platform != "win32":
            return
        self.stop()
        self._requested = [b for b in bindings if b[0]]
        ready = threading.Event()
        self._thread = threading.Thread(target=self._loop, args=(ready,), name="hotkeys", daemon=True)
        self._thread.start()
        ready.wait(2)

    def _loop(self, ready: threading.Event) -> None:
        from ctypes import wintypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        self._thread_id = kernel32.GetCurrentThreadId()
        self.errors = []
        for index, (combo, callback) in enumerate(self._requested, start=1):
            try:
                mods, vk = parse_hotkey(combo)
            except ValueError as exc:
                self.errors.append(f"{combo}: {exc}")
                continue
            if user32.RegisterHotKey(None, index, mods | MOD_NOREPEAT, vk):
                self._bindings[index] = (combo, callback)
            else:
                self.errors.append(f"{combo}: já usado por outro programa")
        if self.errors:
            log.warning("Atalhos não registrados: %s", self.errors)
        ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in self._bindings:
                combo, callback = self._bindings[msg.wParam]
                try:
                    callback()
                except Exception:  # noqa: BLE001
                    log.exception("Erro no atalho %s", combo)
        for index in list(self._bindings):
            user32.UnregisterHotKey(None, index)
        self._bindings.clear()

    def stop(self) -> None:
        if self._thread and self._thread.is_alive() and self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)  # type: ignore[attr-defined]
            self._thread.join(timeout=2)
        self._thread = None
