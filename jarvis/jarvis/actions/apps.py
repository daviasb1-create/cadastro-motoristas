"""Abrir e fechar programas, jogos, sites, pastas e janelas.

Somente alvos conhecidos são executados: atalhos do Menu Iniciar, apps da
Microsoft Store, jogos da Steam, pastas do usuário e atalhos definidos nas
configurações. Nenhum texto reconhecido por voz é executado como comando
de terminal.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..core import paths
from ..nlu.normalize import normalize, similar
from ..nlu.numbers import words_to_digits
from ..platform import windows as win
from ..platform.lnk import lnk_target
from ..platform.steam import installed_games
from .base import BOOL, STR, ActionResult, action, props

log = logging.getLogger(__name__)
CREATE_NO_WINDOW = 0x08000000

BROWSER_WORDS = {"navegador", "browser", "internet", "o navegador", "navegador de internet"}
BUILTINS: dict[str, dict] = {
    "explorador de arquivos": {"type": "command", "argv": ["explorer.exe"], "exe": ["explorer.exe"]},
    "explorer": {"type": "command", "argv": ["explorer.exe"], "exe": ["explorer.exe"]},
    "configuracoes": {"type": "uri", "uri": "ms-settings:"},
    "configuracoes do windows": {"type": "uri", "uri": "ms-settings:"},
    "configuracoes de som": {"type": "uri", "uri": "ms-settings:sound"},
    "bluetooth": {"type": "uri", "uri": "ms-settings:bluetooth"},
    "gerenciador de tarefas": {"type": "command", "argv": ["taskmgr.exe"], "exe": ["Taskmgr.exe"]},
    "bloco de notas": {"type": "command", "argv": ["notepad.exe"], "exe": ["notepad.exe", "Notepad.exe"]},
    "calculadora": {"type": "uri", "uri": "calculator:", "exe": ["CalculatorApp.exe", "Calculator.exe"]},
    "lixeira": {"type": "uri", "uri": "shell:RecycleBinFolder"},
    "steam": {"type": "uri", "uri": "steam://open/main", "exe": ["steam.exe"]},
}
FOLDER_SYNONYMS = {
    "downloads": ["downloads", "download", "baixados", "transferencias"],
    "documentos": ["documentos", "documents", "meus documentos"],
    "area de trabalho": ["area de trabalho", "desktop", "tela inicial"],
    "imagens": ["imagens", "fotos", "pictures"],
    "musicas": ["musicas", "musica", "music"],
    "videos": ["videos", "video"],
}


@dataclass
class AppEntry:
    name: str
    kind: str  # lnk | store | steam | alias | builtin
    launch: str
    exe: list[str] = field(default_factory=list)
    install_dir: str = ""
    norm: str = ""

    def __post_init__(self) -> None:
        if not self.norm:
            self.norm = words_to_digits(normalize(self.name))


class AppCatalog:
    """Índice de programas instalados, atualizado em segundo plano."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self._entries: list[AppEntry] = []
        self._lock = threading.Lock()
        self._cache = paths.cache_dir() / "apps.json"
        self._load_cache()

    # ---------------------------------------------------------------- índice
    def _load_cache(self) -> None:
        if self._cache.exists():
            try:
                data = json.loads(self._cache.read_text(encoding="utf-8"))
                self._entries = [AppEntry(**item) for item in data]
            except Exception:  # noqa: BLE001
                self._entries = []

    def refresh_async(self) -> None:
        threading.Thread(target=self.refresh, name="app-catalog", daemon=True).start()

    def refresh(self) -> int:
        entries: list[AppEntry] = []
        started = time.time()
        if self.settings.get("apps.scan_start_menu", True):
            entries += _scan_start_menu()
            entries += _scan_store_apps(entries)
        if self.settings.get("apps.scan_steam", True):
            for game in installed_games():
                entries.append(AppEntry(game.name, "steam", game.appid, install_dir=str(game.install_dir)))
        with self._lock:
            self._entries = entries
        try:
            self._cache.write_text(json.dumps([asdict(e) for e in entries], ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        log.info("Catálogo de apps: %d itens em %.1fs", len(entries), time.time() - started)
        return len(entries)

    def entries(self) -> list[AppEntry]:
        with self._lock:
            entries = list(self._entries)
        for alias, spec in (self.settings.get("apps.aliases", {}) or {}).items():
            entries.append(AppEntry(alias, "alias", json.dumps(spec, ensure_ascii=False),
                                    exe=list(spec.get("exe", []))))
        for name, spec in BUILTINS.items():
            entries.append(AppEntry(name, "builtin", json.dumps(spec), exe=list(spec.get("exe", []))))
        return entries

    def find(self, query: str, limit: int = 3) -> list[tuple[float, AppEntry]]:
        q = words_to_digits(normalize(query))
        scored = []
        for entry in self.entries():
            score = similar(q, entry.norm)
            if entry.kind in ("alias", "builtin") and score >= 0.85:
                score += 0.1  # atalhos do usuário têm prioridade
            if score >= 0.6:
                scored.append((score, entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[:limit]


def _start_menu_dirs() -> list[Path]:
    dirs = []
    for env in ("APPDATA", "PROGRAMDATA"):
        base = os.environ.get(env)
        if base:
            path = Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            if path.exists():
                dirs.append(path)
    return dirs


_SKIP_WORDS = ("uninstall", "desinstalar", "readme", "leia-me", "help", "ajuda", "website", "site da web")


def _scan_start_menu() -> list[AppEntry]:
    entries = []
    for directory in _start_menu_dirs():
        for lnk in directory.rglob("*.lnk"):
            name = lnk.stem
            if any(word in name.lower() for word in _SKIP_WORDS):
                continue
            target = lnk_target(lnk)
            exe = [Path(target).name] if target and target.lower().endswith(".exe") else []
            entries.append(AppEntry(name, "lnk", str(lnk), exe=exe))
    return entries


def _scan_store_apps(existing: list[AppEntry]) -> list[AppEntry]:
    """Lista apps do Menu Iniciar (inclui Microsoft Store) via Get-StartApps."""
    if sys.platform != "win32":
        return []
    known = {e.norm for e in existing}
    script = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=25, creationflags=CREATE_NO_WINDOW,
        )
        data = json.loads(out.stdout.decode("utf-8", errors="ignore") or "[]")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        log.warning("Get-StartApps indisponível", exc_info=True)
        return []
    if isinstance(data, dict):
        data = [data]
    entries = []
    for item in data:
        name, app_id = item.get("Name"), item.get("AppID")
        # AppIDs com "!" são apps empacotados (Store); os demais já vêm dos atalhos .lnk
        if name and app_id and "!" in app_id and normalize(name) not in known:
            entries.append(AppEntry(name, "store", app_id))
    return entries


# ------------------------------------------------------------- execução
def _open_uri(services, uri: str) -> None:
    if services.open_url:
        services.open_url(uri)
    elif sys.platform == "win32":
        os.startfile(uri)  # type: ignore[attr-defined]
    else:
        webbrowser.open(uri)


def launch_entry(services, entry: AppEntry) -> None:
    if entry.kind == "lnk":
        os.startfile(entry.launch)  # type: ignore[attr-defined]
    elif entry.kind == "store":
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{entry.launch}"], creationflags=CREATE_NO_WINDOW)
    elif entry.kind == "steam":
        _open_uri(services, f"steam://rungameid/{entry.launch}")
    elif entry.kind in ("alias", "builtin"):
        spec = json.loads(entry.launch)
        kind = spec.get("type")
        if kind == "url":
            _open_uri(services, spec["url"])
        elif kind == "uri":
            _open_uri(services, spec["uri"])
        elif kind == "steam":
            _open_uri(services, f"steam://rungameid/{spec['appid']}")
        elif kind == "store":
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{spec['appid']}"], creationflags=CREATE_NO_WINDOW)
        elif kind == "path":
            os.startfile(spec["path"])  # type: ignore[attr-defined]
        elif kind == "command":
            # Apenas comandos escritos pelo próprio usuário nas configurações.
            subprocess.Popen(spec["argv"], creationflags=CREATE_NO_WINDOW, cwd=spec.get("cwd"))
        else:
            raise ValueError(f"Tipo de atalho desconhecido: {kind}")


def _processes_for(entry: AppEntry) -> list:
    import psutil

    exe_names = {e.lower() for e in entry.exe}
    install_dir = entry.install_dir.lower() if entry.install_dir else ""
    found = []
    for proc in psutil.process_iter(["name", "exe"]):
        try:
            name = (proc.info.get("name") or "").lower()
            exe_path = (proc.info.get("exe") or "").lower()
            if (exe_names and name in exe_names) or (install_dir and exe_path.startswith(install_dir)):
                found.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


def _browser_entry() -> AppEntry | None:
    exe = win.default_browser_exe()
    if not exe:
        return None
    friendly = {"msedge.exe": "Microsoft Edge", "chrome.exe": "Google Chrome", "firefox.exe": "Firefox",
                "brave.exe": "Brave", "opera.exe": "Opera"}.get(Path(exe).name.lower(), Path(exe).stem)
    return AppEntry(friendly, "alias", json.dumps({"type": "command", "argv": [exe]}), exe=[Path(exe).name])


def _catalog(services) -> AppCatalog:
    if services.apps is None:
        services.apps = AppCatalog(services.settings)
    return services.apps


def resolve_target(services, target: str) -> AppEntry | None:
    t = normalize(target)
    if t in BROWSER_WORDS:
        return _browser_entry()
    matches = _catalog(services).find(t)
    return matches[0][1] if matches else None


@action("open_target", "Abre um programa, jogo, site conhecido, planilha configurada ou pasta pelo nome.",
        props(["target"], target=STR | {"description": "Nome falado do programa/jogo/site, ex.: 'navegador', 'storm 4'."}))
def open_target(services, params):
    target = (params.get("target") or "").strip()
    if not target:
        return ActionResult.fail("O que devo abrir?", display="Diga o nome do programa.")
    t = normalize(target)
    if t in ("whatsapp", "whatsapp business", "whats", "zap", "wpp") and services.whatsapp:
        return services.whatsapp.open_app()
    folder = _match_folder(services, t)
    entry = resolve_target(services, target)
    if entry is None and folder:
        return open_folder(services, {"folder": target})
    if entry is None and services.excel is not None:
        wb = services.excel.find_workbook(target, strict=True)
        if wb:
            return services.excel.open_workbook(wb, services)
    if entry is None:
        return ActionResult.fail(f"Não encontrei {target} entre os programas instalados.",
                                 display="Dica: adicione um atalho em Configurações > Comandos.")
    launch_entry(services, entry)
    services.context.remember(last_app=entry.name)
    undo = None
    if entry.exe or entry.install_dir:
        undo = lambda: _close_entry(services, entry, force=False).say  # noqa: E731
    return ActionResult(f"Abrindo {entry.name}.", undo=undo, undo_label=f"abrir {entry.name}")


def _close_entry(services, entry: AppEntry, force: bool) -> ActionResult:
    procs = _processes_for(entry)
    if not procs:
        if entry.kind in ("alias", "builtin") and '"url"' in entry.launch:
            return ActionResult.fail(
                f"{entry.name} abre no navegador; não fecho abas por segurança. Posso fechar o navegador inteiro, se quiser.")
        return ActionResult.fail(f"{entry.name} não parece estar aberto.")
    pids = {p.pid for p in procs}
    if force:
        for proc in procs:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
        return ActionResult(f"{entry.name} encerrado à força.")
    closed = win.close_windows_of_pids(pids)
    if closed == 0:
        return ActionResult.fail(
            f"{entry.name} está rodando sem janela aberta. Para encerrar, diga: fecha {entry.name} à força.")
    return ActionResult(f"Fechando {entry.name}.",
                        undo=lambda: (launch_entry(services, entry), f"Reabrindo {entry.name}.")[1],
                        undo_label=f"fechar {entry.name}")


def _close_confirm_text(params) -> str:
    target = params.get("target", "")
    if params.get("force"):
        return f"Encerrar {target} à força pode perder dados não salvos. Confirma?"
    return f"Confirma fechar {target}?"


@action("close_app", "Fecha um programa ou jogo aberto de forma normal (o app pode pedir para salvar).",
        props(["target"], target=STR, force=BOOL | {"description": "Encerrar à força. Exige confirmação."}))
def close_app(services, params):
    target = params.get("target", "")
    force = bool(params.get("force"))
    needs_confirmation = force or services.settings.get("apps.close_requires_confirmation", False)
    if needs_confirmation and not params.get("_confirmed"):
        from .base import PendingAction

        question = _close_confirm_text(params)
        return ActionResult(question, expects_reply=True, pending=PendingAction(
            question=question, execute=lambda: close_app(services, {**params, "_confirmed": True})))
    if target == "@foreground":
        pid = win.foreground_pid()
        if not pid or pid == os.getpid():
            return ActionResult.fail("Não identifiquei a janela em primeiro plano.")
        win.close_windows_of_pids({pid})
        return ActionResult("Fechando a janela atual.")
    entry = resolve_target(services, target)
    if entry is None:
        window = _find_window(target)
        if window:
            win.close_windows_of_pids({window.pid})
            return ActionResult(f"Fechando {window.title[:40]}.")
        return ActionResult.fail(f"Não encontrei {target} aberto.")
    return _close_entry(services, entry, force)


def _find_window(target: str):
    import psutil

    t = words_to_digits(normalize(target))
    best = None
    for window in win.list_windows():
        if window.pid == os.getpid():
            continue
        try:
            proc_name = normalize(Path(psutil.Process(window.pid).name()).stem)
        except Exception:  # noqa: BLE001
            proc_name = ""
        score = max(similar(t, normalize(window.title)), similar(t, proc_name))
        if score >= 0.6 and (best is None or score > best[0]):
            best = (score, window)
    return best[1] if best else None


@action("switch_window", "Traz para frente a janela de um programa já aberto.", props(["target"], target=STR))
def switch_window(services, params):
    target = params.get("target", "")
    if normalize(target) in BROWSER_WORDS:
        browser = _browser_entry()
        if browser:
            target = Path(browser.exe[0]).stem
    window = _find_window(target)
    if not window:
        return ActionResult.fail(f"Não encontrei uma janela de {target}.")
    win.focus_window(window.hwnd)
    return ActionResult(f"Mostrando {window.title[:40]}.")


@action("show_desktop", "Minimiza todas as janelas e mostra a área de trabalho.")
def show_desktop(services, params):
    if sys.platform != "win32":
        return ActionResult.fail("Disponível apenas no Windows.")
    subprocess.Popen(["explorer.exe", "shell:::{3080F90D-D7AD-11D9-BD98-0000947B0257}"], creationflags=CREATE_NO_WINDOW)
    return ActionResult("Área de trabalho.")


# ---------------------------------------------------------------- pastas
def _match_folder(services, name: str) -> Path | None:
    t = normalize(name)
    for alias, path in (services.settings.get("folders.aliases", {}) or {}).items():
        if similar(t, normalize(alias)) >= 0.85 and Path(path).exists():
            return Path(path)
    for key, synonyms in FOLDER_SYNONYMS.items():
        if any(t == s or t == f"pasta {s}" for s in synonyms):
            return win.known_folder(key)
    if t in ("onedrive", "one drive"):
        return win.onedrive_folder()
    return None


@action("open_folder", "Abre uma pasta (downloads, documentos, área de trabalho, imagens ou apelidos configurados).",
        props(["folder"], folder=STR))
def open_folder(services, params):
    name = params.get("folder", "")
    path = _match_folder(services, name)
    if not path:
        return ActionResult.fail(f"Não conheço a pasta {name}. Você pode cadastrá-la nas configurações.")
    _open_uri(services, str(path))
    return ActionResult(f"Abrindo a pasta {name}.")


def _search_roots(services) -> list[Path]:
    roots = [Path(p) for p in services.settings.get("folders.search_roots", []) or [] if Path(p).exists()]
    if roots:
        return roots
    for key in ("area de trabalho", "documentos", "downloads"):
        folder = win.known_folder(key)
        if folder and folder not in roots:
            roots.append(folder)
    onedrive = win.onedrive_folder()
    if onedrive and onedrive not in roots:
        roots.append(onedrive)
    return roots


_SKIP_DIRS = {"node_modules", ".git", "appdata", "$recycle.bin", "__pycache__", ".venv", "venv"}


def search_files(roots: list[Path], query: str, seconds: float = 4.0, limit: int = 8) -> list[tuple[float, Path]]:
    q = words_to_digits(normalize(query))
    deadline = time.time() + seconds
    results: list[tuple[float, Path]] = []
    queue = list(roots)
    while queue and time.time() < deadline:
        folder = queue.pop(0)
        try:
            with os.scandir(folder) as it:
                for item in it:
                    if item.name.startswith(".") or item.name.lower() in _SKIP_DIRS:
                        continue
                    if item.is_dir(follow_symlinks=False):
                        queue.append(Path(item.path))
                        continue
                    score = similar(q, words_to_digits(normalize(Path(item.name).stem)))
                    if score >= 0.6:
                        results.append((score, Path(item.path)))
        except OSError:
            continue
    results.sort(key=lambda r: (r[0], r[1].stat().st_mtime if r[1].exists() else 0), reverse=True)
    return results[:limit]


@action("file_search", "Procura arquivos pelo nome nas pastas do usuário.", props(["query"], query=STR))
def file_search(services, params):
    query = params.get("query", "")
    found = search_files(_search_roots(services), query, services.settings.get("folders.search_seconds", 4))
    if not found:
        return ActionResult.fail(f"Não encontrei arquivos parecidos com {query}.")
    services.context.remember(files=[str(p) for _, p in found])
    listing = "\n".join(f"{i + 1}. {p.name} - {p.parent}" for i, (_, p) in enumerate(found))
    if len(found) == 1 or found[0][0] - found[1][0] > 0.15:
        return ActionResult(f"Encontrei {found[0][1].name}. Quer que eu abra?", display=listing,
                            expects_reply=True, pending=_open_file_pending(services, found[0][1]))
    return ActionResult(f"Encontrei {len(found)} arquivos. O primeiro é {found[0][1].name}. Diga, por exemplo, abre o primeiro.",
                        display=listing)


def _open_file_pending(services, path: Path):
    from .base import PendingAction

    def execute() -> ActionResult:
        _open_uri(services, str(path))
        return ActionResult(f"Abrindo {path.name}.")

    return PendingAction(question=f"Abrir {path.name}?", execute=execute)


@action("open_file_result", "Abre um arquivo da última pesquisa pelo número da lista (1 = primeiro).",
        props(["index"], index={"type": "integer"}))
def open_file_result(services, params):
    files = services.context.get("files") or []
    index = int(params.get("index", 1)) - 1
    if not files or not (0 <= index < len(files)):
        return ActionResult.fail("Não há resultado de pesquisa com esse número.")
    path = Path(files[index])
    _open_uri(services, str(path))
    return ActionResult(f"Abrindo {path.name}.")


@action("open_url", "Abre um endereço da web no navegador padrão.", props(["url"], url=STR))
def open_url(services, params):
    url = params.get("url", "")
    if not url.startswith(("https://", "http://")):
        return ActionResult.fail("Só abro endereços que começam com http ou https.")
    _open_uri(services, url)
    return ActionResult("Abrindo no navegador.")


@action("refresh_apps", "Atualiza a lista de programas e jogos instalados.")
def refresh_apps(services, params):
    count = _catalog(services).refresh()
    return ActionResult(f"Lista atualizada: {count} programas e jogos encontrados.")
