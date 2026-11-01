"""Limpeza inteligente: analisa primeiro (mostra o espaço a liberar), depois limpa.

Segurança:
- Somente caminhos dentro das pastas declaradas em cada categoria são apagados (verificação
  de prefixo + lista de pastas proibidas do sistema).
- Arquivos temporários recentes (< 24 h) são preservados: podem pertencer a instaladores em uso.
- Arquivos em uso são ignorados silenciosamente.
- Arquivos grandes do usuário NUNCA são apagados definitivamente: vão para a Lixeira.
- Prefetch e Windows.old NÃO são limpos (apagar prefetch deixa o PC mais lento; Windows.old é
  a única forma de voltar à versão anterior do Windows).
"""
from __future__ import annotations

import ctypes
import fnmatch
import glob
import os
import stat
import time
from dataclasses import dataclass, field
from typing import Callable

from ..config import IS_WINDOWS
from ..utils import fmt_bytes, log, powershell, run

E = os.environ.get
WIN = E("SystemRoot", r"C:\Windows")
LOCAL = E("LOCALAPPDATA", "")
LOCALLOW = os.path.join(os.path.dirname(LOCAL), "LocalLow") if LOCAL else ""
ROAMING = E("APPDATA", "")
PROGDATA = E("ProgramData", r"C:\ProgramData")
USERPROFILE = E("USERPROFILE", os.path.expanduser("~"))

FORBIDDEN = [os.path.join(WIN, d).lower() for d in ("System32", "SysWOW64", "WinSxS", "Boot", "Fonts",
                                                     "Installer", "servicing", "assembly", "Prefetch")]


@dataclass
class Category:
    id: str
    name: str
    description: str
    group: str
    paths: list[str] = field(default_factory=list)  # pastas (aceita glob)
    patterns: list[str] = field(default_factory=lambda: ["*"])
    min_age_h: float = 0
    admin: bool = False
    default: bool = True
    note: str = ""
    scan_fn: Callable[[], tuple[int, int]] | None = None
    clean_fn: Callable[[], tuple[int, str]] | None = None
    recursive: bool = True


@dataclass
class ScanResult:
    size: int = 0
    count: int = 0
    files: list[str] = field(default_factory=list)


def _expand(paths: list[str]) -> list[str]:
    out = []
    for p in paths:
        if not p or not os.path.isabs(p):  # variável de ambiente ausente: ignora
            continue
        out += [x for x in glob.glob(p) if os.path.isdir(x)]
    return out


def is_safe(path: str, roots: list[str]) -> bool:
    lp = os.path.normcase(os.path.abspath(path))
    if any(lp.startswith(f) for f in FORBIDDEN):
        return False
    return any(lp.startswith(os.path.normcase(os.path.abspath(r)) + os.sep) for r in roots)


def _walk(root: str, patterns: list[str], min_age_h: float, recursive: bool, res: ScanResult):
    cutoff = time.time() - min_age_h * 3600
    try:
        it = os.scandir(root)
    except OSError:
        return
    with it:
        for e in it:
            try:
                if e.is_symlink():
                    continue
                if e.is_dir(follow_symlinks=False):
                    if recursive:
                        _walk(e.path, patterns, min_age_h, recursive, res)
                    continue
                if patterns != ["*"] and not any(fnmatch.fnmatch(e.name.lower(), p) for p in patterns):
                    continue
                st = e.stat(follow_symlinks=False)
                if min_age_h and st.st_mtime > cutoff:
                    continue
                res.size += st.st_size
                res.count += 1
                res.files.append(e.path)
            except OSError:
                continue


# ------------------------------------------------------------------ especiais
def _recycle_scan() -> tuple[int, int]:
    if not IS_WINDOWS:
        return 0, 0

    class SHQUERYRBINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]
    info = SHQUERYRBINFO(ctypes.sizeof(SHQUERYRBINFO), 0, 0)
    ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
    return info.i64Size, info.i64NumItems


