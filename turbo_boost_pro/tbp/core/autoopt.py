"""TURBO BENCHMARK AI · AUTO OPTIMIZER

Laboratório que testa configurações do Windows UMA DE CADA VEZ, mede no CS2 (ou outro jogo) e mantém apenas o que
comprovadamente melhora o desempenho.

Método:
- Cada variável tem duas opções: A = estado atual do seu PC, B = alternativa.
- Variáveis "ao vivo" são medidas intercaladas (A B, B A, A B…) para cancelar aquecimento e deriva térmica.
- Variáveis que exigem reiniciar o jogo/PC são medidas em blocos A e B no mesmo cenário (demo + mesmo tick).
- Decisão estatística: a diferença precisa superar a margem de erro (2 erros-padrão e o ruído mínimo da métrica).
  1% low e estabilidade do frametime pesam mais que o FPS médio.
- Tudo é aplicado pelo Journal (backup + reversão). Falhas revertem automaticamente.
"""
from __future__ import annotations

import json
import math
import os
import statistics
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

import psutil

from ..config import DATA_DIR, IS_WINDOWS, settings
from ..utils import log, powershell, run
from . import bench, memory, power, registry as reg, restore_point, services, system_mods, winapi
from .journal import journal

STATE_FILE = DATA_DIR / "autoopt.json"
TEST_PREFIX = "autoopt_test:"
APPLIED_PREFIX = "autoopt:"
_lock = threading.RLock()

_GD = r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers"
_MM = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile"
_GAMES = _MM + r"\Tasks\Games"
_PRIO = r"SYSTEM\CurrentControlSet\Control\PriorityControl"
_IFEO = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\cs2.exe\PerfOptions"
_GAMEBAR = r"Software\Microsoft\GameBar"


# ============================================================================ VARIÁVEIS
@dataclass
class Variable:
    id: str
    title: str
    category: str
    desc: str
    scope: str                                   # live | game | reboot
    state: Callable[[], str]                     # descrição do estado atual
    alt_label: Callable[[], str]                 # descrição da alternativa
    apply_alt: Callable[[str], None]             # aplica a alternativa registrando no grupo do journal
    available: Callable[[], bool] = lambda: True
    revert_extra: Callable[[], None] | None = None


def _reg_val(hive, path, name):
    ok, _t, v = reg.read_value(hive, path, name)
    return v if ok else None


def _set(gid, hive, path, name, value, typ=reg.REG_DWORD):
    journal.group(gid, f"Teste: {gid.split(':', 1)[1]}", "autoopt")
    journal.reg_set(gid, hive, path, name, typ, value)


def _record_plan_restore(gid: str):
    """Guarda o plano ativo e os valores do processador para restaurar depois do teste."""
    journal.group(gid, f"Teste: {gid.split(':', 1)[1]}", "autoopt")
    plan = power.active_plan()
    if not plan:
        return
    vals = power.cpu_settings()
    for alias, v in vals.items():
        if v:
            journal.add_action(gid, {"kind": "cmd", "cmd": ["powercfg", "/setacvalueindex", plan["guid"],
                                                             "SUB_PROCESSOR", alias, str(v[0])], "desc": alias})
            journal.add_action(gid, {"kind": "cmd", "cmd": ["powercfg", "/setdcvalueindex", plan["guid"],
                                                             "SUB_PROCESSOR", alias, str(v[1])], "desc": alias})
    journal.add_action(gid, {"kind": "cmd", "cmd": ["powercfg", "/setactive", plan["guid"]],
                             "desc": f"Voltar ao plano {plan['name']}"})


def _plan_profile(name):
    def apply(gid):
        _record_plan_restore(gid)
        power.set_cpu_profile(name, journal)
    return apply


def _plan_state():
    p = power.active_plan()
    prof = settings.get("cpu_profile") if p and p["name"] == power.PLAN_NAME else None
    return (p["name"] if p else "?") + (f" ({power.CPU_PROFILES[prof]['label']})" if prof in power.CPU_PROFILES else "")


def _parking_state():
    v = power.read_setting("CPMINCORES")
    return "desativado (100%)" if v and v[0] >= 100 else f"permitido ({v[0]}%)" if v else "?"


def _parking_apply(gid):
    _record_plan_restore(gid)
    plan = power.active_plan()
    v = power.read_setting("CPMINCORES")
    new = "10" if v and v[0] >= 100 else "100"
    for mode in ("/setacvalueindex", "/setdcvalueindex"):
        run(["powercfg", mode, plan["guid"], "SUB_PROCESSOR", "CPMINCORES", new])
    run(["powercfg", "/setactive", plan["guid"]])


