"""Benchmark integrado com PresentMon (Intel, MIT): FPS médio, 1% low, 0,1% low, frametime, latência,
modo de apresentação, CPU/GPU-bound, uso de CPU/GPU/RAM e processos concorrentes.

O PresentMon lê eventos ETW do Windows (DXGI/D3D/Vulkan): não injeta código no jogo, não lê a memória do
processo e é seguro para anti-cheats como o VAC.

Definições:
- FPS médio = quadros / tempo total
- 1% low  = 1000 / percentil 99 do frametime  (0,1% low = percentil 99,9)
- Travadas = quadros com frametime > 2x a mediana
"""
from __future__ import annotations

import csv
import json
import os
import statistics
import subprocess
import threading
import time
from typing import Callable

import psutil

from ..config import DATA_DIR, IS_WINDOWS, resource_path, settings
from ..utils import CREATE_NO_WINDOW, log

BENCH_DIR = DATA_DIR / "benchmarks"
BENCH_DIR.mkdir(exist_ok=True)
BENCH_FILE = DATA_DIR / "benchmarks.json"
_lock = threading.Lock()

FT_COLS = ("MsBetweenPresents", "FrameTime", "msBetweenPresents", "MsBetweenAppStart")
LAT_COLS = (("MsPCLatency", "Latência PC (Reflex)"), ("MsAllInputToPhotonLatency", "Entrada até a tela"),
            ("MsClickToPhotonLatency", "Clique até a tela"), ("DisplayLatency", "Início do quadro até a tela"),
            ("MsUntilDisplayed", "Present até a tela"))


class BenchError(RuntimeError):
    pass


def presentmon_path() -> str | None:
    cands = [settings.get("presentmon_path") or "", resource_path(os.path.join("tools", "PresentMon.exe")),
             str(DATA_DIR / "PresentMon.exe")]
    return next((c for c in cands if c and os.path.isfile(c)), None)


def _num(v):
    try:
        f = float(v)
        return f if f == f else None  # descarta NaN
    except (TypeError, ValueError):
        return None