def _recycle_clean() -> tuple[int, str]:
    size, _ = _recycle_scan()
    if IS_WINDOWS:
        ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x1 | 0x2 | 0x4)
    return size, "Lixeira esvaziada."


def _dir_size(path: str) -> tuple[int, int]:
    r = ScanResult()
    _walk(path, ["*"], 0, True, r)
    return r.size, r.count


def _wu_scan():
    return _dir_size(os.path.join(WIN, "SoftwareDistribution", "Download"))


def _wu_clean() -> tuple[int, str]:
    """Para temporariamente Windows Update/BITS, limpa downloads já instalados e reinicia os serviços."""
    size, _ = _wu_scan()
    run(["net", "stop", "wuauserv", "/y"], timeout=60)
    run(["net", "stop", "bits", "/y"], timeout=60)
    try:
        root = os.path.join(WIN, "SoftwareDistribution", "Download")
        res = ScanResult()
        _walk(root, ["*"], 0, True, res)
        freed = _delete_files(res.files, [root])
    finally:
        run(["net", "start", "bits"], timeout=60)
        run(["net", "start", "wuauserv"], timeout=60)
    return freed, "Cache do Windows Update limpo (serviços reiniciados)."


def _do_scan():
    return _dir_size(os.path.join(WIN, r"ServiceProfiles\NetworkService\AppData\Local\Microsoft\Windows"
                                       r"\DeliveryOptimization\Cache"))


def _do_clean():
    size, _ = _do_scan()
    r = powershell("Delete-DeliveryOptimizationCache -Force")
    return (size if r.returncode == 0 else 0), "Cache de Otimização de Entrega limpo."


def _dism_scan():
    return 0, 0  # a análise do DISM leva minutos; o tamanho é informado após a limpeza


def _dism_clean():
    before = _free_space()
    r = run(["dism.exe", "/Online", "/Cleanup-Image", "/StartComponentCleanup"], timeout=3600)
    freed = max(0, _free_space() - before)
    ok = r.returncode == 0
    return freed, ("Componentes antigos de atualizações removidos." if ok else
                   f"DISM retornou código {r.returncode}.")


def _free_space() -> int:
    import shutil
    return shutil.disk_usage(os.environ.get("SystemDrive", "C:") + os.sep).free


# ------------------------------------------------------------------ catálogo
def _browser_paths() -> list[str]:
    paths = []
    for base in (r"Google\Chrome", r"Microsoft\Edge", r"BraveSoftware\Brave-Browser", r"Vivaldi"):
        for sub in ("Cache", "Code Cache", "GPUCache", "Service Worker\\CacheStorage"):
            paths.append(os.path.join(LOCAL, base, "User Data", "*", sub))
    paths.append(os.path.join(LOCAL, r"Mozilla\Firefox\Profiles\*\cache2"))
    paths.append(os.path.join(ROAMING, r"Opera Software\Opera*\Cache"))
    paths.append(os.path.join(LOCAL, r"Opera Software\Opera*\Cache"))
    return paths


