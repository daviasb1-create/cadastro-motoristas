"""Configurações persistentes do JARVIS.

As preferências ficam em settings.json (sem segredos). Chaves de API e tokens
são guardados pelo módulo ``secrets`` (Gerenciador de Credenciais do Windows).
"""
from __future__ import annotations

import copy
import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable

from . import paths

log = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "version": 1,
    "general": {
        "assistant_name": "Jarvis",
        "user_name": "",
        "user_title": "",  # ex.: "senhor", "senhora" ou vazio
        "start_with_windows": False,
        "start_minimized": True,
        "close_to_tray": True,
        "ui_animations": True,
    },
    "voice": {
        "profile": "jarvis",  # jarvis | friday
        "engine": "auto",  # auto | edge | azure | sapi
        "rate": 0,  # -50..+50 (%)
        "volume": 85,  # 0..100 volume próprio do assistente
        "spoken_replies": True,
        "verbosity": "short",  # short | detailed
        "style": "formal",  # formal | casual
        "azure_region": "brazilsouth",
    },
    "profiles": {
        "jarvis": {
            "label": "JARVIS",
            "edge_voice": "pt-BR-AntonioNeural",
            "edge_pitch": "-4Hz",
            "azure_voice": "pt-BR-AntonioNeural",
            "sapi_hint": "Daniel",
            "acks": ["Às suas ordens.", "Estou aqui.", "Pois não?", "Pode falar."],
        },
        "friday": {
            "label": "FRIDAY",
            "edge_voice": "pt-BR-FranciscaNeural",
            "edge_pitch": "+0Hz",
            "azure_voice": "pt-BR-FranciscaNeural",
            "sapi_hint": "Maria",
            "acks": ["Estou aqui.", "Pode falar.", "Pois não?", "Às suas ordens."],
        },
    },
    "wake": {
        "engine": "vosk",  # vosk | porcupine | off
        "words": ["jarvis"],
        # Como o modelo local transcreve a palavra de ativação. A calibração
        # (Configurações > Ativação) adiciona automaticamente as variantes ouvidas.
        "variants": ["jarvis", "jarbas", "jarvas", "jarves", "javis"],
        "sensitivity": 0.5,  # 0..1 (maior = dispara com mais facilidade)
        "ack_mode": "voice",  # voice | beep | both | none
        "listen_timeout": 6.0,
        "command_max_seconds": 12.0,
        "end_silence_ms": 900,
        "follow_up_seconds": 6.0,
        "preroll_seconds": 1.2,
    },
    "stt": {
        "engine": "vosk",  # vosk | whisper
        "vosk_model": "vosk-model-small-pt-0.3",
        "whisper_model": "small",
        "min_confidence": 0.55,
    },
    "audio": {
        "input_device": None,
        "output_device": None,
        "beep_on_listen": True,
        "beep_volume": 35,
        "duck_others": True,
        "duck_only_in_game": True,
        "duck_level": 35,  # % do volume original dos outros apps durante a fala
        "noise_gate": 1.0,  # multiplicador do limiar de silêncio
    },
    "gaming": {
        "auto_game_mode": True,
        "detect_fullscreen": True,
        "game_processes": ["NSUNS4.exe"],
        "short_replies_in_game": True,
        "silence_notifications_in_game": True,
        "pause_ui_in_game": True,
        "hotkeys": {
            "stop_speech": "ctrl+alt+s",
            "push_to_talk": "ctrl+alt+j",
            "toggle_mic": "ctrl+alt+m",
        },
        "gamepad": {
            "enabled": True,
            "hold_ms": 400,
            "talk_combo": ["BACK", "LEFT_THUMB"],
            "stop_combo": ["BACK", "RIGHT_THUMB"],
        },
    },
    "ai": {
        "provider": "none",  # none | anthropic | ollama
        "anthropic_model": "claude-opus-5-5",
        "effort": "low",
        "ollama_url": "http://localhost:11434",
        "ollama_model": "llama3.1",
        "timeout_seconds": 30,
        "send_content": True,
        "web_search": True,  # Claude pode pesquisar na web para perguntas atuais (custo extra por pesquisa)
        "web_search_max": 3,  # permite enviar textos de e-mails/mensagens à IA para resumir
        "max_history_turns": 20,
    },
    "apps": {
        # Atalhos personalizados. Tipos: url, path, steam, store, command, uri
        "aliases": {
            "outlook": {"type": "url", "url": "https://outlook.office.com/mail/"},
            "outlook online": {"type": "url", "url": "https://outlook.office.com/mail/"},
            "calendario": {"type": "url", "url": "https://outlook.office.com/calendar/"},
            "excel": {"type": "url", "url": "https://www.office.com/launch/excel"},
            "excel online": {"type": "url", "url": "https://www.office.com/launch/excel"},
            "onedrive": {"type": "url", "url": "https://onedrive.live.com/"},
            "whatsapp web": {"type": "url", "url": "https://web.whatsapp.com/"},
            "youtube": {"type": "url", "url": "https://www.youtube.com/"},
            "google": {"type": "url", "url": "https://www.google.com/"},
        },
        "close_requires_confirmation": False,
        "scan_steam": True,
        "scan_start_menu": True,
    },
    "folders": {
        # Pastas extras: "apelido": "C:\\caminho"
        "aliases": {},
        "search_roots": [],  # vazio = Área de Trabalho, Documentos, Downloads e OneDrive
        "search_seconds": 4,
    },
    "microsoft": {
        "client_id": "",
        "tenant": "common",
        "features": {"mail": True, "calendar": True, "excel": True, "send_mail": True},
        "poll_minutes": 3,
    },
    "outlook": {
        "notify_new": True,
        "important_senders": [],
        "urgent_keywords": ["urgente", "importante", "prazo", "imediato", "asap"],
        "manager": "",
    },
    "excel": {
        # Lista de planilhas configuradas pelo usuário. Ver docs/INTEGRACOES.md
        "workbooks": [],
        "watch_minutes": 10,
    },
    "whatsapp": {
        "enabled": True,
        "handler_match": ["whatsapp"],
        "contacts": {},  # "nome": "+5521999999999"
        "prefer_app": True,
    },
    "notifications": {
        "speak_new": True,
        "batch_seconds": 6,
        "dedupe_minutes": 30,
        "sources": {"outlook": True, "whatsapp": True, "excel": True, "windows": False, "reminder": True},
        "windows_apps": [],
        "important_senders": [],
        "important_keywords": ["urgente", "importante"],
        "quiet_hours": {"enabled": False, "start": "22:00", "end": "07:00"},
        "muted_until": None,
    },
    "memory": {
        "history_enabled": True,
        "keep_days": 30,
        "facts": [],
    },
    "music": {
        "file": "",  # arquivo de música do próprio usuário (MP3/WAV/FLAC/OGG)
        "url": "",  # alternativa sem arquivo: link do Spotify ou YouTube
        "volume": 30,
        "play_on_startup": False,
        "loop": False,
        "max_seconds": 0,  # 0 = música inteira
    },
    "spotify": {
        "client_id": "",  # app gratuito em developer.spotify.com (ver docs/INTEGRACOES.md)
    },
    "custom_commands": [],
}


