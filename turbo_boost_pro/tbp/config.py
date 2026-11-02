"""Caminhos, configurações persistentes e constantes globais."""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"


def _data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(Path.home(), ".local", "share")
    p = Path(base) / "TurboBoostPro"
    p.mkdir(parents=True, exist_ok=True)
    return p


DATA_DIR = _data_dir()
BACKUP_DIR = DATA_DIR / "backup"
LOG_DIR = DATA_DIR / "logs"
REPORT_DIR = DATA_DIR / "relatorios"
for _d in (BACKUP_DIR, LOG_DIR, REPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

JOURNAL_FILE = BACKUP_DIR / "journal.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
PROFILES_FILE = DATA_DIR / "game_profiles.json"


def resource_path(rel: str) -> str:
    """Resolve caminho de recursos tanto em dev quanto empacotado (PyInstaller)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, rel)


DEFAULT_SETTINGS = {
    "restore_point_before_changes": True,
    "auto_mode": False,
    "auto_ram_threshold": 85,
    "auto_game_boost": True,
    "close_bg_apps_in_turbo": True,
    "stop_services_in_turbo": True,
    "relaunch_closed_apps": True,
    "preferred_dns": "cloudflare",
    "current_mode": "equilibrado",
    "monitor_interval_ms": 1000,
    "custom_kill_list": [],
    "never_kill": ["discord.exe", "obs64.exe", "steam.exe"],
    "timer_mode": "auto",          # auto = só após teste A/B aprovar; on/off
    "timer_ab_result": None,
    "presentmon_path": "",
    "bench_seconds": 60,
}


class Settings:
    _lock = threading.Lock()

    def __init__(self):
        self.data = dict(DEFAULT_SETTINGS)
        try:
            if SETTINGS_FILE.exists():
                self.data.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass

    def get(self, key, default=None):
        return self.data.get(key, DEFAULT_SETTINGS.get(key, default))

    def set(self, key, value):
        with self._lock:
            self.data[key] = value
            self.save()

    def save(self):
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, SETTINGS_FILE)


settings = Settings()
