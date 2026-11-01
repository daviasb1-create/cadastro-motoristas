"""Diagnóstico automático ("ANALISAR MEU PC"): hardware, gargalos, configurações e relatório."""
from __future__ import annotations

import html
import os
import platform
import time
from dataclasses import dataclass, field

import psutil

from ..config import IS_WINDOWS, REPORT_DIR
from ..utils import fmt_bytes, powershell_json
from . import power, processes, services, startup, storage
from .tweaks import TWEAKS_BY_ID


@dataclass
class Finding:
    severity: str          # "critico" | "alto" | "medio" | "info" | "ok"
    area: str
    title: str
    detail: str
    action: str = ""       # ex.: "tweak:game_mode", "power", "page:cleaner", "ram"
    action_label: str = ""


@dataclass
class Report:
    score: int = 100
    hardware: dict = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    top_cpu: list[dict] = field(default_factory=list)
    top_ram: list[dict] = field(default_factory=list)
    bottleneck: str = ""
    samples: dict = field(default_factory=dict)
    created: float = field(default_factory=time.time)


PENALTY = {"critico": 20, "alto": 10, "medio": 5, "info": 0, "ok": 0}


def _hardware() -> dict:
    hw = {"os": f"{platform.system()} {platform.release()} ({platform.version()})",
          "ram_total": psutil.virtual_memory().total, "cores": psutil.cpu_count(False),
          "threads": psutil.cpu_count(), "gpus": [], "ram_speed": None, "ram_modules": 0}
    if IS_WINDOWS:
        for g in powershell_json("Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,"
                                 "DriverVersion,DriverDate,CurrentRefreshRate,CurrentHorizontalResolution,"
                                 "CurrentVerticalResolution"):
            hw["gpus"].append(g)
        mem = powershell_json("Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,Speed,"
                              "ConfiguredClockSpeed")
        hw["ram_modules"] = len(mem)
        speeds = [m.get("ConfiguredClockSpeed") or m.get("Speed") for m in mem if m]
        hw["ram_speed"] = max([s for s in speeds if s] or [0]) or None
        cs = powershell_json("Get-CimInstance Win32_ComputerSystem | Select-Object PCSystemType,Model,Manufacturer")
        hw["laptop"] = bool(cs and cs[0].get("PCSystemType") == 2)
        hw["model"] = f"{cs[0].get('Manufacturer', '')} {cs[0].get('Model', '')}".strip() if cs else ""
        hw["volumes"] = storage.list_volumes()
    return hw


