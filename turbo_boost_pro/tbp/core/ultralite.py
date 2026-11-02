"""WINDOWS ULTRA LITE e WINDOWS GAMING EDITION: planos completos, ativação/desativação com um clique,
medições antes/depois e RESTAURAR WINDOWS ORIGINAL."""
from __future__ import annotations

import time

from ..config import settings
from ..utils import log
from . import services, snapshot, startup, system_mods, winapi, winver
from .engine import Action, engine
from .tweaks import TWEAKS, TWEAKS_BY_ID

ULTRA_GID = "profile:ultra_lite"
GAMING_GID = "profile:gaming_edition"
PROFILE_TITLES = {ULTRA_GID: "WINDOWS ULTRA LITE", GAMING_GID: "WINDOWS GAMING EDITION"}


def is_active(gid: str) -> bool:
    return engine.journal.has_group(gid)


# ------------------------------------------------------------------ blocos
def _start_profile(gid: str) -> Action:
    def run():
        engine.journal.group(gid, PROFILE_TITLES[gid], "perfil")
        engine.journal.set_meta(gid, "keep", True)
        engine.journal.set_meta(gid, "since", time.time())
        return f"⚡ {PROFILE_TITLES[gid]}: sessão de alterações registrada"
    return Action(f"{gid}:init", "Segurança", "Registrar perfil para desativação com 1 clique",
                  ["Cada alteração guarda o valor original antes de ser aplicada."], run, locked=True)


def _snapshot_action(gid: str, label: str, when: str) -> Action:
    def run():
        snap = snapshot.capture(label, journal=engine.journal)
        engine.journal.set_meta(gid, f"snap_{when}", snap["id"])
        return f"📊 Medição '{label}' registrada"
    return Action(f"{gid}:snap_{when}", "Medição" if when == "before" else "Medição final",
                  f"Medir desempenho ({'antes' if when == 'before' else 'depois'})",
                  ["RAM, processos, serviços, CPU em repouso (8 s), tempo de boot, espaço livre."], run, locked=True)


def _track_gid(profile_gid: str, gid: str):
    engine._track(profile_gid, "gids", gid)


def _service_actions(profile: str, profile_gid: str) -> list[Action]:
    out = []
    for c in services.profile_plan(profile):
        def run(c=c):
            ok, msg = services.set_start(c["name"], c["target"], engine.journal)
            if not ok:
                raise RuntimeError(msg)
            _track_gid(profile_gid, f"service:{c['name']}")
            return "✔ Serviço " + msg
        out.append(Action(f"svc:{c['name']}", f"Serviços (perfil {profile})",
                          f"{c['label']}: {c['current']} → {c['target_label']}",
                          [c["desc"], f"Serviço: {c['name']} · estado atual: {c['status']}"], run, admin=True,
                          critical=True))
    return out


def _task_actions(profile_gid: str) -> list[Action]:
    out = []
    for t in system_mods.list_tasks():
        if not t["enabled"]:
            continue

        def run(t=t):
            msg = system_mods.disable_task(t["full"], engine.journal)
            _track_gid(profile_gid, f"task:{t['full']}")
            return msg
        out.append(Action(f"task:{t['full']}", "Tarefas agendadas de telemetria", f"Desativar tarefa {t['name']}",
                          [t["desc"], t["full"]], run, admin=True, critical=True))
    return out


def _startup_actions(profile_gid: str) -> list[Action]:
    out = []
    admin = winapi.is_admin()
    for e in startup.list_entries():
        if not e["enabled"] or e["rec"] != "desativar" or (e["admin"] and not admin):
            continue

        def run(e=e):
            msg = startup.set_enabled(e, False, engine.journal)
            _track_gid(profile_gid, e["gid"])
            return "✔ " + msg
        out.append(Action(f"startup:{e['name']}", "Inicialização do Windows", f"Não iniciar com o Windows: {e['name']}",
                          [e["command"][:140], "O programa continua instalado; reative quando quiser."], run,
                          critical=True))
    return out