CATEGORIES: list[Category] = [
    Category("user_temp", "Arquivos temporários do usuário", "Pasta %TEMP% (arquivos com mais de 24 h).",
             "Sistema", [E("TEMP", "")], min_age_h=24),
    Category("win_temp", "Arquivos temporários do Windows", r"C:\Windows\Temp (mais de 24 h).", "Sistema",
             [os.path.join(WIN, "Temp")], min_age_h=24, admin=True),
    Category("thumbs", "Cache de miniaturas", "Miniaturas de imagens/vídeos do Explorer (recriadas sob demanda).",
             "Sistema", [os.path.join(LOCAL, r"Microsoft\Windows\Explorer")], patterns=["thumbcache_*.db",
                                                                                     "iconcache_*.db"],
             recursive=False),
    Category("wer", "Relatórios de erros e despejos de memória", "Relatórios do WER e arquivos .dmp de falhas.",
             "Sistema", [os.path.join(LOCAL, r"Microsoft\Windows\WER"), os.path.join(LOCAL, "CrashDumps"),
                         os.path.join(PROGDATA, r"Microsoft\Windows\WER"), os.path.join(WIN, "Minidump"),
                         os.path.join(WIN, "LiveKernelReports")], admin=True),
    Category("logs", "Logs antigos do Windows", "Arquivos .log/.etl com mais de 7 dias.", "Sistema",
             [os.path.join(WIN, "Logs"), os.path.join(WIN, r"Panther")], patterns=["*.log", "*.etl", "*.cab"],
             min_age_h=24 * 7, admin=True),
    Category("recycle", "Lixeira", "Esvazia a Lixeira de todas as unidades.", "Sistema",
             scan_fn=_recycle_scan, clean_fn=_recycle_clean, default=False),
    Category("wu_cache", "Downloads do Windows Update", "Instaladores de atualizações JÁ aplicadas. O Windows "
             "Update é parado só durante a limpeza.", "Atualizações", admin=True,
             scan_fn=_wu_scan, clean_fn=_wu_clean),
    Category("delivery_opt", "Cache de Otimização de Entrega", "Cópias de atualizações compartilhadas.",
             "Atualizações", admin=True, scan_fn=_do_scan, clean_fn=_do_clean),
    Category("dism", "Resíduos de atualizações antigas (WinSxS)", "Remove versões substituídas de componentes "
             "via DISM (método oficial da Microsoft). Pode levar vários minutos.", "Atualizações", admin=True,
             default=False, scan_fn=_dism_scan, clean_fn=_dism_clean,
             note="Tamanho exato calculado após a execução."),
    Category("browsers", "Cache de navegadores", "Chrome, Edge, Brave, Firefox, Opera, Vivaldi. Feche os "
             "navegadores para limpar tudo. Senhas, histórico e cookies NÃO são apagados.", "Aplicativos",
             _browser_paths()),
    Category("apps_cache", "Cache de aplicativos", "Discord, Spotify, Teams, Steam (web), Epic, Office.",
             "Aplicativos",
             [os.path.join(ROAMING, r"discord\Cache"), os.path.join(ROAMING, r"discord\Code Cache"),
              os.path.join(ROAMING, r"discord\GPUCache"), os.path.join(LOCAL, r"Spotify\Data"),
              os.path.join(LOCAL, r"Packages\MSTeams_*\LocalCache\Microsoft\MSTeams\EBWebView\Default\Cache"),
              os.path.join(ROAMING, r"Microsoft\Teams\Cache"), os.path.join(LOCAL, r"Steam\htmlcache"),
              os.path.join(LOCAL, r"EpicGamesLauncher\Saved\webcache*"),
              os.path.join(LOCAL, r"Microsoft\Office\16.0\OfficeFileCache"),
              os.path.join(LOCAL, r"Microsoft\Windows\INetCache")]),
    Category("shader_dx", "Cache de shaders DirectX", "Cache de shaders do Windows. É reconstruído "
             "automaticamente ao abrir cada jogo.", "Shaders", [os.path.join(LOCAL, "D3DSCache")], default=False,
             note="Após limpar, a 1ª partida de cada jogo pode ter travadas enquanto os shaders recompilam."),
    Category("shader_gpu", "Cache de shaders da GPU (NVIDIA/AMD/Intel)", "Útil após atualizar drivers ou "
             "quando um jogo apresenta artefatos/travadas por cache corrompido.", "Shaders",
             [os.path.join(LOCAL, r"NVIDIA\DXCache"), os.path.join(LOCAL, r"NVIDIA\GLCache"),
              os.path.join(LOCALLOW, r"NVIDIA\PerDriverVersion\DXCache"),
              os.path.join(LOCALLOW, r"NVIDIA\PerDriverVersion\GLCache"),
              os.path.join(LOCAL, r"AMD\DxCache"), os.path.join(LOCAL, r"AMD\DxcCache"),
              os.path.join(LOCAL, r"AMD\VkCache"), os.path.join(LOCAL, r"AMD\GLCache"),
              os.path.join(LOCALLOW, r"Intel\ShaderCache")], default=False,
             note="Reconstrução automática pelo driver na próxima execução de cada jogo."),
]

