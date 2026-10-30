"""Descoberta de jogos instalados na Steam (somente leitura dos manifestos)."""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


def parse_vdf(text: str) -> dict:
    """Parser do formato KeyValues (VDF/ACF) em texto usado pela Steam."""
    tokens: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c == "/" and text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif c in "{}":
            tokens.append(c)
            i += 1
        elif c == '"':
            i += 1
            buf = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    nxt = text[i + 1]
                    buf.append({"n": "\n", "t": "\t", "\\": "\\", '"': '"'}.get(nxt, nxt))
                    i += 2
                    continue
                buf.append(text[i])
                i += 1
            tokens.append("\x00" + "".join(buf))  # marca de string
            i += 1
        else:
            start = i
            while i < n and text[i] not in ' \t\r\n{}"':
                i += 1
            tokens.append("\x00" + text[start:i])

    def parse_block(index: int) -> tuple[dict, int]:
        obj: dict = {}
        while index < len(tokens):
            tok = tokens[index]
            if tok == "}":
                return obj, index + 1
            key = tok[1:]
            index += 1
            if index >= len(tokens):
                break
            if tokens[index] == "{":
                value, index = parse_block(index + 1)
            else:
                value = tokens[index][1:]
                index += 1
            obj[key] = value
        return obj, index

    result, _ = parse_block(0)
    return result


@dataclass
class SteamGame:
    appid: str
    name: str
    install_dir: Path


def steam_root() -> Path | None:
    if sys.platform == "win32":
        import winreg

        for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    for value in ("SteamPath", "InstallPath"):
                        try:
                            path = Path(winreg.QueryValueEx(handle, value)[0])
                            if path.exists():
                                return path
                        except FileNotFoundError:
                            continue
            except OSError:
                continue
        default = Path(r"C:\Program Files (x86)\Steam")
        return default if default.exists() else None
    linux = Path.home() / ".steam" / "steam"
    return linux if linux.exists() else None


def library_folders(root: Path) -> list[Path]:
    folders = [root]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        try:
            data = parse_vdf(vdf.read_text(encoding="utf-8", errors="ignore"))
            libs = data.get("libraryfolders") or data.get("LibraryFolders") or {}
            for value in libs.values():
                path = value.get("path") if isinstance(value, dict) else value
                if path and Path(path).exists() and Path(path) not in folders:
                    folders.append(Path(path))
        except Exception:  # noqa: BLE001
            log.warning("Não foi possível ler libraryfolders.vdf", exc_info=True)
    return folders


def installed_games(root: Path | None = None) -> list[SteamGame]:
    root = root or steam_root()
    if not root:
        return []
    games: list[SteamGame] = []
    for library in library_folders(root):
        apps = library / "steamapps"
        for manifest in apps.glob("appmanifest_*.acf"):
            try:
                state = parse_vdf(manifest.read_text(encoding="utf-8", errors="ignore")).get("AppState", {})
                appid, name = state.get("appid"), state.get("name")
                if appid and name and appid != "228980":  # ignora "Steamworks Common Redistributables"
                    games.append(SteamGame(appid, name, apps / "common" / state.get("installdir", "")))
            except Exception:  # noqa: BLE001
                log.debug("Manifesto ignorado: %s", manifest, exc_info=True)
    return games