def _feature_actions(profile_gid: str) -> list[Action]:
    out = []
    for f in system_mods.list_features():
        if not f["enabled"]:
            continue

        def run(f=f):
            msg = system_mods.disable_feature(f, engine.journal)
            _track_gid(profile_gid, f"{f['type']}:{f['name']}")
            return msg
        kind = "Recurso opcional" if f["type"] == "feature" else "Capacidade"
        out.append(Action(f"feat:{f['name']}", "Recursos opcionais do Windows", f"Desativar {f['label']}",
                          [f["desc"], f"{kind}: {f['name']}"], run, admin=True, critical=True,
                          selected=f["level"] == "recomendado"))
    return out


def _debloat_actions(profile_gid: str, include_optional_selected=False) -> list[Action]:
    out = []
    for a in system_mods.list_apps():
        if a["level"] == "outro":
            continue

        def run(a=a):
            msg = system_mods.remove_app(a, engine.journal)
            _track_gid(profile_gid, f"appx:{a['name']}")
            return msg
        out.append(Action(f"appx:{a['name']}", "Apps pré-instalados (debloat)", f"Remover {a['label']}",
                          [a["desc"], f"Pacote: {a['name']} · reinstalável a qualquer momento"], run, critical=True,
                          selected=a["level"] == "recomendado" or include_optional_selected))
    return out


# ------------------------------------------------------------------ ULTRA LITE
def plan_ultra_lite() -> list[Action]:
    gid = ULTRA_GID
    acts = [_start_profile(gid), _snapshot_action(gid, "Antes do Ultra Lite", "before")]
    acts += engine._tweak_actions([t.id for t in TWEAKS if t.lite], "Registro: visual, segundo plano e privacidade",
                                  track_gid=gid)
    acts += _service_actions("avancado", gid)
    acts += _task_actions(gid)
    acts += _startup_actions(gid)
    acts += _debloat_actions(gid)
    acts += _feature_actions(gid)
    if system_mods.hibernation_enabled():
        def hib():
            msg = system_mods.disable_hibernation(engine.journal)
            _track_gid(gid, "power:hibernate")
            return msg
        acts.append(Action("hibernate", "Disco", "Desativar hibernação (libera o hiberfil.sys, 40% da RAM em disco)",
                           ["Também desativa a Inicialização Rápida: o desligamento passa a ser completo.",
                            "Em notebooks, a hibernação automática com bateria baixa deixa de existir."], hib,
                           admin=True, critical=True, selected=False))
    acts.append(_snapshot_action(gid, "Depois do Ultra Lite", "after"))
    return acts


# ------------------------------------------------------------------ GAMING EDITION
def plan_gaming_edition() -> list[Action]:
    gid = GAMING_GID
    acts = [_start_profile(gid), _snapshot_action(gid, "Antes do Gaming Edition", "before")]
    acts += engine._power_action(track_gid=gid)
    ids = [t.id for t in TWEAKS if t.gamer or t.id in ("bg_apps", "visual_anim", "visual_transparency",
                                                        "power_throttling_off")]
    acts += engine._tweak_actions(list(dict.fromkeys(ids)), "Registro: jogos, latência e agendamento",
                                  track_gid=gid)
    acts += _service_actions("conservador", gid)

    def runtime():
        winapi.set_timer_resolution(True)
        settings.set("auto_game_boost", True)
        engine.journal.set_meta(gid, "timer", True)
        return "✔ Timer 0,5 ms + detecção automática de jogos ativos"
    acts.append(Action("ge:runtime", "Tempo de execução", "Timer de 0,5 ms e boost automático ao abrir jogos",
                       ["Ao abrir um jogo com perfil: prioridade alta, serviços pausados e RAM liberada.",
                        "Tudo volta ao normal ao fechar o jogo."], runtime))
    cs = system_mods.find_cs2()
    if cs:
        def cs2_core():
            msgs = system_mods.apply_cs2(engine.journal, priority=True, gpu=True, autoexec=False)
            _track_gid(gid, "game:cs2")
            return " · ".join(msgs)
        acts.append(Action("cs2", "Counter-Strike 2", "CS2: prioridade Alta (CPU/E-S) e GPU de alto desempenho",
                           [cs["exe"], r"HKLM\...\Image File Execution Options\cs2.exe\PerfOptions: "
                            "CpuPriorityClass=3, IoPriority=3",
                            "Não altera arquivos do jogo nem a memória do processo (seguro para VAC)."],
                           cs2_core, admin=True, critical=True))
    acts.append(_snapshot_action(gid, "Depois do Gaming Edition", "after"))
    return acts