def _gm_on():
    return _reg_val("HKCU", _GAMEBAR, "AutoGameModeEnabled") != 0


def _hags_on():
    return _reg_val("HKLM", _GD, "HwSchMode") == 2


def _mmcss_on():
    return _reg_val("HKLM", _MM, "SystemResponsiveness") == 10 and _reg_val("HKLM", _GAMES, "GPU Priority") == 8 \
        and _reg_val("HKLM", _GAMES, "Priority") == 6


def _mmcss_apply(gid):
    if _mmcss_on():  # alternativa = valores padrão do Windows
        vals = [(_MM, "SystemResponsiveness", 20, reg.REG_DWORD), (_GAMES, "Priority", 2, reg.REG_DWORD),
                (_GAMES, "Scheduling Category", "Medium", reg.REG_SZ), (_GAMES, "SFIO Priority", "Normal", reg.REG_SZ)]
    else:
        vals = [(_MM, "SystemResponsiveness", 10, reg.REG_DWORD), (_GAMES, "GPU Priority", 8, reg.REG_DWORD),
                (_GAMES, "Priority", 6, reg.REG_DWORD), (_GAMES, "Scheduling Category", "High", reg.REG_SZ),
                (_GAMES, "SFIO Priority", "High", reg.REG_SZ)]
    for path, name, v, t in vals:
        _set(gid, "HKLM", path, name, v, t)


def _sep_val():
    return _reg_val("HKLM", _PRIO, "Win32PrioritySeparation")


def _prio_on():
    return _reg_val("HKLM", _IFEO, "CpuPriorityClass") == 3


def _prio_apply(gid):
    if _prio_on():
        _set(gid, "HKLM", _IFEO, "CpuPriorityClass", 2)  # Normal
        _set(gid, "HKLM", _IFEO, "IoPriority", 2)
    else:
        _set(gid, "HKLM", _IFEO, "CpuPriorityClass", 3)
        _set(gid, "HKLM", _IFEO, "IoPriority", 3)


def _fso_off():
    try:
        return bool(system_mods.cs2_status().get("fso_off"))
    except Exception:
        return False


def _fso_apply(gid):
    cs = system_mods.find_cs2()
    lay = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
    cur = str(_reg_val("HKCU", lay, cs["exe"]) or "")
    flags = set(cur.replace("~", "").split())
    if "DISABLEDXMAXIMIZEDWINDOWEDMODE" in flags:
        flags.discard("DISABLEDXMAXIMIZEDWINDOWEDMODE")
    else:
        flags.add("DISABLEDXMAXIMIZEDWINDOWEDMODE")
    new = ("~ " + " ".join(sorted(flags))) if flags else ""
    journal.group(gid, "Teste: tela cheia CS2", "autoopt")
    if new:
        journal.reg_set(gid, "HKCU", lay, cs["exe"], reg.REG_SZ, new)
    else:
        journal.reg_delete(gid, "HKCU", lay, cs["exe"])


_purge_before_capture = {"on": False}


def _purge_apply(gid):
    journal.group(gid, "Teste: limpeza de RAM", "autoopt")
    journal.set_meta(gid, "keep", True)
    _purge_before_capture["on"] = True


def _timer_apply(gid):
    journal.group(gid, "Teste: timer 0,5 ms", "autoopt")
    journal.set_meta(gid, "keep", True)
    winapi.set_timer_resolution(True)


BG_SERVICES = ("WSearch", "DiagTrack", "WerSvc", "InventorySvc", "whesvc")


def _bg_apply(gid):
    journal.group(gid, "Teste: serviços de fundo pausados", "autoopt")
    journal.set_meta(gid, "keep", True)
    for s in BG_SERVICES:
        services.stop_temporarily(s, journal, gid)


def _svc_running(name):
    s = services.get_service(name)
    return bool(s and s["status"] == "running")


