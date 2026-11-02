"""ETAPA 2: plano de otimizações ainda não aplicadas e MODO CS2 (otimiza ao abrir, restaura ao fechar)."""
from __future__ import annotations

import os
import time

import psutil

from ..config import IS_WINDOWS, settings
from ..utils import log
from . import power, processes, services, system_mods, winapi
from .engine import Action, engine
from .tweaks import TWEAKS
from . import ultralite as UL

CS2_GID = "session:cs2"
CS2_SESSION_SERVICES = ("WSearch", "DiagTrack", "WerSvc", "InventorySvc", "whesvc", "SysMain")


def is_laptop() -> bool:
    bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    return bat is not None


def plan_stage2() -> list[Action]:
    gid = UL.STAGE2_GID
    acts = [UL._start_profile(gid), UL._snapshot_action(gid, "Antes da Etapa 2", "before")]
    prof = "eficiente" if is_laptop() else "competitivo"

    def cpu():
        msg = power.set_cpu_profile(prof, engine.journal)
        engine.journal.set_meta(gid, "power", True)
        return "✔ " + msg
    p = power.CPU_PROFILES[prof]
    details = [p["desc"]] + [f"{power.SETTING_LABELS[k]}: {v}" for k, v in p["values"].items()]
    details.append("Wi-Fi do plano: desempenho máximo (sem economia de energia entre pacotes)")
    if power.parking_sensitive_cpu():
        details.append("Ryzen X3D de 2 CCDs detectado: o estacionamento de núcleos NÃO será desativado.")
    acts.append(Action("cpu_profile", "CPU e energia", f"Perfil de CPU: {p['label']}" +
                       (" (notebook: evita aquecimento)" if prof == "eficiente" else ""), details, cpu, critical=True))
    acts += engine._tweak_actions([t.id for t in TWEAKS if (t.gamer or t.lite) and t.id != "global_timer"],
                                  "Ajustes pendentes da etapa 1", track_gid=gid)
    acts += UL._service_actions("avancado", gid)
    acts += UL._task_actions(gid)
    if IS_WINDOWS:
        from .analysis2 import nic_properties
        eee = [n for n in nic_properties() if n["keyword"] in system_mods.EEE_KEYWORDS
               and n["value"] not in ("0", "", None)]
        if eee:
            def nic():
                msgs = system_mods.disable_nic_power_saving(engine.journal)
                for n in eee:
                    UL._track_gid(gid, f"nic:{n['adapter']}:{n['keyword']}")
                return " · ".join(msgs)
            acts.append(Action("nic_eee", "Rede", "Desativar economia de energia da placa de rede (EEE/Green)",
                               [f"{n['adapter']}: {n['name']} = {n['display']} → Desativado" for n in eee] +
                               ["A conexão cai por 2-3 s ao aplicar."], nic, admin=True, critical=True))
        from .utils_pagefile import pagefile_is_auto
        if pagefile_is_auto() is False:
            def pf():
                msg = system_mods.set_pagefile_auto(engine.journal)
                UL._track_gid(gid, "memory:pagefile")
                return msg
            acts.append(Action("pagefile", "Memória", "Arquivo de paginação gerenciado pelo Windows",
                               ["Recomendado pela Microsoft; evita erros de memória em jogos. Efeito após reiniciar."],
                               pf, admin=True, critical=True))
        st = system_mods.cs2_status()
        if st.get("found") and not (st["priority"] and st["gpu"]):
            def cs2():
                msgs = system_mods.apply_cs2(engine.journal, True, True, False)
                UL._track_gid(gid, "game:cs2")
                return " · ".join(msgs)
            acts.append(Action("cs2", "Counter-Strike 2", "CS2: prioridade Alta (CPU/E-S) e GPU de alto desempenho",
                               [st["exe"]], cs2, admin=True, critical=True))
    acts.append(UL._snapshot_action(gid, "Depois da Etapa 2", "after"))
    return acts


# ============================================================================ MODO CS2
def cs2_session_active() -> bool:
    return engine.journal.has_group(CS2_GID)


def start_cs2_session(launch: bool = True, close_apps: bool = True) -> list[str]:
    """Aplica otimizações temporárias, abre o CS2 e registra tudo para restaurar quando o jogo fechar."""
    j = engine.journal
    if cs2_session_active():
        return ["Modo CS2 já está ativo."]
    j.group(CS2_GID, "Modo CS2 (sessão)", "sessao")
    j.set_meta(CS2_GID, "keep", True)
    j.set_meta(CS2_GID, "since", time.time())
    msgs = []
    prev = power.active_plan()
    if prev and prev["name"] != power.PLAN_NAME:
        try:
            if not power.turbo_plan_guid():
                power.apply_turbo_plan(j)  # cria o plano (com backup próprio)
            j.add_action(CS2_GID, {"kind": "cmd", "cmd": ["powercfg", "/setactive", prev["guid"]],
                                   "desc": f"Voltar ao plano {prev['name']}"})
            power.set_plan(power.turbo_plan_guid())
            msgs.append("Plano de energia TURBO durante a partida")
        except Exception as e:
            msgs.append(f"Plano de energia: {e}")
    if winapi.is_admin():
        for svc in CS2_SESSION_SERVICES:
            ok, _m = services.stop_temporarily(svc, j, CS2_GID)
            if ok:
                msgs.append(f"{svc} pausado")
    if close_apps:
        apps = [a for a in processes.find_background_apps(settings.get("never_kill")) if a["default"]]
        n, _f = processes.close_apps(apps, j, CS2_GID, settings.get("relaunch_closed_apps"))
        if n:
            msgs.append(f"{n} apps de fundo fechados")
    if settings.get("timer_mode") == "on" and not winapi.timer_resolution_active():
        winapi.set_timer_resolution(True)
        j.set_meta(CS2_GID, "timer", True)
        msgs.append("timer 0,5 ms (aprovado no teste A/B)")
    if launch and IS_WINDOWS:
        os.startfile("steam://rungameid/730")  # noqa: S606
        msgs.append("CS2 iniciado pela Steam")
    engine.notify("🎯 Modo CS2: " + ", ".join(msgs), "game")
    log.info("Modo CS2 iniciado: %s", msgs)
    return msgs


def end_cs2_session() -> list[str]:
    g = engine.journal.data["groups"].get(CS2_GID)
    if not g:
        return []
    if g["meta"].get("timer"):
        winapi.set_timer_resolution(False)
    errs = engine.journal.revert_group(CS2_GID)
    engine.notify("Modo CS2 encerrado: serviços, apps e plano de energia restaurados.", "game")
    return errs


def cs2_running() -> bool:
    return any((p.info["name"] or "").lower() == "cs2.exe" for p in psutil.process_iter(["name"]))


def tick():
    """Chamado pelo AutoPilot a cada 3 s: encerra a sessão quando o CS2 fecha; inicia automaticamente se ativado."""
    running = cs2_running()
    if cs2_session_active():
        g = engine.journal.group(CS2_GID)
        if running:
            if not g["meta"].get("seen"):
                engine.journal.set_meta(CS2_GID, "seen", True)
        elif g["meta"].get("seen") or time.time() - g["meta"].get("since", 0) > 300:
            end_cs2_session()
    elif running and settings.get("cs2_auto_session"):
        start_cs2_session(launch=False, close_apps=False)
        engine.journal.set_meta(CS2_GID, "seen", True)
