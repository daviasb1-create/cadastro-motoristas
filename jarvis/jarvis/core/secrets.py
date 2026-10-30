"""Armazenamento seguro de segredos (chaves de API).

Ordem de preferência:
1. ``keyring`` -> Gerenciador de Credenciais do Windows.
2. Arquivo criptografado com DPAPI do Windows (vinculado à conta do usuário).

Nunca grava segredos em texto simples. Em sistemas sem nenhum dos dois
mecanismos, o segredo vale apenas durante a execução.
"""
from __future__ import annotations

import base64
import json
import logging
import threading

from . import paths
from .paths import IS_WINDOWS

log = logging.getLogger(__name__)

SERVICE = "Jarvis-Assistente"
KNOWN_KEYS = {
    "anthropic_api_key": "Chave da API Anthropic (Claude)",
    "porcupine_access_key": "AccessKey Picovoice (Porcupine)",
    "azure_speech_key": "Chave do Azure Speech",
}


class SecretStore:
    def __init__(self) -> None:
        self._memory: dict[str, str] = {}
        self._lock = threading.Lock()
        self._keyring = None
        try:
            import keyring  # type: ignore
            from keyring.backends import fail  # type: ignore

            if not isinstance(keyring.get_keyring(), fail.Keyring):
                self._keyring = keyring
        except Exception:  # noqa: BLE001 - keyring é opcional
            self._keyring = None

    @property
    def backend_name(self) -> str:
        if self._keyring is not None:
            return "Gerenciador de Credenciais do Windows" if IS_WINDOWS else "keyring do sistema"
        if IS_WINDOWS:
            return "Arquivo protegido por DPAPI"
        return "Somente memória (não persistente)"

    def get(self, name: str) -> str | None:
        with self._lock:
            if name in self._memory:
                return self._memory[name]
            value = None
            if self._keyring is not None:
                try:
                    value = self._keyring.get_password(SERVICE, name)
                except Exception:  # noqa: BLE001
                    log.warning("Falha ao ler segredo %s do keyring", name)
            elif IS_WINDOWS:
                value = _dpapi_file_load().get(name)
            if value:
                self._memory[name] = value
            return value

    def set(self, name: str, value: str) -> None:
        value = (value or "").strip()
        with self._lock:
            if not value:
                self._delete_locked(name)
                return
            self._memory[name] = value
            if self._keyring is not None:
                self._keyring.set_password(SERVICE, name, value)
            elif IS_WINDOWS:
                data = _dpapi_file_load()
                data[name] = value
                _dpapi_file_save(data)
            else:
                log.warning("Sem armazenamento seguro disponível; segredo %s mantido só em memória.", name)

    def delete(self, name: str) -> None:
        with self._lock:
            self._delete_locked(name)

    def _delete_locked(self, name: str) -> None:
        self._memory.pop(name, None)
        if self._keyring is not None:
            try:
                self._keyring.delete_password(SERVICE, name)
            except Exception:  # noqa: BLE001 - já inexistente
                pass
        elif IS_WINDOWS:
            data = _dpapi_file_load()
            if data.pop(name, None) is not None:
                _dpapi_file_save(data)

    def has(self, name: str) -> bool:
        return bool(self.get(name))


# ---------------------------------------------------------------- DPAPI (Win)
def _dpapi_path():
    return paths.data_dir() / "secrets.dpapi"


def _dpapi_file_load() -> dict:
    path = _dpapi_path()
    if not path.exists():
        return {}
    try:
        raw = dpapi_unprotect(base64.b64decode(path.read_bytes()))
        return json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        log.error("Não foi possível descriptografar o arquivo de segredos.")
        return {}


def _dpapi_file_save(data: dict) -> None:
    blob = dpapi_protect(json.dumps(data).encode("utf-8"))
    _dpapi_path().write_bytes(base64.b64encode(blob))


def dpapi_protect(data: bytes) -> bytes:
    return _dpapi_call(data, protect=True)


def dpapi_unprotect(data: bytes) -> bytes:
    return _dpapi_call(data, protect=False)


def _dpapi_call(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(blob_in), None, None, None, None, 0x01, ctypes.byref(blob_out))  # UI_FORBIDDEN
    if not ok:
        raise OSError("Falha na DPAPI")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)