VARIABLES: list[Variable] = [
    Variable("plan_comp", "Plano de energia: Competitivo", "Energia",
             "Clock mínimo 100%, sem estacionamento, turbo agressivo (plano TURBO BOOST PRO).", "live",
             _plan_state, lambda: "TURBO BOOST PRO (Competitivo)", _plan_profile("competitivo"),
             lambda: not (power.active_plan() or {}).get("name") == power.PLAN_NAME
             or settings.get("cpu_profile") != "competitivo"),
    Variable("plan_eff", "Plano de energia: Desempenho eficiente", "Energia",
             "Turbo agressivo, mas a CPU pode baixar o clock em repouso (menos calor).", "live",
             _plan_state, lambda: "TURBO BOOST PRO (Eficiente)", _plan_profile("eficiente"),
             lambda: not (power.active_plan() or {}).get("name") == power.PLAN_NAME
             or settings.get("cpu_profile") != "eficiente"),
    Variable("parking", "Estacionamento de núcleos", "CPU", "Alterna entre núcleos sempre ativos e estacionamento "
             "permitido no plano ativo.", "live", _parking_state,
             lambda: "permitido" if (power.read_setting("CPMINCORES") or (0,))[0] >= 100 else "desativado",
             _parking_apply),
    Variable("timer", "Timer do sistema 0,5 ms", "Timer", "Pedido de 0,5 ms pelo TURBO BOOST PRO durante a "
             "captura. No Windows 11 só afeta o jogo com 'pedidos globais de timer' ativos.", "live",
             lambda: "padrão", lambda: "0,5 ms", _timer_apply,
             revert_extra=lambda: winapi.set_timer_resolution(False)),
    Variable("bg_services", "Serviços de fundo pausados", "Segundo plano", "Pausa busca, telemetria e relatórios "
             "de erro durante a medição.", "live", lambda: "rodando", lambda: "pausados", _bg_apply),
    Variable("sysmain", "SysMain (Superfetch)", "Memória", "Pré-carregamento de apps na RAM.", "live",
             lambda: "rodando", lambda: "pausado",
             lambda gid: (journal.group(gid, "Teste: SysMain", "autoopt"),
                          services.stop_temporarily("SysMain", journal, gid)),
             available=lambda: _svc_running("SysMain")),
    Variable("purge", "Limpar cache de RAM antes de jogar", "Memória", "Esvazia o cache em espera e compacta a "
             "memória antes de cada medição (o que 'limpadores de RAM' fazem).", "live",
             lambda: "sem limpeza", lambda: "com limpeza", _purge_apply,
             revert_extra=lambda: _purge_before_capture.update(on=False)),
    Variable("game_mode", "Game Mode do Windows", "Jogo", "Prioriza o jogo e bloqueia atualizações durante a "
             "partida.", "game", lambda: "ativado" if _gm_on() else "desativado",
             lambda: "desativado" if _gm_on() else "ativado",
             lambda gid: _set(gid, "HKCU", _GAMEBAR, "AutoGameModeEnabled", 0 if _gm_on() else 1)),
    Variable("cs2_priority", "Prioridade do cs2.exe", "Prioridade", "Prioridade Alta de CPU/E-S (IFEO) aplicada "
             "a cada abertura do jogo.", "game", lambda: "Alta" if _prio_on() else "Normal",
             lambda: "Normal" if _prio_on() else "Alta", _prio_apply,
             available=lambda: bool(system_mods.find_cs2())),
    Variable("fso", "Tela cheia exclusiva do CS2", "GPU", "Desativa as otimizações de tela cheia só para o cs2.exe.",
             "game", lambda: "exclusiva" if _fso_off() else "padrão (FSO)",
             lambda: "padrão (FSO)" if _fso_off() else "exclusiva", _fso_apply,
             available=lambda: bool(system_mods.find_cs2())),
    Variable("hags", "Agendamento de GPU por hardware (HAGS)", "GPU", "Fila de comandos gerenciada pela GPU.",
             "reboot", lambda: "ativado" if _hags_on() else "desativado",
             lambda: "desativado" if _hags_on() else "ativado",
             lambda gid: _set(gid, "HKLM", _GD, "HwSchMode", 1 if _hags_on() else 2)),
    Variable("mmcss", "MMCSS (prioridade multimídia de jogos)", "Agendamento", "Prioridade de CPU/GPU/E-S das "
             "tarefas de jogo e reserva de CPU para segundo plano.", "reboot",
             lambda: "otimizado" if _mmcss_on() else "padrão", lambda: "padrão" if _mmcss_on() else "otimizado",
             _mmcss_apply),
    Variable("priority_sep", "Prioridade de primeiro plano (Win32PrioritySeparation)", "Prioridade",
             "Quantum curto com bônus para a janela ativa (0x26) x padrão (0x2).", "reboot",
             lambda: f"0x{(_sep_val() or 2):X}", lambda: "0x2" if _sep_val() == 0x26 else "0x26",
             lambda gid: _set(gid, "HKLM", _PRIO, "Win32PrioritySeparation", 2 if _sep_val() == 0x26 else 0x26)),
]
VAR_BY_ID = {v.id: v for v in VARIABLES}