# ------------------------------------------------------------------ desativação
def deactivate(gid: str) -> list[str]:
    """Desfaz apenas o que o perfil aplicou (preserva o que outro perfil ativo também usa)."""
    g = engine.journal.data["groups"].get(gid)
    if not g:
        return []
    other = GAMING_GID if gid == ULTRA_GID else ULTRA_GID
    og = engine.journal.data["groups"].get(other, {"meta": {}})["meta"]
    keep_tweaks, keep_gids = set(og.get("tweaks", [])), set(og.get("gids", []))
    errors = []
    for g2 in reversed(g["meta"].get("gids", [])):
        if g2 not in keep_gids:
            errors += engine.journal.revert_group(g2)
    for tid in g["meta"].get("tweaks", []):
        if tid not in keep_tweaks and tid in TWEAKS_BY_ID:
            errors += TWEAKS_BY_ID[tid].revert(engine.journal)
    if g["meta"].get("power") and not og.get("power") and not engine.turbo_active:
        from . import power
        power.set_balanced(engine.journal)
    if g["meta"].get("timer") and engine.mode != "gamer":
        winapi.set_timer_resolution(False)
    errors += engine.journal.revert_group(gid)
    log.info("Perfil %s desativado. erros=%s", gid, errors)
    engine.notify(f"{PROFILE_TITLES[gid]} desativado. Configurações originais restauradas.")
    return errors


def restore_windows_original() -> list[str]:
    """RESTAURAR WINDOWS ORIGINAL: desfaz absolutamente tudo (apps, recursos, serviços, tarefas, registro)."""
    errors = []
    for gid in (GAMING_GID, ULTRA_GID):
        if is_active(gid):
            errors += deactivate(gid)
    errors += engine.restore_everything()
    snapshot.capture("Após restaurar Windows original", cpu_seconds=3, journal=engine.journal)
    return errors


# ------------------------------------------------------------------ planos avulsos (abas)
def plan_service_profile(profile: str) -> list[Action]:
    return _service_actions(profile, None)


def plan_debloat(apps: list[dict]) -> list[Action]:
    out = []
    for a in apps:
        out.append(Action(f"appx:{a['name']}", "Apps selecionados", f"Remover {a['label']}",
                          [a["desc"], f"Pacote: {a['full']}"],
                          lambda a=a: system_mods.remove_app(a, engine.journal), critical=True))
    return out


def plan_features(items: list[dict]) -> list[Action]:
    return [Action(f"feat:{f['name']}", "Recursos selecionados", f"Desativar {f['label']}", [f["desc"], f["name"]],
                   lambda f=f: system_mods.disable_feature(f, engine.journal), admin=True, critical=True)
            for f in items]


def plan_tasks(items: list[dict]) -> list[Action]:
    return [Action(f"task:{t['full']}", "Tarefas selecionadas", f"Desativar {t['name']}", [t["desc"], t["full"]],
                   lambda t=t: system_mods.disable_task(t["full"], engine.journal), admin=True, critical=True)
            for t in items]


def plan_cs2(autoexec: bool) -> list[Action]:
    cs = system_mods.find_cs2()
    if not cs:
        return []
    details = [cs["exe"], "Prioridade Alta de CPU e E/S (IFEO PerfOptions)", "GPU de alto desempenho"]
    if autoexec:
        details += [f"autoexec.cfg em {cs['cfg_dir']} (o atual é salvo no backup):"] + \
            [line for line in system_mods.CS2_AUTOEXEC.splitlines() if line and not line.startswith("//")]
    return [Action("cs2", "Counter-Strike 2", "Aplicar otimizações do CS2", details,
                   lambda: " · ".join(system_mods.apply_cs2(engine.journal, True, True, autoexec)), admin=True,
                   critical=True)]


def compat_summary() -> dict:
    level, warns = winver.compatibility()
    return {"label": winver.label(), "edition": winver.info()["edition_label"], "level": level, "warnings": warns,
            "admin": winapi.is_admin()}
