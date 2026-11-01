"""Programas de inicialização: lista e desativa usando o mesmo mecanismo do Gerenciador de Tarefas
(chaves StartupApproved). Nada é apagado: desativar é 100% reversível."""
from __future__ import annotations

import os
import struct
import time

from ..config import IS_WINDOWS
from . import registry as reg
from .journal import Journal

_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN32 = r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"
_APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"

SOURCES = [
    # (hive, chave Run ou None, pasta, chave StartupApproved, rótulo)
    ("HKCU", _RUN, None, _APPROVED + r"\Run", "Registro (usuário)"),
    ("HKLM", _RUN, None, _APPROVED + r"\Run", "Registro (todos os usuários)"),
    ("HKLM", _RUN32, None, _APPROVED + r"\Run32", "Registro 32 bits"),
    ("HKCU", None, "APPDATA", _APPROVED + r"\StartupFolder", "Pasta Inicializar (usuário)"),
    ("HKLM", None, "PROGRAMDATA", _APPROVED + r"\StartupFolder", "Pasta Inicializar (todos)"),
]

# Recomendações: apps que normalmente podem ser desativados / que devem ser mantidos.
RECOMMEND_DISABLE = [
    "spotify", "discord", "steam", "epicgames", "eadesktop", "origin", "upc", "ubisoft", "battle.net",
    "teams", "skype", "zoom", "adobe", "ccleaner", "utorrent", "qbittorrent", "dropbox", "googledrive",
    "ituneshelper", "opera", "microsoftedgeautolaunch", "edge", "cortana", "lghub", "wallpaper", "whatsapp",
    "telegram", "slack", "acrobat", "java", "jusched", "onedrive",
]
KEEP = ["securityhealth", "windowsdefender", "rtk", "realtek", "nvidia", "nv", "igfx", "intel", "amd", "radeon",
        "synaptics", "etd", "elan", "bluetooth", "audio", "touchpad", "ctfmon", "vmware", "virtualbox"]


def _folder(var: str) -> str:
    base = os.environ.get(var, "")
    if var == "APPDATA":
        return os.path.join(base, r"Microsoft\Windows\Start Menu\Programs\Startup")
    return os.path.join(base, r"Microsoft\Windows\Start Menu\Programs\StartUp")


def _recommendation(name: str, command: str) -> str:
    text = (name + " " + command).lower()
    if any(k in text for k in KEEP):
        return "manter"
    if any(k in text for k in RECOMMEND_DISABLE):
        return "desativar"
    return "neutro"


def list_entries() -> list[dict]:
    if not IS_WINDOWS:
        return []
    out = []
    for hive, runkey, folder, approved, label in SOURCES:
        items = []
        if runkey:
            for name, value, _t in reg.list_values(hive, runkey):
                items.append((name, str(value)))
        else:
            d = _folder(folder)
            if os.path.isdir(d):
                for f in os.listdir(d):
                    if f.lower() != "desktop.ini":
                        items.append((f, os.path.join(d, f)))
        for name, command in items:
            ok, _t, data = reg.read_value(hive, approved, name)
            enabled = not (ok and isinstance(data, (bytes, bytearray)) and len(data) and data[0] & 1)
            out.append({"name": name, "command": command, "hive": hive, "approved": approved,
                        "source": label, "enabled": enabled, "admin": hive == "HKLM",
                        "rec": _recommendation(name, command), "gid": f"startup:{hive}:{approved}:{name}"})
    out.sort(key=lambda e: ({"desativar": 0, "neutro": 1, "manter": 2}[e["rec"]], e["name"].lower()))
    return out


def _filetime_now() -> bytes:
    return struct.pack("<Q", int((time.time() + 11644473600) * 10_000_000))


def set_enabled(entry: dict, enabled: bool, journal: Journal) -> str:
    gid = entry["gid"]
    if enabled:
        if journal.has_group(gid):
            journal.revert_group(gid)
        else:
            journal.group(gid, f"Inicialização: {entry['name']}", "inicializacao")
            journal.reg_set(gid, entry["hive"], entry["approved"], entry["name"], reg.REG_BINARY,
                            b"\x02\x00\x00\x00" + b"\x00" * 8)
        return f"{entry['name']} será iniciado com o Windows."
    journal.group(gid, f"Inicialização desativada: {entry['name']}", "inicializacao")
    journal.reg_set(gid, entry["hive"], entry["approved"], entry["name"], reg.REG_BINARY,
                    b"\x03\x00\x00\x00" + _filetime_now())
    return f"{entry['name']} não será mais iniciado com o Windows (reversível)."