# ============================================================================ ESTATÍSTICA
PRIMARY = [("fps_1low", True, 0.40), ("fps_avg", True, 0.25), ("ft_std", False, 0.20), ("fps_01low", True, 0.15)]


def _ms(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None, None, 0
    m = statistics.mean(vals)
    sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return m, sd, len(vals)


def decide(a: list[dict], b: list[dict]) -> dict:
    """Compara as repetições de A e B. Só declara diferença quando ela supera a margem de erro."""
    if any(t.get("failed") for t in b):
        return {"verdict": "instável", "score": -100.0, "metrics": {}, "note": "O jogo falhou ou travou com B."}
    if not a or not b:
        return {"verdict": "sem dados", "score": 0.0, "metrics": {}}
    metrics, score = {}, 0.0
    sig = {}
    for key, higher, weight in PRIMARY + [("ft_p99", False, 0.0), ("stutter_pct", False, 0.0),
                                          ("latency_ms", False, 0.0), ("cpu_temp_max", False, 0.0),
                                          ("gpu_temp_max", False, 0.0), ("cpu_avg", None, 0.0), ("gpu_avg", None, 0.0)]:
        ma, sa, na = _ms([t.get(key) for t in a])
        mb, sb, nb = _ms([t.get(key) for t in b])
        if ma is None or mb is None or not ma:
            continue
        se = math.sqrt((sa ** 2) / max(na, 1) + (sb ** 2) / max(nb, 1))
        noise = bench.NOISE.get(key, 3.0) / 100 * abs(ma)
        margin = max(2 * se, noise)
        diff = mb - ma
        pct = diff / ma * 100
        significant = abs(diff) > margin and higher is not None
        better = significant and ((diff > 0) == higher)
        metrics[key] = {"a": round(ma, 2), "b": round(mb, 2), "sd_a": round(sa, 2), "sd_b": round(sb, 2),
                        "pct": round(pct, 2), "margin_pct": round(margin / abs(ma) * 100, 2),
                        "significant": significant, "better": better}
        sig[key] = (significant, better)
        if weight and higher is not None:
            score += weight * (pct if higher else -pct) * (1.0 if significant else 0.25)
    low_s, low_b = sig.get("fps_1low", (False, False))
    avg_s, avg_b = sig.get("fps_avg", (False, False))
    std_s, std_b = sig.get("ft_std", (False, False))
    if (low_s and not low_b) or (avg_s and not avg_b):
        verdict = "pior"
    elif (low_s and low_b) or (avg_s and avg_b and not low_s) or (std_s and std_b and not avg_s and not low_s):
        verdict = "melhor"
    else:
        verdict = "igual"
    return {"verdict": verdict, "score": round(score, 2), "metrics": metrics}


# ============================================================================ ESTADO PERSISTENTE
def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"sessions": []}


def save_state(st: dict):
    with _lock:
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, STATE_FILE)


def current_session(st: dict | None = None) -> dict | None:
    st = st or load_state()
    return st["sessions"][-1] if st["sessions"] else None


def _slim(stats: dict) -> dict:
    keep = ("fps_avg", "fps_1low", "fps_01low", "ft_avg", "ft_p99", "ft_std", "stutter_pct", "latency_ms",
            "cpu_avg", "gpu_avg", "ram_used", "cpu_temp_max", "gpu_temp_max", "frames", "bound", "present_mode",
            "time", "failed", "error")
    out = {k: stats.get(k) for k in keep if k in stats}
    out["series"] = (stats.get("series") or [])[::3]
    return out


# ============================================================================ HARDWARE
def hardware_summary() -> dict:
    from .analysis2 import gpu_list
    from .monitor import _cpu_name
    from .storage import list_volumes
    from . import winver
    hw = {"cpu": _cpu_name(), "cores": psutil.cpu_count(False), "threads": psutil.cpu_count(),
          "ram": psutil.virtual_memory().total, "windows": winver.label()}
    if IS_WINDOWS:
        from ..utils import powershell_json
        mods = powershell_json("Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,ConfiguredClockSpeed")
        hw["ram_modules"] = len(mods)
        hw["ram_speed"] = max((m.get("ConfiguredClockSpeed") or 0) for m in mods) if mods else None
        hw["gpus"] = [f"{g['name']} (driver {g['driver']})" for g in gpu_list()]
        hw["disks"] = [f"{v['letter']}: {v['kind']} {v['model'] or ''}" for v in list_volumes()]
    hw["config"] = {v.id: v.state() for v in VARIABLES if _safe(v.available)}
    hw["config"]["power_plan"] = _plan_state()
    return hw


