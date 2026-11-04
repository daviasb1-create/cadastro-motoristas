"""Integração com o sistema operacional: privilégios, elevação sob demanda e inicialização com o Windows.

Tudo aqui funciona sem administrador. A elevação (UAC) só é solicitada quando o usuário
aciona uma função que realmente precisa dela (ex.: criar regra de firewall para o DNS local).
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path

from netvision import APP_ID
from netvision.core.paths import is_frozen, is_windows

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
CREATE_NO_WINDOW = 0x08000000


def is_admin() -> bool:
    if is_windows():
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False
    return hasattr(os, "geteuid") and os.geteuid() == 0


def run_hidden(args: list[str], timeout: float = 15.0) -> str:
    """Executa um comando sem abrir janela de console e devolve a saída (texto)."""
    kwargs = {}
    if is_windows():
        kwargs["creationflags"] = CREATE_NO_WINDOW
    try:
        out = subprocess.run(args, capture_output=True, timeout=timeout, **kwargs)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    raw = out.stdout or b""
    for enc in ("utf-8", "cp850", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _launch_command() -> tuple[str, str]:
    """Executável e argumentos que reabrem este aplicativo."""
    if is_frozen():
        return sys.executable, ""
    script = Path(sys.argv[0]).resolve()
    pyw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pyw if pyw.exists() else sys.executable)
    return exe, f'"{script}"'


def shell_execute_elevated(exe: str, params: str = "") -> bool:
    """Abre um processo com o prompt do UAC. Retorna False se o usuário negar."""
    if not is_windows():
        return False
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return rc > 32


def relaunch_as_admin(extra_args: str = "") -> bool:
    exe, params = _launch_command()
    return shell_execute_elevated(exe, f"{params} {extra_args}".strip())


def add_firewall_rule_dns(port: int = 53) -> bool:
    """Cria regra de entrada UDP para o DNS local (necessita UAC; executada só sob demanda)."""
    name = f"{APP_ID} DNS local"
    params = (
        f'advfirewall firewall add rule name="{name}" dir=in action=allow protocol=UDP '
        f'localport={port} profile=any remoteip=localsubnet'
    )
    return shell_execute_elevated("netsh", params)


# ------------------------------------------------------------ autostart
def autostart_command() -> str:
    exe, params = _launch_command()
    return f'"{exe}" {params} --minimized'.replace("  ", " ")


def set_autostart(enabled: bool) -> bool:
    """Liga/desliga a inicialização com o Windows (HKCU, não exige administrador)."""
    if not is_windows():
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, APP_ID)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def get_autostart() -> bool:
    if not is_windows():
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_ID)
            return True
    except OSError:
        return False


def npcap_installed() -> bool:
    if not is_windows():
        return True
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    return Path(system_root, "System32", "Npcap", "wpcap.dll").exists()
