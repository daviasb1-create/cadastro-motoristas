"""Versão do Windows e verificação de compatibilidade das otimizações."""
from __future__ import annotations

import functools
import platform

from ..config import IS_WINDOWS
from . import registry as reg

_CV = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"

EDITIONS = {"Core": "Home", "CoreSingleLanguage": "Home (idioma único)", "Professional": "Pro",
            "ProfessionalWorkstation": "Pro for Workstations", "Enterprise": "Enterprise", "Education": "Education",
            "IoTEnterprise": "IoT Enterprise", "ServerDatacenter": "Server Datacenter",
            "ServerStandard": "Server Standard"}


@functools.lru_cache(maxsize=1)
def info() -> dict:
    if not IS_WINDOWS:
        return {"product": f"{platform.system()} {platform.release()}", "display": "", "build": 0, "ubr": 0,
                "edition": "", "edition_label": "", "is_win11": False, "is_server": False,
                "arch": platform.machine()}
    def r(name):
        return reg.read_value("HKLM", _CV, name)[2]
    build = int(r("CurrentBuildNumber") or r("CurrentBuild") or 0)
    edition = str(r("EditionID") or "")
    product = str(r("ProductName") or "Windows")
    if build >= 22000:  # o registro ainda diz "Windows 10" no Windows 11
        product = product.replace("Windows 10", "Windows 11")
    return {"product": product, "display": str(r("DisplayVersion") or r("ReleaseId") or ""), "build": build,
            "ubr": int(r("UBR") or 0), "edition": edition, "edition_label": EDITIONS.get(edition, edition),
            "is_win11": build >= 22000, "is_server": "Server" in edition or "Server" in product,
            "arch": platform.machine()}


def build_number() -> int:
    return info()["build"]


def compatibility() -> tuple[str, list[str]]:
    """Retorna (nível, avisos). nível: 'ok' | 'aviso' | 'bloqueado'."""
    i = info()
    warns = []
    level = "ok"
    if not IS_WINDOWS:
        return "bloqueado", ["Este módulo só funciona no Windows."]
    if i["is_server"]:
        level = "aviso"
        warns.append("Windows Server detectado: apps nativos e alguns recursos não existem; serão ignorados.")
    elif not i["is_win11"]:
        level = "aviso"
        warns.append("Windows 10 detectado: a maioria dos ajustes funciona, mas itens exclusivos do Windows 11 "
                     "(Copilot, Recall, Widgets, Chat) serão ignorados.")
    elif i["build"] < 22621:
        level = "aviso"
        warns.append("Windows 11 21H2 é antigo e sem suporte; atualize para 23H2/24H2 para melhor resultado.")
    if i["edition"].startswith("Core"):
        warns.append("Edição Home: algumas políticas (ex.: telemetria abaixo do nível 'Obrigatório') são "
                     "ignoradas pelo Windows. O TURBO BOOST PRO usa apenas valores suportados.")
    if i["arch"].upper() in ("ARM64", "AARCH64"):
        warns.append("Windows em ARM: drivers de GPU e alguns contadores podem ter comportamento diferente.")
    return level, warns


def label() -> str:
    i = info()
    if not i["build"]:
        return i["product"]
    return f"{i['product']} {i['display']} (build {i['build']}.{i['ubr']})"