def _safe(fn, default=False):
    try:
        return fn()
    except Exception:
        return default


# ============================================================================ ROTEIRO
def build_steps(var_ids: list[str], reps: int, allow_reboot: bool, mode: str) -> list[dict]:
    vars_ = [VAR_BY_ID[i] for i in var_ids if i in VAR_BY_ID and _safe(VAR_BY_ID[i].available)]
    if mode == "manual" or not allow_reboot:
        vars_ = [v for v in vars_ if v.scope != "reboot"]
    steps: list[dict] = [{"kind": "prepare"}]
    steps += [{"kind": "measure", "var": "__base__", "opt": "A"} for _ in range(reps)]
    for v in [v for v in vars_ if v.scope == "live"]:  # intercalado: AB, BA, AB…
        for r in range(reps):
            order = ("A", "B") if r % 2 == 0 else ("B", "A")
            for opt in order:
                if opt == "B":
                    steps.append({"kind": "apply", "var": v.id})
                steps.append({"kind": "measure", "var": v.id, "opt": opt})
                if opt == "B":
                    steps.append({"kind": "revert", "var": v.id})
    for v in [v for v in vars_ if v.scope == "game"]:
        steps += [{"kind": "measure", "var": v.id, "opt": "A"} for _ in range(reps)]
        steps += [{"kind": "apply", "var": v.id}, {"kind": "restart_game"}]
        steps += [{"kind": "measure", "var": v.id, "opt": "B"} for _ in range(reps)]
        steps += [{"kind": "revert", "var": v.id}, {"kind": "restart_game"}]
    for v in [v for v in vars_ if v.scope == "reboot"]:
        steps += [{"kind": "measure", "var": v.id, "opt": "A"} for _ in range(reps)]
        steps += [{"kind": "apply", "var": v.id}, {"kind": "reboot"}, {"kind": "prepare"}]
        steps += [{"kind": "measure", "var": v.id, "opt": "B"} for _ in range(reps)]
        steps += [{"kind": "revert", "var": v.id}, {"kind": "reboot"}, {"kind": "prepare"}]
    steps += [{"kind": "analyze"}, {"kind": "final_apply"}, {"kind": "restart_game"}]
    steps += [{"kind": "measure", "var": "__final__", "opt": "B"} for _ in range(reps)]
    steps += [{"kind": "final_revert"}, {"kind": "done"}]
    return steps


def estimate_minutes(steps: list[dict], seconds: int, mode: str) -> int:
    per = seconds + (12 if mode == "demo" else 20)
    t = sum(per for s in steps if s["kind"] == "measure")
    t += sum(90 for s in steps if s["kind"] == "restart_game") + sum(180 for s in steps if s["kind"] == "reboot")
    t += 90  # abertura do jogo + demo
    return max(1, round(t / 60))


