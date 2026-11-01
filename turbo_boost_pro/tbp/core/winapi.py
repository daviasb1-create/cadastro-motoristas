"""Chamadas nativas do Windows via ctypes (admin, privilégios, janelas, broadcast)."""
from __future__ import annotations

import ctypes
import os
import sys

from ..config import IS_WINDOWS
from ..utils import log

if IS_WINDOWS:
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")


def is_admin() -> bool:
    if not IS_WINDOWS:
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin(extra_args: list[str] | None = None) -> bool:
    """Reabre o aplicativo elevado (UAC). Retorna True se a nova instância foi iniciada."""
    if not IS_WINDOWS:
        return False
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, list(sys.argv[1:])
    else:
        exe = sys.executable.replace("python.exe", "pythonw.exe")
        if not os.path.exists(exe):
            exe = sys.executable
        params = [os.path.abspath(sys.argv[0])] + sys.argv[1:]
    params += extra_args or []
    param_str = " ".join(f'"{p}"' for p in params)
    rc = shell32.ShellExecuteW(None, "runas", exe, param_str, None, 1)
    return rc > 32


# ---------------------------------------------------------------- privilégios
if IS_WINDOWS:
    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class LUID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]

    class TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1)]


def enable_privilege(name: str) -> bool:
    """Habilita um privilégio no token do processo atual (ex.: SeProfileSingleProcessPrivilege)."""
    if not IS_WINDOWS:
        return False
    TOKEN_ADJUST_PRIVILEGES, TOKEN_QUERY, SE_PRIVILEGE_ENABLED = 0x20, 0x8, 0x2
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
                                     ctypes.byref(token)):
        return False
    try:
        luid = LUID()
        if not advapi32.LookupPrivilegeValueW(None, name, ctypes.byref(luid)):
            return False
        tp = TOKEN_PRIVILEGES(1, (LUID_AND_ATTRIBUTES * 1)(LUID_AND_ATTRIBUTES(luid, SE_PRIVILEGE_ENABLED)))
        advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(tp), 0, None, None)
        return ctypes.get_last_error() == 0
    finally:
        kernel32.CloseHandle(token)


# ---------------------------------------------------------------- janelas
def foreground_pid() -> int | None:
    if not IS_WINDOWS:
        return None
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value or None


def broadcast_settings_change():
    """Notifica o Explorer/apps que configurações de sistema mudaram (efeitos visuais, etc.)."""
    if not IS_WINDOWS:
        return
    HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x1A, 0x2
    result = ctypes.c_ulong()
    for param in ("Environment", "WindowMetrics", "Policy", "ImmersiveColorSet"):
        user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, param, SMTO_ABORTIFHUNG, 1000,
                                   ctypes.byref(result))


def apply_mouse_settings_live():
    """Recarrega as configurações de mouse do registro sem precisar fazer logoff."""
    if not IS_WINDOWS:
        return
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Mouse") as k:
            speed = int(winreg.QueryValueEx(k, "MouseSpeed")[0])
            t1 = int(winreg.QueryValueEx(k, "MouseThreshold1")[0])
            t2 = int(winreg.QueryValueEx(k, "MouseThreshold2")[0])
        arr = (ctypes.c_int * 3)(t1, t2, speed)
        SPI_SETMOUSE, SPIF_UPDATEINIFILE, SPIF_SENDCHANGE = 0x0004, 0x01, 0x02
        user32.SystemParametersInfoW(SPI_SETMOUSE, 0, arr, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)
    except Exception as e:  # pragma: no cover
        log.warning("Falha ao aplicar mouse: %s", e)


def apply_visual_settings_live():
    """Aplica imediatamente animações de janela/menus conforme o registro."""
    if not IS_WINDOWS:
        return
    try:
        import winreg

        class ANIMATIONINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("iMinAnimate", ctypes.c_int)]

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop\WindowMetrics") as k:
            min_anim = int(winreg.QueryValueEx(k, "MinAnimate")[0])
        ai = ANIMATIONINFO(ctypes.sizeof(ANIMATIONINFO), min_anim)
        SPI_SETANIMATION = 0x0049
        user32.SystemParametersInfoW(SPI_SETANIMATION, ctypes.sizeof(ai), ctypes.byref(ai), 0x3)
    except Exception:
        pass
    broadcast_settings_change()


# ---------------------------------------------------------------- timer
_timer_active = False


def set_timer_resolution(enable: bool, hundred_ns: int = 5000) -> float | None:
    """Ativa/desativa a resolução de timer de 0,5 ms enquanto o app estiver aberto.
    O efeito termina automaticamente quando o processo fecha (totalmente reversível)."""
    global _timer_active
    if not IS_WINDOWS:
        return None
    current = ctypes.c_ulong()
    ntdll.NtSetTimerResolution(ctypes.c_ulong(hundred_ns), ctypes.c_bool(enable), ctypes.byref(current))
    _timer_active = enable
    return current.value / 10000.0


def timer_resolution_active() -> bool:
    return _timer_active


def restart_explorer():
    from ..utils import run
    if not IS_WINDOWS:
        return
    run(["taskkill", "/f", "/im", "explorer.exe"])
    import subprocess
    subprocess.Popen(["explorer.exe"], close_fds=True)
