"""Funções nativas do Windows via ctypes (sem dependências extras).

Todas as funções retornam valores neutros em outros sistemas operacionais,
o que permite rodar os testes automatizados fora do Windows.
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)
IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32")

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]

WM_CLOSE = 0x0010
GW_OWNER = 4
SW_RESTORE = 9

# --------------------------------------------------------------- pastas
KNOWN_FOLDERS = {
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "documentos": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "area de trabalho": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "imagens": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "musicas": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
    "videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
}

_FALLBACK_FOLDERS = {
    "downloads": "Downloads",
    "documentos": "Documents",
    "area de trabalho": "Desktop",
    "imagens": "Pictures",
    "musicas": "Music",
    "videos": "Videos",
}


def known_folder(name: str) -> Path | None:
    """Retorna o caminho real de uma pasta conhecida (respeita redirecionamento do OneDrive)."""
    if IS_WINDOWS and name in KNOWN_FOLDERS:
        try:
            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", wintypes.BYTE * 8)]

            raw = uuid.UUID(KNOWN_FOLDERS[name])
            guid = GUID(raw.fields[0], raw.fields[1], raw.fields[2],
                        (wintypes.BYTE * 8).from_buffer_copy(raw.bytes[8:]))
            out = ctypes.c_wchar_p()
            shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(out))
            path = Path(out.value) if out.value else None
            ole32.CoTaskMemFree(out)
            if path and path.exists():
                return path
        except Exception:  # noqa: BLE001
            log.debug("SHGetKnownFolderPath falhou para %s", name, exc_info=True)
    fallback = _FALLBACK_FOLDERS.get(name)
    if fallback:
        path = Path.home() / fallback
        return path if path.exists() else None
    return None


def onedrive_folder() -> Path | None:
    for var in ("OneDriveCommercial", "OneDrive", "OneDriveConsumer"):
        value = os.environ.get(var)
        if value and Path(value).exists():
            return Path(value)
    return None


# -------------------------------------------------------------- janelas
@dataclass
class WindowInfo:
    hwnd: int
    title: str
    pid: int


def list_windows() -> list[WindowInfo]:
    """Janelas visíveis de nível superior, com título."""
    if not IS_WINDOWS:
        return []
    result: list[WindowInfo] = []

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, GW_OWNER):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        result.append(WindowInfo(int(hwnd), buf.value, int(pid.value)))
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return result


def close_windows_of_pids(pids: set[int]) -> int:
    """Envia WM_CLOSE (fechamento normal, o app pode pedir para salvar)."""
    count = 0
    for win in list_windows():
        if win.pid in pids:
            user32.PostMessageW(win.hwnd, WM_CLOSE, 0, 0)
            count += 1
    return count


def focus_window(hwnd: int) -> bool:
    if not IS_WINDOWS:
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    # O Windows só permite trocar o foco se o processo "recebeu entrada";
    # simular a tecla ALT libera a troca de forma documentada pela comunidade.
    VK_MENU, KEYEVENTF_KEYUP = 0x12, 0x0002
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    user32.BringWindowToTop(hwnd)
    return bool(user32.SetForegroundWindow(hwnd))


def foreground_pid() -> int | None:
    if not IS_WINDOWS:
        return None
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


# ------------------------------------------------- tela cheia / "ocupado"
QUNS = {
    1: "not_present", 2: "busy", 3: "d3d_fullscreen", 4: "presentation",
    5: "accepts_notifications", 6: "quiet_time", 7: "app",
}


def user_notification_state() -> str:
    """Estado informado pelo Windows (detecta jogos em tela cheia exclusiva)."""
    if not IS_WINDOWS:
        return "accepts_notifications"
    state = ctypes.c_int()
    try:
        if shell32.SHQueryUserNotificationState(ctypes.byref(state)) == 0:
            return QUNS.get(state.value, "unknown")
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def is_fullscreen_app_running() -> bool:
    return user_notification_state() in ("busy", "d3d_fullscreen", "presentation", "app")


# ------------------------------------------------ inicialização automática
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "JarvisAssistente"


def autostart_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else exe
    launcher = Path(__file__).resolve().parents[2] / "run_jarvis.pyw"
    return f'"{interpreter}" "{launcher}" --minimized'


def set_autostart(enabled: bool) -> bool:
    """Grava em HKCU (não exige administrador)."""
    if not IS_WINDOWS:
        return False
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass
    return True


def is_autostart_enabled() -> bool:
    if not IS_WINDOWS:
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_VALUE)
            return True
    except FileNotFoundError:
        return False


# ---------------------------------------------------------- instância única
class SingleInstance:
    """Mutex nomeado: impede duas cópias do JARVIS disputando o microfone."""

    def __init__(self, name: str = "Local\\JarvisAssistenteMutex"):
        self.handle = None
        self.already_running = False
        if IS_WINDOWS:
            self.handle = kernel32.CreateMutexW(None, False, name)
            self.already_running = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
        else:
            import fcntl
            import tempfile

            self._file = open(Path(tempfile.gettempdir()) / "jarvis.lock", "w")  # noqa: SIM115
            try:
                fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.already_running = True


# ------------------------------------------------------------ navegador
def default_browser_exe() -> str | None:
    """Executável do navegador padrão (para abrir e fechar 'o navegador')."""
    if not IS_WINDOWS:
        return None
    import shlex
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice",
        ) as key:
            prog_id = winreg.QueryValueEx(key, "ProgId")[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{prog_id}\shell\open\command") as key:
            command = winreg.QueryValueEx(key, "")[0]
        exe = shlex.split(command, posix=False)[0].strip('"')
        return exe if Path(exe).exists() else None
    except OSError:
        return None