# ============================================================================ EXECUÇÃO
class Runner:
    def __init__(self, monitor=None):
        self.monitor = monitor
        self.thread: threading.Thread | None = None
        self.cancel = threading.Event()
        self.status = {"text": "Pronto.", "progress": 0.0, "live": None, "running": False, "step": ""}
        self.ask: Callable[[str], bool] | None = None  # prompt para o modo manual (definido pela interface)
        self.demo = None

    # ---------------------------------------------------------------- controle
    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self, var_ids: list[str], reps: int = 3, seconds: int = 30, mode: str = "demo",
              allow_reboot: bool = False, process: str = "cs2.exe"):
        if self.running:
            raise RuntimeError("Um teste já está em execução.")
        steps = build_steps(var_ids, reps, allow_reboot, mode)
        sess = {"id": int(time.time()), "started": time.time(), "mode": mode, "reps": reps, "seconds": seconds,
                "process": process, "vars": var_ids, "steps": steps, "index": 0, "status": "running",
                "hardware": None, "trials": {}, "results": {}, "log": [],
                "var_info": {v: {"title": VAR_BY_ID[v].title, "scope": VAR_BY_ID[v].scope,
                                 "category": VAR_BY_ID[v].category, "a": _safe(VAR_BY_ID[v].state, "?"),
                                 "b": _safe(VAR_BY_ID[v].alt_label, "?")} for v in var_ids if v in VAR_BY_ID}}
        st = load_state()
        st["sessions"].append(sess)
        st["sessions"] = st["sessions"][-20:]
        save_state(st)
        self._launch()

    def resume(self):
        sess = current_session()
        if not sess or sess.get("status") not in ("running", "rebooting"):
            return False
        sess_state = load_state()
        sess_state["sessions"][-1]["status"] = "running"
        save_state(sess_state)
        _remove_resume_task()
        self._launch()
        return True

    def stop(self):
        self.cancel.set()

    def _launch(self):
        self.cancel.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name="AutoOptimizer")
        self.thread.start()

    def _set(self, text=None, progress=None, live=None):
        if text is not None:
            self.status["text"] = text
            log.info("AUTOOPT %s", text)
        if progress is not None:
            self.status["progress"] = progress
        if live is not None:
            self.status["live"] = live

    def _log(self, sess, text):
        sess["log"].append([time.time(), text])
        self._set(text)

    # ---------------------------------------------------------------- laço principal
    def _run(self):
        self.status["running"] = True
        st = load_state()
        sess = st["sessions"][-1]
        try:
            if sess["index"] == 0:
                self._set("Identificando hardware e registrando a configuração atual…")
                sess["hardware"] = hardware_summary()
                self._log(sess, "Criando ponto de restauração e backup…")
                journal.export_copy()
                if settings.get("restore_point_before_changes") and winapi.is_admin():
                    ok, msg = restore_point.create("TURBO BOOST PRO - antes do Auto Optimizer")
                    self._log(sess, msg)
            if sess["mode"] == "demo":
                from .cs2_control import DemoRunner
                self.demo = DemoRunner()
            total = len(sess["steps"])
            while sess["index"] < total:
                if self.cancel.is_set():
                    raise InterruptedError("Teste cancelado pelo usuário.")
                step = sess["steps"][sess["index"]]
                self._set(progress=sess["index"] / total)
                self.status["step"] = f"{sess['index'] + 1}/{total}"
                if self._exec(sess, step) == "reboot":
                    sess["status"] = "rebooting"
                    st["sessions"][-1] = sess
                    save_state(st)
                    return
                sess["index"] += 1
                st["sessions"][-1] = sess
                save_state(st)
            sess["status"] = "done"
            self._set("Teste concluído. Veja os resultados e use APLICAR MELHOR CONFIGURAÇÃO.", 1.0)
        except Exception as e:  # falha ou cancelamento: reverte TUDO o que o teste aplicou
            log.exception("AutoOptimizer")
            sess["status"] = "cancelado" if isinstance(e, InterruptedError) else "falhou"
            sess["error"] = str(e)
            errs = revert_test_changes()
            self._log(sess, f"{'Cancelado' if isinstance(e, InterruptedError) else 'Falha'}: {e}. "
                            f"Configurações de teste revertidas{' com avisos' if errs else ''}.")
        finally:
            st["sessions"][-1] = sess
            save_state(st)
            self.status["running"] = False
            if self.demo:
                try:
                    self.demo.finish()
                except Exception:
                    pass

    def _exec(self, sess, step) -> str | None:
        k = step["kind"]
        if k == "prepare":
            if sess["mode"] == "demo":
                self.demo.ensure_game(self.cancel, lambda t: self._set(t))
                self.demo.prepare(self.cancel, lambda t: self._set(t))
            else:
                self._prompt(f"Abra o {sess['process']} e posicione-se no cenário de teste (sempre o mesmo).")
        elif k == "apply":
            v = VAR_BY_ID[step["var"]]
            self._log(sess, f"Aplicando para teste: {v.title} → {sess['var_info'][v.id]['b']}")
            v.apply_alt(TEST_PREFIX + v.id)
            time.sleep(3)
        elif k == "revert":
            self._revert_var(step["var"])
        elif k == "restart_game":
            if sess["mode"] == "demo":
                self.demo.restart_game(self.cancel, lambda t: self._set(t))
                self.demo.prepare(self.cancel, lambda t: self._set(t))
            else:
                self._prompt(f"Feche e abra novamente o {sess['process']} e volte ao mesmo cenário.")
        elif k == "reboot":
            if self.demo:
                self.demo.close()
            _create_resume_task()
            self._log(sess, "Reiniciando o Windows para aplicar a configuração (o teste continua após o login)…")
            run(["shutdown", "/r", "/t", "20", "/c", "TURBO BOOST PRO: reiniciando para continuar o teste"])
            return "reboot"
        elif k == "measure":
            self._measure(sess, step)
        elif k == "analyze":
            sess["results"] = analyze_session(sess)
            self._log(sess, "Resultados individuais calculados.")
        elif k == "final_apply":
            winners = [v for v, r in sess["results"].items() if r.get("verdict") == "melhor"
                       and VAR_BY_ID[v].scope != "reboot"]
            sess["winners_live"] = winners
            if not winners:
                self._log(sess, "Nenhuma alteração superou a margem de erro: a configuração atual já é a melhor.")
                sess["index"] = len(sess["steps"]) - 3  # pula a validação combinada
                return None
            for v in winners:
                VAR_BY_ID[v].apply_alt(TEST_PREFIX + v)
            self._log(sess, "Validando a combinação vencedora: " + ", ".join(VAR_BY_ID[v].title for v in winners))
        elif k == "final_revert":
            revert_test_changes()
            base = sess["trials"].get("__base__", {}).get("A", [])
            fin = sess["trials"].get("__final__", {}).get("B", [])
            if base and fin:
                sess["combined"] = decide(base, fin)
                self._log(sess, f"Combinação x configuração inicial: {sess['combined']['verdict']}")
        elif k == "done":
            pass
        return None

    def _revert_var(self, vid):
        v = VAR_BY_ID[vid]
        journal.revert_group(TEST_PREFIX + vid)
        if v.revert_extra:
            v.revert_extra()
        time.sleep(2)

    def _prompt(self, text):
        if not self.ask or not self.ask(text):
            raise InterruptedError("Teste cancelado no modo manual.")

    def _measure(self, sess, step):
        vid, opt = step["var"], step["opt"]
        title = {"__base__": "Linha de base", "__final__": "Combinação vencedora"}.get(vid) or VAR_BY_ID[vid].title
        label = f"{title} · {'A' if opt == 'A' else 'B'}"
        if sess["mode"] == "demo":
            self.demo.seek(self.cancel, lambda t: self._set(t))
        else:
            self._prompt(f"Medição: {label}. Volte ao mesmo cenário; a captura começa 8 s após o OK.")
            time.sleep(8)
        if _purge_before_capture["on"]:
            memory.optimize_ram(deep=True)
            time.sleep(2)
        attempts = 0
        while True:
            attempts += 1
            try:
                stats = bench.capture(sess["process"], sess["seconds"], f"Auto: {label}", self.monitor,
                                      lambda p, t: self._set(f"{label}: {t}"), save=False,
                                      live=lambda d: self._set(live=d), cancel=self.cancel)
                break
            except bench.BenchError as e:
                if self.cancel.is_set():
                    raise InterruptedError("Teste cancelado.")
                from .cs2_control import cs2_pid
                crashed = sess["process"] == "cs2.exe" and not cs2_pid()
                if attempts >= 2 or crashed:
                    stats = {"failed": True, "error": str(e)}
                    self._log(sess, f"Medição falhou ({label}): {e}")
                    if crashed and sess["mode"] == "demo":
                        self.demo.restart_game(self.cancel, lambda t: self._set(t))
                        self.demo.prepare(self.cancel, lambda t: self._set(t))
                    break
                self._log(sess, f"Repetindo medição ({e})")
                if sess["mode"] == "demo":
                    self.demo.prepare(self.cancel, lambda t: self._set(t))
        sess["trials"].setdefault(vid, {}).setdefault(opt, []).append(_slim(stats))
        if not stats.get("failed"):
            self._log(sess, f"{label}: {stats['fps_avg']:.0f} FPS · 1% low {stats['fps_1low']:.0f} · "
                            f"variação {stats['ft_std']:.2f} ms")


