"""Acesso ao Registro do Windows (com backend simulado fora do Windows para testes)."""
from __future__ import annotations

from ..config import IS_WINDOWS

REG_SZ, REG_EXPAND_SZ, REG_BINARY, REG_DWORD, REG_MULTI_SZ, REG_QWORD = 1, 2, 3, 4, 7, 11

if IS_WINDOWS:
    import winreg

    HIVES = {
        "HKCU": winreg.HKEY_CURRENT_USER,
        "HKLM": winreg.HKEY_LOCAL_MACHINE,
        "HKCR": winreg.HKEY_CLASSES_ROOT,
        "HKU": winreg.HKEY_USERS,
    }
    _VIEW = winreg.KEY_WOW64_64KEY

    def read_value(hive: str, path: str, name: str):
        """Retorna (existe, tipo, valor)."""
        try:
            with winreg.OpenKey(HIVES[hive], path, 0, winreg.KEY_READ | _VIEW) as k:
                value, typ = winreg.QueryValueEx(k, name)
                return True, typ, value
        except OSError:
            return False, None, None

    def write_value(hive: str, path: str, name: str, typ: int, value):
        with winreg.CreateKeyEx(HIVES[hive], path, 0, winreg.KEY_WRITE | _VIEW) as k:
            winreg.SetValueEx(k, name, 0, typ, value)

    def delete_value(hive: str, path: str, name: str):
        try:
            with winreg.OpenKey(HIVES[hive], path, 0, winreg.KEY_WRITE | _VIEW) as k:
                winreg.DeleteValue(k, name)
        except FileNotFoundError:
            pass

    def list_values(hive: str, path: str) -> list[tuple[str, object, int]]:
        out = []
        try:
            with winreg.OpenKey(HIVES[hive], path, 0, winreg.KEY_READ | _VIEW) as k:
                i = 0
                while True:
                    try:
                        out.append(winreg.EnumValue(k, i))
                    except OSError:
                        break
                    i += 1
        except OSError:
            pass
        return out

    def list_subkeys(hive: str, path: str) -> list[str]:
        out = []
        try:
            with winreg.OpenKey(HIVES[hive], path, 0, winreg.KEY_READ | _VIEW) as k:
                i = 0
                while True:
                    try:
                        out.append(winreg.EnumKey(k, i))
                    except OSError:
                        break
                    i += 1
        except OSError:
            pass
        return out

else:  # Backend em memória: permite rodar testes e a interface fora do Windows.
    _FAKE: dict[tuple[str, str, str], tuple[int, object]] = {}

    def _k(hive, path, name):
        return hive.upper(), path.lower(), name.lower()

    def read_value(hive, path, name):
        v = _FAKE.get(_k(hive, path, name))
        return (True, v[0], v[1]) if v else (False, None, None)

    def write_value(hive, path, name, typ, value):
        _FAKE[_k(hive, path, name)] = (typ, value)

    def delete_value(hive, path, name):
        _FAKE.pop(_k(hive, path, name), None)

    def list_values(hive, path):
        return [(n, v[1], v[0]) for (h, p, n), v in _FAKE.items() if h == hive.upper() and p == path.lower()]

    def list_subkeys(hive, path):
        return []


def encode(typ, value):
    """Serializa valor do registro para JSON."""
    if typ == REG_BINARY and value is not None:
        return bytes(value).hex()
    return value


def decode(typ, value):
    if typ == REG_BINARY and value is not None:
        return bytes.fromhex(value)
    return value


def type_name(typ) -> str:
    return {REG_SZ: "REG_SZ", REG_EXPAND_SZ: "REG_EXPAND_SZ", REG_BINARY: "REG_BINARY", REG_DWORD: "REG_DWORD",
            REG_MULTI_SZ: "REG_MULTI_SZ", REG_QWORD: "REG_QWORD"}.get(typ, str(typ))


def display(value) -> str:
    if value is None:
        return "(não existe)"
    if isinstance(value, (bytes, bytearray)):
        return value[:8].hex(" ") + ("…" if len(value) > 8 else "")
    if isinstance(value, int) and value > 9:
        return f"{value} (0x{value:X})"
    return str(value)
