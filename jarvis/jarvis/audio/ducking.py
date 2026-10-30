"""Redução temporária do volume de outros apps (ex.: o jogo) enquanto o JARVIS fala.

Usa a API de sessões de áudio do Windows (ISimpleAudioVolume via pycaw),
a mesma do Mixer de Volume. Não toca em arquivos nem no processo do jogo.
"""
from __future__ import annotations

import logging
import os
import sys
import threading

log = logging.getLogger(__name__)


class Ducker:
    def __init__(self, settings, state) -> None:
        self.settings = settings
        self.state = state
        self._saved: dict[str, float] = {}
        self._lock = threading.Lock()

    def enabled(self) -> bool:
        if sys.platform != "win32" or not self.settings.get("audio.duck_others", True):
            return False
        if self.settings.get("audio.duck_only_in_game", True):
            return bool(self.state.game_mode)
        return True

    def _sessions(self):
        import comtypes  # type: ignore
        from pycaw.pycaw import AudioUtilities  # type: ignore

        try:
            comtypes.CoInitialize()
        except OSError:
            pass
        return AudioUtilities.GetAllSessions()

    def duck(self) -> None:
        if not self.enabled():
            return
        level = max(0, min(100, int(self.settings.get("audio.duck_level", 35)))) / 100.0
        own = os.getpid()
        with self._lock:
            try:
                for session in self._sessions():
                    proc = session.Process
                    key = _session_key(session)
                    if proc is None or proc.pid == own or key in self._saved:
                        continue
                    volume = session.SimpleAudioVolume
                    current = volume.GetMasterVolume()
                    self._saved[key] = current
                    volume.SetMasterVolume(current * level, None)
            except Exception:  # noqa: BLE001
                log.debug("Ducking indisponível", exc_info=True)

    def restore(self) -> None:
        with self._lock:
            if not self._saved:
                return
            try:
                for session in self._sessions():
                    key = _session_key(session)
                    if key in self._saved:
                        session.SimpleAudioVolume.SetMasterVolume(self._saved[key], None)
            except Exception:  # noqa: BLE001
                log.debug("Falha ao restaurar volumes", exc_info=True)
            finally:
                self._saved.clear()


def _session_key(session) -> str:
    """Um processo pode ter várias sessões de áudio (jogos, Discord): cada uma guarda seu volume."""
    try:
        return str(session.InstanceIdentifier)
    except Exception:  # noqa: BLE001
        proc = session.Process
        return f"pid:{proc.pid if proc else 0}"
