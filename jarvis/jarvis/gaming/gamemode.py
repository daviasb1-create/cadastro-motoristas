"""Detecção automática do modo jogo (processo do jogo aberto ou app em tela cheia)."""
from __future__ import annotations

import logging
import threading

from ..actions.control import set_game_mode
from ..platform import windows as win

log = logging.getLogger(__name__)


def running_game(process_names: list[str]) -> str | None:
    import psutil

    wanted = {p.lower() for p in process_names if p}
    if not wanted:
        return None
    for proc in psutil.process_iter(["name"]):
        name = (proc.info.get("name") or "").lower()
        if name in wanted:
            return proc.info["name"]
    return None


class GameModeMonitor:
    def __init__(self, services) -> None:
        self.services = services
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._loop, name="game-mode", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def check_once(self) -> tuple[bool, str]:
        settings = self.services.settings
        game = running_game(settings.get("gaming.game_processes", []) or [])
        if game:
            return True, game
        if settings.get("gaming.detect_fullscreen", True) and win.user_notification_state() == "d3d_fullscreen":
            return True, "tela cheia"
        return False, ""

    def _loop(self) -> None:
        while not self._stop.wait(5):
            settings = self.services.settings
            state = self.services.state
            if not settings.get("gaming.auto_game_mode", True) or state.game_mode_manual is True:
                continue
            try:
                active, reason = self.check_once()
            except Exception:  # noqa: BLE001
                log.debug("Falha na detecção de jogo", exc_info=True)
                continue
            if state.game_mode_manual is False:
                # Usuário desligou o modo jogo com o jogo aberto: respeita até o jogo fechar
                if not active:
                    state.game_mode_manual = None
                continue
            if active != state.game_mode:
                set_game_mode(self.services, active, reason or "jogo encerrado")