def _pct(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def parse_csv(path: str) -> dict:
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise BenchError("Nenhum quadro capturado. O jogo estava aberto e renderizando (fora do menu minimizado)?")
    cols = rows[0].keys()
    ft_col = next((c for c in FT_COLS if c in cols), None)
    if not ft_col:
        raise BenchError(f"Formato do PresentMon não reconhecido (colunas: {list(cols)[:8]}…)")
    fts = [v for r in rows if (v := _num(r.get(ft_col))) and 0 < v < 1000]
    if len(fts) < 30:
        raise BenchError("Poucos quadros capturados para uma medição confiável.")
    s = sorted(fts)
    total = sum(fts)
    med = statistics.median(fts)
    stats = {
        "frames": len(fts), "duration_s": round(total / 1000, 1),
        "fps_avg": round(len(fts) / (total / 1000), 1),
        "fps_1low": round(1000 / _pct(s, 0.99), 1), "fps_01low": round(1000 / _pct(s, 0.999), 1),
        "ft_avg": round(total / len(fts), 3), "ft_p99": round(_pct(s, 0.99), 3),
        "ft_std": round(statistics.pstdev(fts), 3), "stutters": sum(1 for v in fts if v > 2 * med),
        "series": [round(v, 2) for v in fts[:: max(1, len(fts) // 600)]],
    }
    stats["stutter_pct"] = round(stats["stutters"] / len(fts) * 100, 2)
    for col, label in LAT_COLS:
        if col in cols:
            vals = [v for r in rows if (v := _num(r.get(col))) is not None and 0 <= v < 1000]
            if len(vals) > len(fts) * 0.5:
                stats["latency_ms"] = round(statistics.mean(vals), 2)
                stats["latency_kind"] = label
                break
    cpu_busy = [v for r in rows if (v := _num(r.get("MsCPUBusy"))) is not None]
    gpu_busy = [v for r in rows if (v := _num(r.get("MsGPUBusy") or r.get("MsGPUTime"))) is not None]
    if cpu_busy and gpu_busy:
        stats["cpu_busy_ms"] = round(statistics.mean(cpu_busy), 2)
        stats["gpu_busy_ms"] = round(statistics.mean(gpu_busy), 2)
        ratio = stats["gpu_busy_ms"] / stats["ft_avg"]
        stats["bound"] = "GPU" if ratio > 0.85 else "CPU"
    if "PresentMode" in cols:
        modes = [r.get("PresentMode") for r in rows if r.get("PresentMode")]
        if modes:
            stats["present_mode"] = max(set(modes), key=modes.count)
    if "AllowsTearing" in cols:
        stats["tearing"] = any(r.get("AllowsTearing") == "1" for r in rows[:200])
    return stats


def config_snapshot() -> dict:
    """Estado das configurações que afetam o resultado (para comparar maçãs com maçãs)."""
    from . import power, registry as reg, winapi
    snap = {"plan": (power.active_plan() or {}).get("name"), "timer_ms": None,
            "hags": None, "global_timer": False, "profiles": []}
    tr = winapi.query_timer_resolution()
    if tr:
        snap["timer_ms"] = round(tr["current"], 3)
    ok, _t, v = reg.read_value("HKLM", r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode")
    snap["hags"] = (v == 2) if ok else None
    ok, _t, v = reg.read_value("HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\kernel",
                               "GlobalTimerResolutionRequests")
    snap["global_timer"] = bool(ok and v == 1)
    from .journal import journal
    snap["profiles"] = [g for g in ("profile:ultra_lite", "profile:gaming_edition", "profile:stage2",
                                    "session:turbo", "session:cs2") if journal.has_group(g)]
    snap["app_timer"] = winapi.timer_resolution_active()
    try:
        from .system_mods import cs2_status
        snap["cs2_fso_off"] = bool(cs2_status().get("fso_off"))
    except Exception:
        snap["cs2_fso_off"] = None
    snap["cpu_profile"] = settings.get("cpu_profile")
    return snap


def last_pair_by(key: str, process: str = "cs2.exe") -> tuple[dict, dict] | None:
    """As duas capturas mais recentes do processo com valores DIFERENTES para a configuração 'key'."""
    runs = [r for r in load() if r.get("process") == process]
    if not runs:
        return None
    last = runs[-1]
    for r in reversed(runs[:-1]):
        if r.get("config", {}).get(key) != last.get("config", {}).get(key):
            return r, last
    return None


def capture(process: str = "cs2.exe", seconds: int = 60, label: str = "", monitor=None,
            progress: Callable[[float, str], None] | None = None, save: bool = True) -> dict:
    from . import winapi
    if not IS_WINDOWS:
        raise BenchError("Benchmark disponível apenas no Windows.")
    pm = presentmon_path()
    if not pm:
        raise BenchError("PresentMon não encontrado. Ele vem com o instalador; reinstale o TURBO BOOST PRO ou "
                         "indique o PresentMon.exe nas opções do benchmark.")
    if not winapi.is_admin():
        raise BenchError("O benchmark precisa de administrador (leitura de eventos ETW de desempenho).")
    procs = [p for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() == process.lower()]
    if not procs:
        raise BenchError(f"{process} não está em execução. Abra o jogo, entre no mapa e inicie a captura.")
    out = str(BENCH_DIR / f"capture_{int(time.time())}.csv")
    cmd = [pm, "--process_name", process, "--output_file", out, "--timed", str(seconds), "--terminate_after_timed",
           "--stop_existing_session", "--session_name", "TurboBoostPro", "--no_console_stats"]
    log.info("BENCH %s", " ".join(cmd))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW)
    usage = {"cpu": [], "gpu": [], "ram": []}
    competitors: dict[str, float] = {}
    sample_procs = {}
    t0 = time.time()
    psutil.cpu_percent(None)
    while p.poll() is None:
        time.sleep(1)
        el = time.time() - t0
        if progress:
            progress(min(0.99, el / (seconds + 3)), f"Capturando {process}: {int(el)}/{seconds} s")
        snap = monitor.get() if monitor else {}
        usage["cpu"].append(snap.get("cpu", psutil.cpu_percent(None)))
        if snap.get("gpu") is not None:
            usage["gpu"].append(snap["gpu"])
        usage["ram"].append(snap.get("ram_used", psutil.virtual_memory().used))
        if int(el) % 5 == 0:  # processos concorrentes (CPU fora do jogo)
            for q in psutil.process_iter(["pid", "name"]):
                n = (q.info["name"] or "").lower()
                if n in (process.lower(), "system idle process", "idle", ""):
                    continue
                try:
                    obj = sample_procs.setdefault(q.pid, q)
                    c = obj.cpu_percent(None) / (psutil.cpu_count() or 1)
                    competitors[n] = max(competitors.get(n, 0.0), c)
                except psutil.Error:
                    pass
        if el > seconds + 30:
            p.kill()
            raise BenchError("PresentMon não terminou no tempo esperado.")
    output = (p.stdout.read() or b"").decode(errors="replace") if p.stdout else ""
    if not os.path.exists(out):
        raise BenchError("PresentMon não gerou dados. " + output.strip()[-300:])
    stats = parse_csv(out)
    stats.update({
        "id": int(time.time() * 1000), "time": time.time(), "label": label or "Benchmark", "process": process,
        "seconds": seconds, "cpu_avg": round(statistics.mean(usage["cpu"]), 1) if usage["cpu"] else None,
        "gpu_avg": round(statistics.mean(usage["gpu"]), 1) if usage["gpu"] else None,
        "ram_used": int(statistics.mean(usage["ram"])) if usage["ram"] else None,
        "competitors": sorted(([n, round(c, 1)] for n, c in competitors.items() if c >= 1.0),
                              key=lambda x: -x[1])[:8],
        "config": config_snapshot(), "csv": out,
    })
    if save:
        with _lock:
            data = load()
            data.append(stats)
            _save(data[-80:])
    log.info("BENCH resultado %s: %.1f FPS, 1%% low %.1f", label, stats["fps_avg"], stats["fps_1low"])
    return stats


def load() -> list[dict]:
    try:
        return json.loads(BENCH_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(data):
    tmp = BENCH_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, BENCH_FILE)


def delete(run_id: int):
    with _lock:
        _save([r for r in load() if r["id"] != run_id])


METRICS = [("fps_avg", "FPS médio", True), ("fps_1low", "1% low (FPS)", True), ("fps_01low", "0,1% low (FPS)", True),
           ("ft_avg", "Frametime médio (ms)", False), ("ft_p99", "Frametime P99 (ms)", False),
           ("ft_std", "Variação do frametime (ms)", False), ("stutter_pct", "Travadas (%)", False),
           ("latency_ms", "Latência (ms)", False), ("cpu_avg", "Uso de CPU (%)", None), ("gpu_avg", "Uso de GPU (%)", None)]

# Diferenças menores que isso estão dentro do ruído normal entre duas capturas.
NOISE = {"fps_avg": 2.0, "fps_1low": 4.0, "fps_01low": 8.0, "ft_avg": 2.0, "ft_p99": 4.0, "ft_std": 8.0,
         "stutter_pct": 25.0, "latency_ms": 5.0}


def compare(a: dict, b: dict) -> list[dict]:
    rows = []
    for key, label, higher_better in METRICS:
        va, vb = a.get(key), b.get(key)
        if va is None or vb is None:
            continue
        pct = (vb - va) / va * 100 if va else 0.0
        if higher_better is None or abs(pct) < NOISE.get(key, 3.0):
            verdict = "igual" if higher_better is not None else ""
        else:
            verdict = "melhor" if (pct > 0) == higher_better else "pior"
        rows.append({"key": key, "label": label, "a": va, "b": vb, "pct": pct, "verdict": verdict})
    return rows


def verdict(rows: list[dict]) -> str:
    w = {r["key"]: r["verdict"] for r in rows}
    if w.get("fps_1low") == "melhor" and w.get("fps_avg") != "pior":
        return "GANHO REAL: 1% low melhor (menos quedas de FPS)."
    if w.get("fps_avg") == "melhor" and w.get("fps_1low") != "pior":
        return "Ganho de FPS médio sem piorar as quedas."
    if "pior" in (w.get("fps_1low"), w.get("fps_avg")):
        return "PIOROU: reverta a última alteração."
    return "Sem diferença além do ruído de medição: a alteração não ajudou nem atrapalhou."


# ============================================================================ TESTE A/B DO TIMER
def ab_test_timer(process: str = "cs2.exe", seg: int = 20, rounds: int = 2, monitor=None,
                  progress: Callable[[float, str], None] | None = None) -> dict:
    """Alterna timer padrão/0,5 ms (off, on, off, on…) no MESMO cenário e mede. Decide com base no 1% low."""
    from . import winapi
    results = {"off": [], "on": []}
    order = ["off", "on"] * rounds
    try:
        for i, state in enumerate(order):
            winapi.set_timer_resolution(state == "on")
            time.sleep(2)

            def prog(p, t, i=i):
                if progress:
                    progress((i + p) / len(order), f"Etapa {i + 1}/{len(order)} (timer {'0,5 ms' if state == 'on' else 'padrão'}): {t}")
            results[state].append(capture(process, seg, f"A/B timer {state}", monitor, prog, save=False))
    finally:
        winapi.set_timer_resolution(False)

    def agg(lst, key):
        vals = [r[key] for r in lst if r.get(key) is not None]
        return round(statistics.mean(vals), 2) if vals else None
    summary = {s: {k: agg(results[s], k) for k in ("fps_avg", "fps_1low", "fps_01low", "ft_std", "latency_ms")}
               for s in results}
    a, b = summary["off"], summary["on"]
    rows = compare(a, b)
    gain_low = (b["fps_1low"] - a["fps_1low"]) / a["fps_1low"] * 100 if a["fps_1low"] else 0
    recommend = gain_low >= NOISE["fps_1low"] and next((r for r in rows if r["key"] == "fps_avg"),
                                                        {"verdict": ""})["verdict"] != "pior"
    settings.set("timer_mode", "on" if recommend else "off")
    cfg = config_snapshot()
    note = "" if cfg["global_timer"] else ("No Windows 11 o pedido de timer de outro programa NÃO afeta o jogo, a "
                                            "menos que 'Pedidos globais de timer' esteja ativo (requer reinício). "
                                            "Por isso um resultado 'sem diferença' é o esperado.")
    result = {"time": time.time(), "summary": summary, "rows": rows, "gain_1low_pct": round(gain_low, 1),
              "recommend": recommend, "note": note, "global_timer": cfg["global_timer"]}
    settings.set("timer_ab_result", result)
    log.info("A/B timer: %s", result)
    return result
