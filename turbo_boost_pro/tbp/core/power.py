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
        if not parking_sensitive_cpu():  # X3D com 2 CCDs depende do estacionamento para usar o cache 3D
            run(["powercfg", mode, new, "SUB_PROCESSOR", "CPMINCORES", "100"])
        run(["powercfg", mode, new, "SUB_PROCESSOR", "PERFBOOSTMODE", "2"])  # agressivo
        run(["powercfg", mode, new, "SUB_DISK", "DISKIDLE", "0"])
        run(["powercfg", mode, new, "2a737441-1930-4402-8d77-b2bebba308a3",
             "48e6b7a6-50f5-4782-a5d4-53bb8f07e226", "0"])  # USB selective suspend
        run(["powercfg", mode, new, "SUB_PCIEXPRESS", "ASPM", "0"])
        run(["powercfg", mode, new, WIFI_SUB, WIFI_POWER, "0"])  # Wi-Fi: desempenho máximo (sem economia)
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


# ============================================================================ CPU (etapa 2)
WIFI_SUB = "19cbb8fa-5279-450e-9fac-8a3d5fedd0c1"
WIFI_POWER = "12bbebe6-58d6-4636-95bb-3217ef867c1a"

# Perfis aplicados SOMENTE no plano TURBO BOOST PRO (o plano original nunca é editado; reverter = apagar o plano).
CPU_PROFILES = {
    "competitivo": {"label": "Competitivo", "desc": "Clock sempre no máximo, sem estacionamento de núcleos e "
                    "turbo agressivo. Menor variação de frametime; mais calor e consumo em repouso.",
                    "values": {"PROCTHROTTLEMIN": 100, "PROCTHROTTLEMAX": 100, "CPMINCORES": 100,
                               "PERFBOOSTMODE": 2, "PERFEPP": 0}},
    "eficiente": {"label": "Desempenho eficiente", "desc": "Turbo agressivo e preferência por desempenho, mas a CPU "
                  "pode baixar o clock e estacionar núcleos em repouso. Nos jogos o desempenho é praticamente igual "
                  "(CPUs atuais sobem o clock em ~1 ms); menos calor, ruído e throttling térmico em notebooks.",
                  "values": {"PROCTHROTTLEMIN": 5, "PROCTHROTTLEMAX": 100, "CPMINCORES": 10, "PERFBOOSTMODE": 2,
                             "PERFEPP": 25}},
}
SETTING_LABELS = {"PROCTHROTTLEMIN": "Estado mínimo do processador (%)", "PROCTHROTTLEMAX": "Estado máximo (%)",
                  "CPMINCORES": "Núcleos mínimos não estacionados (%)",
                  "PERFBOOSTMODE": "Modo de turbo (0=off 1=on 2=agressivo 3=eficiente 4=eficiente agressivo)",
                  "PERFEPP": "Preferência energia x desempenho (0 = desempenho máximo, 100 = economia)"}


def parking_sensitive_cpu() -> bool:
    """Ryzen X3D com dois CCDs (7900X3D/7950X3D/9900X3D/9950X3D): o driver da AMD estaciona o CCD sem cache 3D
    durante jogos. Forçar todos os núcleos ativos anula isso e PIORA o desempenho."""
    import psutil
    from .monitor import _cpu_name
    name = _cpu_name().upper()
    return "X3D" in name and (psutil.cpu_count(False) or 0) >= 12


def read_setting(alias: str, scheme: str = "SCHEME_CURRENT", sub: str = "SUB_PROCESSOR") -> tuple[int, int] | None:
    """Lê (AC, DC) de uma configuração do plano. Funciona em qualquer idioma (usa os dois últimos valores 0x)."""
    out = run(["powercfg", "/qh", scheme, sub, alias]).stdout
    vals = re.findall(r"0x([0-9a-fA-F]{8})", out)
    if len(vals) < 2:
        return None
    return int(vals[-2], 16), int(vals[-1], 16)


def cpu_settings() -> dict:
    return {alias: read_setting(alias) for alias in SETTING_LABELS}


def turbo_plan_guid() -> str | None:
    return next((p["guid"] for p in list_plans() if p["name"] == PLAN_NAME), None)


def set_cpu_profile(name: str, journal: Journal) -> str:
    """Aplica o perfil de CPU no plano TURBO BOOST PRO (cria o plano, com backup do anterior, se preciso)."""
    prof = CPU_PROFILES[name]
    if not turbo_plan_guid():
        apply_turbo_plan(journal)
    guid = turbo_plan_guid()
    if not guid:
        raise RuntimeError("Plano TURBO BOOST PRO indisponível.")
    for alias, value in prof["values"].items():
        if alias == "CPMINCORES" and value == 100 and parking_sensitive_cpu():
            continue
        for mode in ("/setacvalueindex", "/setdcvalueindex"):
            run(["powercfg", mode, guid, "SUB_PROCESSOR", alias, str(value)])
    for mode in ("/setacvalueindex", "/setdcvalueindex"):
        run(["powercfg", mode, guid, WIFI_SUB, WIFI_POWER, "0"])
    run(["powercfg", "/setactive", guid])
    from ..config import settings
    settings.set("cpu_profile", name)
    return f"Perfil de CPU '{prof['label']}' aplicado no plano TURBO BOOST PRO."


def set_core_parking(allow: bool, journal: Journal) -> str:
    if not turbo_plan_guid():
        apply_turbo_plan(journal)
    guid = turbo_plan_guid()
    value = "10" if allow else "100"
    for mode in ("/setacvalueindex", "/setdcvalueindex"):
        run(["powercfg", mode, guid, "SUB_PROCESSOR", "CPMINCORES", value])
    run(["powercfg", "/setactive", guid])
    return "Estacionamento de núcleos " + ("permitido (padrão do Windows)." if allow else "desativado.")