def analyze_session(sess: dict) -> dict:
    res = {}
    for vid, opts in sess["trials"].items():
        if vid.startswith("__"):
            continue
        res[vid] = decide(opts.get("A", []), opts.get("B", []))
    return res


def revert_test_changes() -> list[str]:
    errs = journal.revert_all(TEST_PREFIX)
    winapi.set_timer_resolution(False)
    _purge_before_capture["on"] = False
    return errs


# ============================================================================ MELHOR CONFIGURAÇÃO
def best_config(sess: dict | None = None) -> list[dict]:
    sess = sess or current_session()
    if not sess:
        return []
    results = sess.get("results") or analyze_session(sess)
    out = []
    for vid, r in sorted(results.items(), key=lambda kv: -kv[1].get("score", 0)):
        if r.get("verdict") != "melhor" or vid not in VAR_BY_ID:
            continue
        if vid == "purge":
            continue  # nunca torna permanente uma limpeza de memória
        info = sess["var_info"].get(vid, {})
        out.append({"var": vid, "title": VAR_BY_ID[vid].title, "from": info.get("a"), "to": info.get("b"),
                    "score": r.get("score"), "gain_1low": r["metrics"].get("fps_1low", {}).get("pct"),
                    "gain_avg": r["metrics"].get("fps_avg", {}).get("pct"), "scope": VAR_BY_ID[vid].scope})
    if sess.get("combined") and sess["combined"].get("verdict") == "pior":
        out = out[:1]  # combinação piorou: mantém só a melhor alteração isolada
    return out


