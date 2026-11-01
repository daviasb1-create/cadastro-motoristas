"""Perfis de jogos: configurações por executável (prioridade, GPU de alto desempenho, tela cheia,
boost de sessão) e detecção de jogos instalados na Steam."""
from __future__ import annotations

import json
import os
import re
import threading

from ..config import IS_WINDOWS, PROFILES_FILE
from . import registry as reg
from .journal import Journal

_GPU_PREF = r"Software\Microsoft\DirectX\UserGpuPreferences"
_LAYERS = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"

DEFAULT_PROFILE = {
    "name": "", "exe": "", "priority": "Alta", "gpu_high": True, "disable_fso": False,
    "close_bg": True, "stop_services": True, "trim_ram": True, "timer": True, "enabled": True,
}


class Profiles:
    _lock = threading.Lock()

    def __init__(self):
        self.items: list[dict] = []
        try:
            if PROFILES_FILE.exists():
                self.items = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
        except Exception:
            self.items = []

    def save(self):
        with self._lock:
            PROFILES_FILE.write_text(json.dumps(self.items, indent=2, ensure_ascii=False), encoding="utf-8")

    def add(self, exe: str, name: str = "", **opts) -> dict:
        exe = os.path.normpath(exe)
        existing = self.get_by_exe(exe)
        if existing:
            return existing
        p = dict(DEFAULT_PROFILE, exe=exe, name=name or os.path.splitext(os.path.basename(exe))[0], **opts)
        self.items.append(p)
        self.save()
        return p

    def remove(self, exe: str, journal: Journal):
        journal.revert_group(profile_gid(exe))
        self.items = [p for p in self.items if os.path.normcase(p["exe"]) != os.path.normcase(exe)]
        self.save()

    def update(self, exe: str, **changes):
        p = self.get_by_exe(exe)
        if p:
            p.update(changes)
            self.save()
        return p

    def get_by_exe(self, exe: str) -> dict | None:
        n = os.path.normcase(os.path.normpath(exe))
        return next((p for p in self.items if os.path.normcase(p["exe"]) == n), None)

    def exe_names(self) -> dict[str, dict]:
        return {os.path.basename(p["exe"]).lower(): p for p in self.items if p.get("enabled", True)}


def profile_gid(exe: str) -> str:
    return f"profile:{os.path.normcase(exe)}"


def apply_profile_registry(p: dict, journal: Journal) -> list[str]:
    """Aplica as configurações persistentes do perfil (GPU dedicada e tela cheia exclusiva)."""
    gid = profile_gid(p["exe"])
    journal.revert_group(gid)  # reaplica do zero conforme o perfil atual
    journal.group(gid, f"Perfil de jogo: {p['name']}", "jogos")
    msgs = []
    if p.get("gpu_high"):
        journal.reg_set(gid, "HKCU", _GPU_PREF, p["exe"], reg.REG_SZ, "GpuPreference=2;")
        msgs.append("GPU de alto desempenho definida")
    if p.get("disable_fso"):
        _e, _t, cur = reg.read_value("HKCU", _LAYERS, p["exe"])
        flags = set(str(cur or "").replace("~", "").split())
        flags.add("DISABLEDXMAXIMIZEDWINDOWEDMODE")
        journal.reg_set(gid, "HKCU", _LAYERS, p["exe"], reg.REG_SZ, "~ " + " ".join(sorted(flags)))
        msgs.append("Otimizações de tela cheia desativadas para este jogo")
    return msgs


def detect_steam_games() -> list[dict]:
    """Encontra jogos instalados nas bibliotecas da Steam (lê libraryfolders.vdf e appmanifest)."""
    if not IS_WINDOWS:
        return []
    steam = None
    for hive, path in (("HKCU", r"Software\Valve\Steam"), ("HKLM", r"SOFTWARE\WOW6432Node\Valve\Steam")):
        ok, _t, v = reg.read_value(hive, path, "SteamPath" if hive == "HKCU" else "InstallPath")
        if ok and v and os.path.isdir(v):
            steam = os.path.normpath(v)
            break
    if not steam:
        return []
    libs = {os.path.join(steam, "steamapps")}
    vdf = os.path.join(steam, "steamapps", "libraryfolders.vdf")
    try:
        txt = open(vdf, encoding="utf-8", errors="ignore").read()
        for m in re.finditer(r'"path"\s*"([^"]+)"', txt):
            libs.add(os.path.join(m.group(1).replace("\\\\", "\\"), "steamapps"))
    except OSError:
        pass
    games = []
    skip = re.compile(r"(unins|setup|redist|vcredist|dxsetup|crash|report|launcher_helper|easyanticheat|"
                      r"battleye|be_service|ue4prereq|dotnet|install)", re.I)
    for lib in libs:
        if not os.path.isdir(lib):
            continue
        for f in os.listdir(lib):
            if not f.startswith("appmanifest_"):
                continue
            try:
                txt = open(os.path.join(lib, f), encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            name = re.search(r'"name"\s*"([^"]+)"', txt)
            folder = re.search(r'"installdir"\s*"([^"]+)"', txt)
            if not (name and folder):
                continue
            gdir = os.path.join(lib, "common", folder.group(1))
            best, best_size = None, 0
            for root, _dirs, files in os.walk(gdir):
                if root.count(os.sep) - gdir.count(os.sep) > 3:
                    continue
                for fn in files:
                    if fn.lower().endswith(".exe") and not skip.search(fn):
                        fp = os.path.join(root, fn)
                        try:
                            sz = os.path.getsize(fp)
                        except OSError:
                            continue
                        if sz > best_size:
                            best, best_size = fp, sz
            if best and "Steamworks" not in name.group(1):
                games.append({"name": name.group(1), "exe": best})
    return sorted(games, key=lambda g: g["name"].lower())


profiles = Profiles()