FREE_DICTS = {"aliases", "contacts"}


def deep_merge(base: dict, override: dict) -> dict:
    """Mescla ``override`` sobre ``base`` sem perder chaves novas dos padrões."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        # Dicionários de dados livres (aliases, contatos) pertencem ao usuário:
        # o valor salvo substitui o padrão por inteiro, permitindo apagar itens.
        if isinstance(value, dict) and isinstance(result.get(key), dict) and key not in FREE_DICTS:
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class Settings:
    """Acesso thread-safe às configurações com notificação de mudanças."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else paths.settings_path()
        self._lock = threading.RLock()
        self._listeners: list[Callable[[str, Any], None]] = []
        self._data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                return deep_merge(DEFAULTS, raw)
            except (OSError, json.JSONDecodeError) as exc:
                backup = self.path.with_suffix(".corrompido.json")
                log.error("settings.json inválido (%s). Backup em %s; usando padrões.", exc, backup)
                try:
                    self.path.replace(backup)
                except OSError:
                    pass
        return copy.deepcopy(DEFAULTS)

    def save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)

    def get(self, dotted: str, default: Any = None) -> Any:
        with self._lock:
            node: Any = self._data
            for part in dotted.split("."):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return copy.deepcopy(node)

    def set(self, dotted: str, value: Any, save: bool = True) -> None:
        with self._lock:
            parts = dotted.split(".")
            node = self._data
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = copy.deepcopy(value)
            if save:
                self.save()
        for listener in list(self._listeners):
            try:
                listener(dotted, value)
            except Exception:  # noqa: BLE001 - um ouvinte com erro não pode derrubar os demais
                log.exception("Erro em ouvinte de configuração")

    def as_dict(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    def replace_all(self, data: dict) -> None:
        with self._lock:
            self._data = deep_merge(DEFAULTS, data)
            self.save()
        for listener in list(self._listeners):
            try:
                listener("*", None)
            except Exception:  # noqa: BLE001
                log.exception("Erro em ouvinte de configuração")

    def on_change(self, callback: Callable[[str, Any], None]) -> None:
        self._listeners.append(callback)