def analyze(monitor=None, progress=None) -> Report:
    rep = Report()
    F = rep.findings.append

    def step(p, text):
        if progress:
            progress(p, text)

    # ------------------------------------------------------------- amostragem de uso
    step(0.05, "Medindo uso de CPU, GPU, RAM e disco por 6 segundos…")
    cpu_s, gpu_s, ram_s, disk_s, temps = [], [], [], [], []
    for _ in range(6):
        time.sleep(1)
        snap = monitor.get() if monitor else {}
        cpu_s.append(snap.get("cpu", psutil.cpu_percent()))
        ram_s.append(snap.get("ram", psutil.virtual_memory().percent))
        if snap.get("gpu") is not None:
            gpu_s.append(snap["gpu"])
        disk_s.append(snap.get("disk", 0))
        if snap.get("cpu_temp"):
            temps.append(snap["cpu_temp"])
    avg = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
    rep.samples = {"cpu": avg(cpu_s), "gpu": avg(gpu_s), "ram": avg(ram_s), "disk": avg(disk_s),
                   "cpu_temp": max(temps) if temps else None}

    step(0.25, "Identificando hardware…")
    hw = _hardware()
    rep.hardware = hw
    snap = monitor.get() if monitor else {}
    hw["cpu_name"] = snap.get("cpu_name", platform.processor())
    hw["gpu_name"] = snap.get("gpu_name") or ", ".join(g.get("Name", "") for g in hw.get("gpus", []))

    # ------------------------------------------------------------- hardware / gargalos
    ram_gb = hw["ram_total"] / 1024 ** 3
    if ram_gb < 7.5:
        F(Finding("critico", "Hardware", f"Pouca memória RAM ({ram_gb:.0f} GB)",
                  "Windows 11 + jogos atuais exigem 16 GB. Com menos de 8 GB o sistema usa o disco como "
                  "memória (paginação), causando travamentos. Recomendação: upgrade para 16 GB."))
    elif ram_gb < 15:
        F(Finding("medio", "Hardware", f"RAM de {ram_gb:.0f} GB",
                  "Suficiente para uso geral; jogos recentes rodam melhor com 16 GB ou mais."))
    if hw.get("ram_modules") == 1:
        F(Finding("alto", "Hardware", "Memória em canal único (1 pente)",
                  "Com um único módulo a RAM opera em single channel, reduzindo a banda pela metade. Em "
                  "GPUs integradas e jogos dependentes de CPU a perda pode passar de 20% de FPS. Use 2 pentes "
                  "iguais."))
    for v in hw.get("volumes", []):
        if v["letter"] and v["letter"].upper() == os.environ.get("SystemDrive", "C:")[0].upper() and v["kind"] == "HDD":
            F(Finding("critico", "Hardware", "Windows instalado em HD mecânico",
                      "Este é o maior gargalo possível de um PC atual: inicialização, abertura de apps e "
                      "carregamento de jogos ficam 5-10x mais lentos. Recomendação: migrar para SSD."))
        if v["size"] and v["free"] / v["size"] < 0.10:
            F(Finding("alto", "Armazenamento", f"Unidade {v['letter']}: quase cheia "
                      f"({fmt_bytes(v['free'])} livres)",
                      "Menos de 10% livre degrada o desempenho (principalmente em SSD) e impede atualizações.",
                      "page:cleaner", "Abrir Limpeza"))
    cpu_avg, gpu_avg = rep.samples["cpu"] or 0, rep.samples["gpu"]
    if cpu_avg > 85:
        rep.bottleneck = "CPU"
    elif gpu_avg is not None and gpu_avg > 90:
        rep.bottleneck = "GPU"
    elif (rep.samples["ram"] or 0) > 88:
        rep.bottleneck = "RAM"
    elif (rep.samples["disk"] or 0) > 85:
        rep.bottleneck = "Disco"
    if rep.bottleneck:
        F(Finding("alto", "Desempenho", f"Gargalo detectado agora: {rep.bottleneck}",
                  f"Durante a análise, {rep.bottleneck} ficou acima do limite. Veja os processos pesados abaixo."))
    if rep.samples["ram"] and rep.samples["ram"] > 80:
        F(Finding("alto", "Memória", f"Uso de RAM alto ({rep.samples['ram']:.0f}%)",
                  "Feche programas ou libere a RAM antes de jogar.", "ram", "Liberar RAM"))
    t = rep.samples["cpu_temp"]
    if t and t > 90:
        F(Finding("critico", "Temperatura", f"CPU muito quente ({t:.0f} °C)",
                  "Acima de 90 °C a CPU reduz a frequência (thermal throttling). Limpe o cooler, troque a "
                  "pasta térmica e verifique a ventilação do gabinete/notebook."))
    elif t and t > 80:
        F(Finding("medio", "Temperatura", f"CPU aquecida ({t:.0f} °C)", "Verifique ventilação e poeira."))

    # ------------------------------------------------------------- sistema
    step(0.5, "Verificando configurações do Windows…")
    try:
        up_days = (time.time() - psutil.boot_time()) / 86400
        if up_days > 7:
            F(Finding("medio", "Sistema", f"PC ligado há {up_days:.0f} dias sem reiniciar",
                      "Reiniciar limpa vazamentos de memória de drivers/apps e aplica atualizações pendentes. "
                      "(A 'Inicialização rápida' do Windows faz o desligar não zerar o sistema.)"))
    except Exception:
        pass
    if IS_WINDOWS:
        plan = power.active_plan()
        if plan and plan["guid"] not in (power.ULTIMATE, power.HIGH) and plan["name"] != power.PLAN_NAME:
            F(Finding("alto", "Energia", f"Plano de energia: {plan['name']}",
                      "O plano atual permite que a CPU reduza frequência e estacione núcleos, gerando quedas "
                      "de FPS e atraso de resposta.", "power", "Ativar plano TURBO"))
        bat = psutil.sensors_battery()
        if bat and not bat.power_plugged:
            F(Finding("info", "Energia", "Notebook na bateria",
                      "Na bateria, CPU e GPU operam com limites menores. Para jogar, conecte o carregador."))
    tweak_checks = [("game_mode", "alto"), ("game_dvr_off", "medio"), ("mmcss_games", "medio"),
                    ("windowed_opt", "medio"), ("hags", "info"), ("power_throttling_off", "medio"),
                    ("visual_anim", "info"), ("bg_apps", "medio"), ("widgets_off", "info"), ("edge_bg", "info"),
                    ("network_throttling", "info"), ("delivery_opt", "info")]
    for tid, sev in tweak_checks:
        tw = TWEAKS_BY_ID[tid]
        if tw.status() not in ("aplicado", "indisponivel"):
            F(Finding(sev, "Configuração", f"Não otimizado: {tw.title}", tw.description + " " + tw.benefit,
                      f"tweak:{tid}", "Aplicar"))

    step(0.65, "Analisando programas de inicialização…")
    entries = [e for e in startup.list_entries() if e["enabled"]]
    heavy = [e for e in entries if e["rec"] == "desativar"]
    if len(entries) > 8 or heavy:
        F(Finding("alto" if len(heavy) > 3 else "medio", "Inicialização",
                  f"{len(entries)} programas iniciam com o Windows ({len(heavy)} desnecessários)",
                  "Desnecessários: " + (", ".join(e["name"] for e in heavy[:8]) or "-"),
                  "page:performance", "Gerenciar"))

    step(0.75, "Analisando serviços…")
    for s in services.catalog_status():
        if s["rec"] == "manual" and s["start"] in ("auto", "delayed-auto"):
            F(Finding("info", "Serviços", f"Serviço otimizável: {s['label']}", s["desc"],
                      f"service:{s['name']}", "Definir Manual"))

    step(0.85, "Identificando programas pesados…")
    processes.top_processes("cpu", 1)
    time.sleep(1.0)
    procs = processes.sampler.sample()
    rep.top_cpu = sorted(procs, key=lambda p: p["cpu"], reverse=True)[:8]
    rep.top_ram = sorted(procs, key=lambda p: p["mem"], reverse=True)[:8]
    for p in rep.top_ram[:5]:
        if p["mem"] > 1.5 * 1024 ** 3 and not p["protected"]:
            F(Finding("medio", "Processos", f"{p['name']} usa {fmt_bytes(p['mem'])} de RAM",
                      "Feche-o antes de jogar se não estiver em uso."))
    for p in rep.top_cpu[:5]:
        if p["cpu"] > 25 and not p["protected"]:
            F(Finding("medio", "Processos", f"{p['name']} usa {p['cpu']:.0f}% de CPU",
                      "Programa pesado em execução agora."))
    bg = processes.find_background_apps()
    if bg:
        F(Finding("medio", "Processos", f"{len(bg)} apps desnecessários em segundo plano",
                  ", ".join(a["label"] for a in bg[:8]) + f" ({fmt_bytes(sum(a['mem'] for a in bg))})",
                  "turbo", "TURBO MODE"))

    if not any(f.severity in ("critico", "alto", "medio") for f in rep.findings):
        F(Finding("ok", "Geral", "Nenhum problema importante encontrado", "Seu PC está bem otimizado."))
    order = {"critico": 0, "alto": 1, "medio": 2, "info": 3, "ok": 4}
    rep.findings.sort(key=lambda f: order[f.severity])
    rep.score = max(0, 100 - sum(PENALTY[f.severity] for f in rep.findings))
    step(1.0, "Análise concluída")
    return rep