def apply_best(sess: dict | None = None) -> list[str]:
    """Aplica de forma persistente (e reversível) as alterações vencedoras."""
    msgs = []
    for item in best_config(sess):
        vid = item["var"]
        if vid == "timer":
            settings.set("timer_mode", "on")
            msgs.append("✔ Timer 0,5 ms habilitado durante jogos (Modo CS2/sessões)")
            continue
        if vid == "bg_services":
            settings.set("cs2_auto_session", True)
            msgs.append("✔ Modo CS2 automático ativado (pausa os serviços de fundo enquanto o jogo roda)")
            continue
        if vid == "sysmain":
            ok, m = services.set_start("SysMain", "demand", journal)
            msgs.append(("✔ " if ok else "⚠ ") + m)
            continue
        gid = APPLIED_PREFIX + vid
        if journal.has_group(gid):
            continue
        VAR_BY_ID[vid].apply_alt(gid)
        journal.group(gid)["title"] = f"Auto Optimizer: {item['title']} → {item['to']}"
        journal.save()
        msgs.append(f"✔ {item['title']}: {item['from']} → {item['to']}"
                    + (" (requer reiniciar)" if item["scope"] == "reboot" else ""))
    return msgs or ["Nenhuma alteração comprovadamente melhor: sua configuração atual foi mantida."]


def restore_all() -> list[str]:
    errs = revert_test_changes()
    errs += journal.revert_all(APPLIED_PREFIX)
    return errs


# ============================================================================ RETOMADA APÓS REINÍCIO
_TASK = "TurboBoostPro_AutoOptimizer_Resume"


def _launch_command() -> tuple[str, str]:
    if getattr(sys, "frozen", False):
        return sys.executable, "--resume-autoopt"
    exe = sys.executable.replace("python.exe", "pythonw.exe")
    main = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "main.py")
    return exe, f'"{main}" --resume-autoopt'


def _create_resume_task():
    exe, args = _launch_command()
    for ch in ("'", "`", "$"):
        if ch in exe or ch in args:
            raise RuntimeError("Caminho do aplicativo com caracteres não suportados para a retomada automática.")
    r = powershell(
        f"$a = New-ScheduledTaskAction -Execute '{exe}' -Argument '{args}'; "
        "$u = \"$env:USERDOMAIN\\$env:USERNAME\"; "
        "$t = New-ScheduledTaskTrigger -AtLogOn -User $u; "
        "$p = New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive -RunLevel Highest; "
        f"Register-ScheduledTask -TaskName '{_TASK}' -Action $a -Trigger $t -Principal $p -Force | Out-Null")
    if r.returncode != 0:
        raise RuntimeError("Não foi possível agendar a retomada após o reinício: " + (r.stderr or "")[:150])


def _remove_resume_task():
    if IS_WINDOWS:
        powershell(f"Unregister-ScheduledTask -TaskName '{_TASK}' -Confirm:$false -ErrorAction SilentlyContinue")


def recover_on_start(resuming: bool) -> str | None:
    """Ao abrir o app: se um teste foi interrompido (falha/queda de energia), reverte as configurações de teste."""
    sess = current_session()
    if not sess or sess.get("status") not in ("running", "rebooting"):
        return None
    if resuming and sess.get("status") == "rebooting":
        return "resume"
    st = load_state()
    st["sessions"][-1]["status"] = "interrompido"
    save_state(st)
    _remove_resume_task()
    errs = revert_test_changes()
    return "Um teste do Auto Optimizer foi interrompido; as configurações de teste foram revertidas" + \
        (f" (avisos: {'; '.join(errs[:3])})." if errs else ".")
