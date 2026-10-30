"""Leitura mínima de atalhos .lnk (formato MS-SHLLINK) para descobrir o executável.

Usado para saber qual processo fechar quando o usuário diz "fecha o X".
Atalhos "anunciados" (instaladores MSI) não têm caminho; nesse caso
retorna None e o JARVIS apenas abre o atalho.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

HAS_ID_LIST = 0x01
HAS_LINK_INFO = 0x02
HAS_NAME = 0x04
HAS_RELATIVE_PATH = 0x08
HAS_WORKING_DIR = 0x10
HAS_ARGUMENTS = 0x20
IS_UNICODE = 0x80


def _read_cstring(data: bytes, offset: int, unicode: bool) -> str:
    if unicode:
        end = offset
        while end + 1 < len(data) and data[end:end + 2] != b"\x00\x00":
            end += 2
        return data[offset:end].decode("utf-16-le", errors="ignore")
    end = data.find(b"\x00", offset)
    end = len(data) if end < 0 else end
    return data[offset:end].decode("mbcs" if os.name == "nt" else "latin-1", errors="ignore")


def parse_lnk(data: bytes) -> dict:
    """Retorna {'target': str|None, 'relative': str|None, 'arguments': str|None, 'working_dir': str|None}."""
    result: dict = {"target": None, "relative": None, "arguments": None, "working_dir": None}
    if len(data) < 76 or struct.unpack_from("<I", data, 0)[0] != 0x4C:
        raise ValueError("Não é um arquivo .lnk válido")
    flags = struct.unpack_from("<I", data, 20)[0]
    pos = 76
    if flags & HAS_ID_LIST:
        id_list_size = struct.unpack_from("<H", data, pos)[0]
        pos += 2 + id_list_size
    if flags & HAS_LINK_INFO:
        info_start = pos
        info_size, header_size, info_flags = struct.unpack_from("<III", data, pos)
        local_base_off, _net_off, suffix_off = struct.unpack_from("<III", data, pos + 16)
        if info_flags & 0x1:
            base = None
            suffix = ""
            if header_size >= 0x24:
                base_u_off, suffix_u_off = struct.unpack_from("<II", data, pos + 28)
                if base_u_off:
                    base = _read_cstring(data, info_start + base_u_off, True)
                if suffix_u_off:
                    suffix = _read_cstring(data, info_start + suffix_u_off, True)
            if not base and local_base_off:
                base = _read_cstring(data, info_start + local_base_off, False)
                if suffix_off:
                    suffix = _read_cstring(data, info_start + suffix_off, False)
            if base:
                result["target"] = base + suffix
        pos = info_start + info_size
    unicode = bool(flags & IS_UNICODE)
    for flag, key in ((HAS_NAME, None), (HAS_RELATIVE_PATH, "relative"),
                      (HAS_WORKING_DIR, "working_dir"), (HAS_ARGUMENTS, "arguments")):
        if flags & flag:
            if pos + 2 > len(data):
                break
            count = struct.unpack_from("<H", data, pos)[0]
            pos += 2
            size = count * 2 if unicode else count
            raw = data[pos:pos + size]
            pos += size
            if key:
                result[key] = raw.decode("utf-16-le" if unicode else "latin-1", errors="ignore")
    return result


def lnk_target(path: Path) -> str | None:
    try:
        info = parse_lnk(path.read_bytes())
    except (OSError, ValueError, struct.error):
        return None
    target = info.get("target")
    if not target and info.get("relative"):
        candidate = (path.parent / info["relative"]).resolve()
        target = str(candidate)
    if target:
        target = os.path.expandvars(target)
    return target