SEV_LABEL = {"critico": "CRÍTICO", "alto": "ALTO", "medio": "MÉDIO", "info": "INFO", "ok": "OK"}
SEV_COLOR = {"critico": "#ff3b5c", "alto": "#ff9f1c", "medio": "#ffd23f", "info": "#00d4ff", "ok": "#2ee59d"}


def export_html(rep: Report) -> str:
    e = html.escape
    hw = rep.hardware
    rows = "".join(
        f"<tr><td><span class='sev' style='background:{SEV_COLOR[f.severity]}'>{SEV_LABEL[f.severity]}</span></td>"
        f"<td>{e(f.area)}</td><td><b>{e(f.title)}</b><br><small>{e(f.detail)}</small></td></tr>"
        for f in rep.findings)
    procs = "".join(f"<tr><td>{e(p['name'])}</td><td>{p['cpu']:.1f}%</td><td>{fmt_bytes(p['mem'])}</td></tr>"
                    for p in rep.top_ram)
    s = rep.samples
    fmt = lambda v, suf="%": "-" if v is None else f"{v:.0f}{suf}"  # noqa: E731
    doc = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>Relatório TURBO BOOST PRO</title><style>
body{{background:#0a0e17;color:#dce6f5;font-family:Segoe UI,Arial;margin:32px}}
h1{{color:#00d4ff;letter-spacing:2px}} h2{{color:#00d4ff;border-bottom:1px solid #1f2a3d;padding-bottom:6px}}
table{{width:100%;border-collapse:collapse}} td,th{{padding:8px;border-bottom:1px solid #1f2a3d;text-align:left;vertical-align:top}}
.sev{{color:#000;font-weight:700;padding:2px 8px;border-radius:4px;font-size:12px}}
.score{{font-size:56px;color:#00d4ff;font-weight:800}} small{{color:#8a9bb5}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}}
.card{{background:#111827;border:1px solid #1f2a3d;border-radius:10px;padding:14px}}
</style></head><body>
<h1>⚡ TURBO BOOST PRO · Relatório de Diagnóstico</h1>
<p>{time.strftime('%d/%m/%Y %H:%M', time.localtime(rep.created))}</p>
<div class="score">{rep.score}/100</div>
<p>Gargalo atual: <b>{rep.bottleneck or 'nenhum'}</b></p>
<h2>Hardware</h2><div class="grid">
<div class="card"><small>Processador</small><br>{e(str(hw.get('cpu_name', '')))}<br>
<small>{hw.get('cores')} núcleos / {hw.get('threads')} threads</small></div>
<div class="card"><small>Placa de vídeo</small><br>{e(str(hw.get('gpu_name', '')))}</div>
<div class="card"><small>Memória</small><br>{fmt_bytes(hw.get('ram_total', 0))} ·
{hw.get('ram_modules') or '?'} módulo(s) · {hw.get('ram_speed') or '?'} MT/s</div>
<div class="card"><small>Sistema</small><br>{e(hw.get('os', ''))}</div></div>
<h2>Uso durante a análise</h2><div class="grid">
<div class="card">CPU: {fmt(s.get('cpu'))}</div><div class="card">GPU: {fmt(s.get('gpu'))}</div>
<div class="card">RAM: {fmt(s.get('ram'))}</div><div class="card">Disco: {fmt(s.get('disk'))}</div>
<div class="card">Temp. CPU: {fmt(s.get('cpu_temp'), ' °C')}</div></div>
<h2>Recomendações</h2><table>{rows}</table>
<h2>Programas que mais usam memória</h2><table><tr><th>Processo</th><th>CPU</th><th>RAM</th></tr>{procs}</table>
</body></html>"""
    path = REPORT_DIR / f"diagnostico_{time.strftime('%Y%m%d_%H%M%S')}.html"
    path.write_text(doc, encoding="utf-8")
    return str(path)