CATEGORIES_BY_ID = {c.id: c for c in CATEGORIES}


def scan(cat: Category) -> ScanResult:
    res = ScanResult()
    if not IS_WINDOWS:
        return res
    if cat.scan_fn:
        res.size, res.count = cat.scan_fn()
        return res
    for root in _expand(cat.paths):
        _walk(root, [p.lower() for p in cat.patterns], cat.min_age_h, cat.recursive, res)
    return res


def _delete_files(files: list[str], roots: list[str]) -> int:
    freed = 0
    for f in files:
        if not is_safe(f, roots):
            log.warning("Ignorado (fora da área segura): %s", f)
            continue
        try:
            size = os.path.getsize(f)
            try:
                os.remove(f)
            except PermissionError:
                os.chmod(f, stat.S_IWRITE)
                os.remove(f)
            freed += size
        except OSError:
            continue
    # remove subpastas vazias (nunca a pasta raiz da categoria)
    for root in roots:
        for dirpath, _dirs, _files in sorted(os.walk(root, topdown=False), key=lambda x: -len(x[0])):
            if os.path.normcase(dirpath) != os.path.normcase(root) and is_safe(dirpath, [root]):
                try:
                    os.rmdir(dirpath)
                except OSError:
                    pass
    return freed


def clean(cat: Category, result: ScanResult | None = None) -> tuple[int, str]:
    if not IS_WINDOWS:
        return 0, "Disponível apenas no Windows."
    if cat.clean_fn:
        return cat.clean_fn()
    roots = _expand(cat.paths)
    if result is None:
        result = ScanResult()
        for root in roots:
            _walk(root, [p.lower() for p in cat.patterns], cat.min_age_h, cat.recursive, result)
    freed = _delete_files(result.files, roots)
    skipped = result.size - freed
    msg = f"{cat.name}: {fmt_bytes(freed)} liberados"
    if skipped > 1024 * 1024:
        msg += f" ({fmt_bytes(skipped)} em uso foram mantidos)"
    return freed, msg


# ------------------------------------------------------------------ arquivos grandes
OLD_INSTALLER_EXT = {".iso", ".exe", ".msi", ".zip", ".rar", ".7z"}


def find_large_files(min_mb: int = 200, folders: list[str] | None = None, limit: int = 300,
                     progress: Callable[[str], None] | None = None) -> list[dict]:
    """Procura arquivos grandes nas pastas do usuário. Marca como 'provavelmente desnecessário'
    instaladores e compactados antigos na pasta Downloads."""
    folders = folders or [os.path.join(USERPROFILE, d) for d in ("Downloads", "Desktop", "Documents",
                                                                 "Videos", "Music", "Pictures")]
    min_size = min_mb * 1024 * 1024
    now = time.time()
    found = []
    downloads = os.path.normcase(os.path.join(USERPROFILE, "Downloads"))
    for folder in folders:
        if progress:
            progress(folder)
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d.lower() != "appdata"]
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                if st.st_size < min_size:
                    continue
                ext = os.path.splitext(fn)[1].lower()
                age_days = (now - max(st.st_atime, st.st_mtime)) / 86400
                unneeded = (os.path.normcase(p).startswith(downloads) and ext in OLD_INSTALLER_EXT
                            and age_days > 30)
                found.append({"path": p, "size": st.st_size, "age_days": int(age_days), "ext": ext,
                              "unneeded": unneeded})
    found.sort(key=lambda f: (not f["unneeded"], -f["size"]))
    return found[:limit]


def send_to_recycle_bin(paths: list[str]) -> tuple[int, list[str]]:
    from send2trash import send2trash
    freed, errors = 0, []
    for p in paths:
        try:
            size = os.path.getsize(p)
            send2trash(p)
            freed += size
        except Exception as e:
            errors.append(f"{os.path.basename(p)}: {e}")
    return freed, errors
