"""Planos de energia: cria plano dedicado TURBO BOOST PRO (cópia do Desempenho Máximo)
e ajusta processador (estado mínimo 100%, sem estacionamento de núcleos) SOMENTE nele.
Reverter = reativar o plano anterior e apagar o plano criado. O plano original nunca é editado."""
from __future__ import annotations

import re

from ..utils import run
from .journal import Journal

ULTIMATE = "e9a42b02-d5df-448d-aa00-03f14749eb61"
HIGH = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"
GID = "power:plan"
PLAN_NAME = "TURBO BOOST PRO"

_GUID_RE = re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")


def list_plans() -> list[dict]:
    out = []
    for line in run(["powercfg", "/list"]).stdout.splitlines():
        m = _GUID_RE.search(line)
        if m:
            name = re.search(r"\((.*?)\)", line)
            out.append({"guid": m.group(1).lower(), "name": name.group(1) if name else m.group(1),
                        "active": line.strip().endswith("*")})
    return out


def active_plan() -> dict | None:
    m = _GUID_RE.search(run(["powercfg", "/getactivescheme"]).stdout)
    if not m:
        return None
    guid = m.group(1).lower()
    for p in list_plans():
        if p["guid"] == guid:
            return p
    return {"guid": guid, "name": guid, "active": True}


def is_turbo_active() -> bool:
    p = active_plan()
    return bool(p and p["name"] == PLAN_NAME)


def preview(laptop_on_battery: bool = False) -> list[str]:
    cur = active_plan()
    lines = [f"Plano atual: {cur['name'] if cur else 'desconhecido'} (será restaurado ao reverter)",
             f"Criar plano '{PLAN_NAME}' baseado em Desempenho Máximo e ativá-lo",
             "No plano novo: estado mínimo do processador 100%, núcleos sem estacionamento,",
             "  disco nunca desliga, USB sem suspensão seletiva, PCIe sem economia de energia"]
    if laptop_on_battery:
        lines.append("⚠ Notebook na bateria: a autonomia será bem menor.")
    return lines


def apply_turbo_plan(journal: Journal) -> str:
    if journal.has_group(GID):
        guid = journal.group(GID)["actions"][0].get("created")
        if guid and any(p["guid"] == guid for p in list_plans()):
            run(["powercfg", "/setactive", guid])
            return "Plano TURBO BOOST PRO já existe e foi ativado."
    prev = active_plan()
    res = run(["powercfg", "-duplicatescheme", ULTIMATE])
    m = _GUID_RE.search(res.stdout)
    if not m:  # algumas edições não têm o Desempenho Máximo oculto: usa Alto Desempenho
        res = run(["powercfg", "-duplicatescheme", HIGH])
        m = _GUID_RE.search(res.stdout)
    if not m:
        raise RuntimeError("Não foi possível criar o plano de energia: " + (res.stderr or res.stdout))
    new = m.group(1).lower()
    journal.group(GID, "Plano de energia TURBO BOOST PRO", "energia")
    journal.add_action(GID, {"kind": "power", "previous": prev["guid"] if prev else BALANCED,
                             "created": new, "desc": "Restaurar plano de energia anterior"})
    run(["powercfg", "-changename", new, PLAN_NAME, "Criado pelo TURBO BOOST PRO (reversível)"])
    for mode in ("/setacvalueindex", "/setdcvalueindex"):
        run(["powercfg", mode, new, "SUB_PROCESSOR", "PROCTHROTTLEMIN", "100"])
        run(["powercfg", mode, new, "SUB_PROCESSOR", "PROCTHROTTLEMAX", "100"])
        run(["powercfg", mode, new, "SUB_PROCESSOR", "CPMINCORES", "100"])
        run(["powercfg", mode, new, "SUB_PROCESSOR", "PERFBOOSTMODE", "2"])  # agressivo
        run(["powercfg", mode, new, "SUB_DISK", "DISKIDLE", "0"])
        run(["powercfg", mode, new, "2a737441-1930-4402-8d77-b2bebba308a3",
             "48e6b7a6-50f5-4782-a5d4-53bb8f07e226", "0"])  # USB selective suspend
        run(["powercfg", mode, new, "SUB_PCIEXPRESS", "ASPM", "0"])
    run(["powercfg", "/setactive", new])
    return "Plano de energia TURBO BOOST PRO ativado."


def set_balanced(journal: Journal) -> str:
    if journal.has_group(GID):
        journal.revert_group(GID)
        return "Plano de energia anterior restaurado."
    run(["powercfg", "/setactive", BALANCED])
    return "Plano Equilibrado ativado."


def set_plan(guid: str):
    run(["powercfg", "/setactive", guid])
