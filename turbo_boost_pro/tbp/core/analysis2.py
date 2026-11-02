"""Etapa 2: análise técnica de CPU, RAM, GPU, latência, disco e processos.

Cada analisador devolve {"facts": [(rótulo, valor)], "findings": [Finding]}. As recomendações só aparecem
quando a medição indica um problema real; nada é aplicado automaticamente.
"""
from __future__ import annotations

import os
import re
import statistics
import time

import psutil

from ..config import IS_WINDOWS, settings
from ..utils import fmt_bytes, powershell_json, run
from . import power, registry as reg, winapi
from .diagnostics import Finding
from .monitor import _cpu_name


def _pdh_sample(paths: list[str], seconds: float = 3.0) -> dict[str, float | None]:
    """Média de contadores de desempenho do Windows (PDH)."""
    out = {p: None for p in paths}
    if not IS_WINDOWS:
        return out
    try:
        import win32pdh
        q = win32pdh.OpenQuery()
        hs = {}
        for p in paths:
            try:
                hs[p] = win32pdh.AddEnglishCounter(q, p)
            except Exception:
                pass
        win32pdh.CollectQueryData(q)
        acc = {p: [] for p in hs}
        n = max(1, int(seconds))
        for _ in range(n):
            time.sleep(1)
            win32pdh.CollectQueryData(q)
            for p, h in hs.items():
                try:
                    acc[p].append(win32pdh.GetFormattedCounterValue(h, win32pdh.PDH_FMT_DOUBLE)[1])
                except Exception:
                    pass
        win32pdh.CloseQuery(q)
        for p, vals in acc.items():
            out[p] = statistics.mean(vals) if vals else None
    except Exception:
        pass
    return out


# ============================================================================ CPU
def cpu_report() -> dict:
    name = _cpu_name()
    facts, found = [], []
    F = found.append
    cores, threads = psutil.cpu_count(False), psutil.cpu_count()
    facts += [("Processador", name), ("Núcleos / threads", f"{cores} / {threads}")]
    hybrid = "Intel" in name and re.search(r"(1[2-9]|2\d)\d{2,3}|Ultra", name) is not None
    if hybrid:
        facts.append(("Arquitetura", "Híbrida (núcleos P + E): o Windows 11 + Thread Director escolhem os núcleos"))
    if power.parking_sensitive_cpu():
        facts.append(("Arquitetura", "Ryzen X3D com 2 CCDs: estacionamento de núcleos deve ficar PERMITIDO"))
    plan = power.active_plan()
    facts.append(("Plano de energia ativo", plan["name"] if plan else "?"))
    st = power.cpu_settings() if IS_WINDOWS else {}
    for alias, label in power.SETTING_LABELS.items():
        v = st.get(alias)
        if v:
            facts.append((label, f"tomada {v[0]} · bateria {v[1]}"))
    perf = _pdh_sample([r"\Processor Information(_Total)\% Processor Performance",
                        r"\Processor Information(_Total)\% Performance Limit",
                        r"\Processor Information(_Total)\Processor Frequency"], 3)
    pp = perf[r"\Processor Information(_Total)\% Processor Performance"]
    lim = perf[r"\Processor Information(_Total)\% Performance Limit"]
    freq = perf[r"\Processor Information(_Total)\Processor Frequency"]
    if freq:
        facts.append(("Frequência atual", f"{freq / 1000:.2f} GHz ({pp:.0f}% do clock base)" if pp else
                      f"{freq / 1000:.2f} GHz"))
    if lim is not None:
        facts.append(("Limite de desempenho", f"{lim:.0f}% (100% = sem limitação)"))
        if lim < 95:
            F(Finding("alto", "CPU", f"Processador limitado a {lim:.0f}% do desempenho",
                      "O firmware/Windows está restringindo a CPU (limite de energia, temperatura ou economia de "
                      "bateria). Verifique o carregador, a temperatura e o modo de energia do fabricante "
                      "(Armoury Crate, Lenovo Vantage, MSI Center…).", "cpu:competitivo", "Perfil competitivo"))
    bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    if bat and not bat.power_plugged:
        F(Finding("alto", "CPU", "Notebook na bateria", "Na bateria o processador e a GPU operam com limites de "
                  "potência muito menores. Para jogar CS2 conecte o carregador."))
    if st.get("PROCTHROTTLEMAX") and st["PROCTHROTTLEMAX"][0] < 100:
        F(Finding("alto", "CPU", f"Estado máximo do processador em {st['PROCTHROTTLEMAX'][0]}%",
                  "O plano de energia impede a CPU de atingir o clock máximo.", "cpu:competitivo", "Corrigir"))
    if st.get("PERFBOOSTMODE") and st["PERFBOOSTMODE"][0] == 0:
        F(Finding("critico", "CPU", "Turbo Boost/Precision Boost desativado no plano",
                  "A CPU nunca passa do clock base: perda de 20-40% em jogos dependentes de CPU como o CS2.",
                  "cpu:competitivo", "Reativar turbo"))
    if power.parking_sensitive_cpu() and st.get("CPMINCORES") and st["CPMINCORES"][0] >= 100:
        F(Finding("alto", "CPU", "Estacionamento de núcleos desativado em um Ryzen X3D de 2 CCDs",
                  "O driver da AMD precisa estacionar o CCD sem cache 3D para o jogo ficar no CCD com V-Cache. "
                  "Com todos os núcleos ativos o CS2 pode perder 5-15% de FPS.", "parking:allow",
                  "Permitir estacionamento"))
    return {"facts": facts, "findings": found}


# ============================================================================ RAM
def ram_report() -> dict:
    facts, found = [], []
    F = found.append
    vm = psutil.virtual_memory()
    facts.append(("RAM total / em uso", f"{fmt_bytes(vm.total)} / {fmt_bytes(vm.total - vm.available)} "
                                        f"({vm.percent:.0f}%)"))
    if not IS_WINDOWS:
        return {"facts": facts, "findings": found}
    mods = powershell_json("Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,Speed,"
                           "ConfiguredClockSpeed,SMBIOSMemoryType,DeviceLocator")
    if mods:
        rated = max((m.get("Speed") or 0) for m in mods)
        conf = max((m.get("ConfiguredClockSpeed") or 0) for m in mods)
        mtype = {26: "DDR4", 34: "DDR5", 24: "DDR3"}.get(mods[0].get("SMBIOSMemoryType"), "")
        facts.append(("Módulos", f"{len(mods)} × {fmt_bytes(mods[0].get('Capacity') or 0)} {mtype}"))
        facts.append(("Velocidade configurada / nominal", f"{conf} / {rated} MT/s"))
        jedec_default = (mtype == "DDR4" and conf <= 2666) or (mtype == "DDR5" and conf <= 4800)
        if jedec_default and rated <= conf:
            F(Finding("alto", "RAM", f"Memória na velocidade padrão ({conf} MT/s)",
                      "Se os seus pentes suportam mais (ex.: DDR4-3200/3600, DDR5-6000), o perfil XMP/EXPO está "
                      "desligado na BIOS. Ativá-lo costuma dar 5-15% de FPS e 1% low no CS2, que depende muito da "
                      "latência de memória. Ajuste manual na BIOS (o app não altera BIOS)."))
        elif conf and rated and conf < rated:
            F(Finding("alto", "RAM", f"RAM rodando abaixo do nominal ({conf} de {rated} MT/s)",
                      "Ative o perfil XMP/EXPO na BIOS para usar a velocidade completa dos pentes."))
        if len(mods) == 1:
            F(Finding("alto", "RAM", "Um único pente de memória (single channel)",
                      "Metade da largura de banda. Em CS2 a diferença de 1 para 2 pentes chega a 15-30% de FPS em "
                      "CPUs rápidas. Recomendação: 2 pentes iguais."))
    pf = powershell_json("$c = Get-CimInstance Win32_ComputerSystem; $u = Get-CimInstance Win32_PageFileUsage; "
                         "[pscustomobject]@{Auto=$c.AutomaticManagedPagefile; Files=@($u | ForEach-Object "
                         "{ \"$($_.Name) ($($_.AllocatedBaseSize) MB)\" })}")
    if pf:
        auto, files = pf[0].get("Auto"), pf[0].get("Files") or []
        facts.append(("Arquivo de paginação", ("Gerenciado pelo Windows · " if auto else "Manual · ") +
                      (", ".join(files) or "NENHUM")))
        if not files:
            F(Finding("alto", "RAM", "Arquivo de paginação desativado",
                      "Sem paginação, jogos podem fechar por falta de memória de commit e o Windows não consegue "
                      "gravar despejos de falha. Desativar NÃO aumenta FPS.", "pagefile:auto",
                      "Gerenciado pelo Windows"))
        elif not auto:
            F(Finding("medio", "RAM", "Arquivo de paginação com tamanho manual",
                      "Tamanhos fixos pequenos podem causar erros de memória insuficiente em jogos. O tamanho "
                      "gerenciado pelo Windows é o recomendado pela Microsoft.", "pagefile:auto",
                      "Gerenciado pelo Windows"))
    mm = powershell_json("Get-MMAgent | Select-Object MemoryCompression,PageCombining")
    if mm:
        facts.append(("Compressão de memória", "ativa" if mm[0].get("MemoryCompression") else "desativada"))
        if not mm[0].get("MemoryCompression"):
            F(Finding("medio", "RAM", "Compressão de memória desativada",
                      "A compressão evita gravar no disco quando a RAM enche (mais rápido que paginar). Reative com "
                      "'Enable-MMAgent -MemoryCompression' (o TURBO BOOST PRO não desativa este recurso)."))
    c = _pdh_sample([r"\Memory\% Committed Bytes In Use", r"\Memory\Pages Input/sec"], 3)
    commit, hard = c[r"\Memory\% Committed Bytes In Use"], c[r"\Memory\Pages Input/sec"]
    if commit is not None:
        facts.append(("Memória comprometida (commit)", f"{commit:.0f}% do limite"))
    if hard is not None:
        facts.append(("Leituras de página do disco", f"{hard:.0f} páginas/s"))
        if hard > 300:
            F(Finding("alto", "RAM", "Paginação intensa agora", "O Windows está lendo memória do disco: RAM "
                      "insuficiente para o que está aberto. Feche programas pesados antes de jogar."))
    from .processes import sampler
    procs = sorted(sampler.sample(), key=lambda p: p["mem"], reverse=True)
    heavy = [p for p in procs[:6] if not p["protected"] and p["mem"] > 500 * 2 ** 20]
    if heavy:
        facts.append(("Processos que mais usam RAM", ", ".join(f"{p['name']} {fmt_bytes(p['mem'])}" for p in heavy)))
    F(Finding("ok", "RAM", "Sem limpador agressivo de memória",
              "A partir desta versão o TURBO BOOST PRO não esvazia o cache em espera durante jogos (isso força "
              "releituras do disco e causa travadas). A compactação só ocorre com RAM acima de 85%."))
    return {"facts": facts, "findings": found}


# ============================================================================ GPU
VENDORS = {"10DE": "NVIDIA", "1002": "AMD", "8086": "Intel"}
VENDOR_TIPS = {
    "NVIDIA": [
        "Painel NVIDIA › Gerenciar configurações 3D › Programa: cs2.exe",
        "Modo de baixa latência: Desligado (o NVIDIA Reflex do jogo substitui) · No CS2: Reflex 'Ativado + Boost'",
        "Modo de gerenciamento de energia: Preferir desempenho máximo (só para cs2.exe)",
        "Tamanho do cache de shaders: Padrão do driver ou 10 GB (evita recompilar shaders)",
        "Sincronização vertical: Desligada (com G-Sync: Ligada no painel + limite de FPS 3 abaixo do monitor)",
        "Configurações de vídeo › Ajustar cor: 'Com as configurações NVIDIA' · Faixa dinâmica: Completa",
        "Não use o overlay/gravação do NVIDIA App se não precisar (custa 1-3% de FPS)",
    ],
    "AMD": [
        "Adrenalin › Jogos › Counter-Strike 2",
        "Radeon Anti-Lag: no CS2 use o Anti-Lag 2 do próprio jogo (seguro para VAC); no driver deixe o padrão",
        "Radeon Chill: Desligado · Radeon Boost: Desligado (reduz a resolução em movimento)",
        "Enhanced Sync: Desligado · Aguardar atualização vertical: Sempre desligado",
        "Gráficos › Perfil: Personalizado, Tessellation: Configurações do aplicativo",
        "Desative Instant Replay/gravação do Adrenalin se não usa",
    ],
    "Intel": [
        "Intel Graphics Software › Jogos › CS2: Sincronização vertical desligada",
        "Atualize sempre o driver Arc/Iris: melhorias de DX11 recentes dão ganhos grandes no CS2",
        "Em notebooks com iGPU + GPU dedicada, garanta que o CS2 usa a dedicada (perfil de GPU por jogo)",
    ],
}


def gpu_list() -> list[dict]:
    rows = powershell_json("Get-CimInstance Win32_VideoController | Select-Object Name,PNPDeviceID,DriverVersion,"
                           "@{n='DriverDate';e={$_.DriverDate.ToString('yyyy-MM-dd')}},CurrentRefreshRate,"
                           "MaxRefreshRate,CurrentHorizontalResolution,CurrentVerticalResolution,AdapterRAM")
    out = []
    for r in rows:
        m = re.search(r"VEN_([0-9A-F]{4})", str(r.get("PNPDeviceID") or "").upper())
        vendor = VENDORS.get(m.group(1) if m else "", "Outro")
        out.append({"name": r.get("Name"), "vendor": vendor, "driver": r.get("DriverVersion"),
                    "driver_date": r.get("DriverDate"), "hz": r.get("CurrentRefreshRate"),
                    "max_hz": r.get("MaxRefreshRate"), "res": f"{r.get('CurrentHorizontalResolution')}x"
                                                         f"{r.get('CurrentVerticalResolution')}"})
    return out


def gpu_report() -> dict:
    facts, found = [], []
    F = found.append
    gpus = gpu_list() if IS_WINDOWS else []
    dedicated = [g for g in gpus if g["vendor"] in ("NVIDIA", "AMD")] or gpus
    for g in gpus:
        facts.append((f"GPU ({g['vendor']})", f"{g['name']} · driver {g['driver']} ({g['driver_date']})"))
        if g["hz"]:
            facts.append(("Tela", f"{g['res']} @ {g['hz']} Hz (máximo informado {g['max_hz']} Hz)"))
    for g in dedicated:
        try:
            age = (time.time() - time.mktime(time.strptime(g["driver_date"], "%Y-%m-%d"))) / 86400
        except (TypeError, ValueError):
            age = 0
        if age > 240:
            F(Finding("medio", "GPU", f"Driver de vídeo antigo ({int(age // 30)} meses)",
                      f"Drivers novos trazem correções e ganhos específicos para CS2. Atualize pelo site da "
                      f"{g['vendor']}."))
        if g["hz"] and g["max_hz"] and g["hz"] < g["max_hz"] and g["hz"] <= 75 and g["max_hz"] >= 100:
            F(Finding("critico", "GPU", f"Monitor rodando a {g['hz']} Hz (suporta {g['max_hz']} Hz)",
                      "Você está vendo só parte dos quadros que a GPU gera. Configure a taxa de atualização "
                      "máxima em Configurações › Tela › Tela avançada. É o ganho de fluidez mais perceptível "
                      "possível em CS2.", "open:ms-settings:display-advanced", "Abrir configurações de tela"))
    ok, _t, hags = reg.read_value("HKLM", r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode")
    facts.append(("Agendamento de GPU por hardware (HAGS)", "ativado" if ok and hags == 2 else "desativado/padrão"))
    F(Finding("info", "GPU", "HAGS: o efeito varia por GPU e driver",
              "Use 'Testes A/B › HAGS' para medir com o seu PC: benchmark, alternar, reiniciar e medir de novo."))
    vendors = {g["vendor"] for g in dedicated}
    return {"facts": facts, "findings": found, "gpus": gpus,
            "tips": {v: VENDOR_TIPS[v] for v in vendors if v in VENDOR_TIPS}}


# ============================================================================ LATÊNCIA
def nic_properties() -> list[dict]:
    rows = powershell_json("Get-NetAdapter -Physical | Where-Object Status -eq 'Up' | ForEach-Object { $n=$_.Name; "
                           "Get-NetAdapterAdvancedProperty -Name $n -ErrorAction SilentlyContinue | Where-Object "
                           "{ $_.RegistryKeyword -in @('*EEE','EEELinkAdvertisement','*InterruptModeration',"
                           "'GreenEthernet','EnableGreenEthernet','*FlowControl','AdvancedEEE','PowerSavingMode') } | "
                           "Select-Object @{n='Adapter';e={$n}},DisplayName,RegistryKeyword,"
                           "@{n='Value';e={[string]($_.RegistryValue | Select-Object -First 1)}},DisplayValue }")
    return [{"adapter": r.get("Adapter"), "name": r.get("DisplayName"), "keyword": r.get("RegistryKeyword"),
             "value": r.get("Value"), "display": r.get("DisplayValue")} for r in rows]


def latency_report() -> dict:
    facts, found = [], []
    F = found.append
    tr = winapi.query_timer_resolution()
    ok, _t, gt = reg.read_value("HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\kernel",
                                "GlobalTimerResolutionRequests")
    if tr:
        facts.append(("Timer do sistema", f"atual {tr['current']:.3f} ms (mín. {tr['finest']:.1f} · padrão "
                                          f"{tr['coarsest']:.1f})"))
    facts.append(("Pedidos globais de timer", "ativado" if ok and gt == 1 else "padrão do Windows 11 (por processo)"))
    ab = settings.get("timer_ab_result")
    if ab:
        facts.append(("Teste A/B do timer", f"{'recomendado' if ab['recommend'] else 'sem benefício'} "
                                            f"(1% low {ab['gain_1low_pct']:+.1f}%)"))
    else:
        F(Finding("info", "Latência", "Timer de 0,5 ms: ainda não testado no seu PC",
                  "O CS2 já pede o timer de 1 ms sozinho. Forçar 0,5 ms só ajuda em alguns PCs e aumenta o consumo. "
                  "Rode 'Testes A/B › Timer' com o jogo aberto para decidir com números."))
    dpc = _pdh_sample([r"\Processor(_Total)\% DPC Time", r"\Processor(_Total)\% Interrupt Time"], 3)
    d, i = dpc[r"\Processor(_Total)\% DPC Time"], dpc[r"\Processor(_Total)\% Interrupt Time"]
    if d is not None:
        facts.append(("Tempo em DPC / interrupções", f"{d:.2f}% / {(i or 0):.2f}%"))
        if d + (i or 0) > 3:
            F(Finding("alto", "Latência", f"Tempo alto em drivers (DPC+ISR {d + (i or 0):.1f}%)",
                      "Algum driver (rede Wi-Fi, áudio, RGB, USB) está ocupando a CPU em alta prioridade, causando "
                      "micro-travadas e atraso de entrada. Atualize drivers de chipset/rede/áudio e feche softwares "
                      "de periféricos. O LatencyMon identifica o driver exato."))
    ok, _t, ms = reg.read_value("HKCU", r"Control Panel\Mouse", "MouseSpeed")
    facts.append(("Aceleração do mouse", "desativada" if ok and str(ms) == "0" else "ATIVADA"))
    if not (ok and str(ms) == "0"):
        F(Finding("medio", "Latência", "Aceleração do mouse ativada",
                  "A mira fica inconsistente (o CS2 usa raw input, mas o menu e o desktop não).", "tweak:mouse_raw",
                  "Desativar"))
    stats = ping_stats()
    if stats:
        facts.append(("Rede (1.1.1.1, 20 pings)", f"média {stats['avg']:.0f} ms · jitter {stats['jitter']:.1f} ms · "
                                                  f"perda {stats['loss']:.0f}%"))
        if stats["loss"] > 0 or stats["jitter"] > 8:
            F(Finding("alto", "Rede", "Conexão instável (perda/jitter)",
                      "Perda de pacotes e jitter causam 'teleportes' no CS2. Prefira cabo a Wi-Fi e evite downloads "
                      "durante as partidas."))
    nics = nic_properties() if IS_WINDOWS else []
    for n in nics:
        facts.append((f"Placa {n['adapter']}", f"{n['name']}: {n['display']}"))
    eee = [n for n in nics if n["keyword"] in ("*EEE", "EEELinkAdvertisement", "AdvancedEEE", "GreenEthernet",
                                               "EnableGreenEthernet") and n["value"] not in ("0", "", None)]
    if eee:
        F(Finding("medio", "Rede", "Ethernet com economia de energia (EEE/Green Ethernet) ativa",
                  "A placa entra em baixo consumo entre pacotes; ao 'acordar' adiciona atraso e oscilações. "
                  "Desativar é seguro e reversível (a rede reconecta por 2-3 s ao aplicar).", "nic:eee",
                  "Desativar economia"))
    F(Finding("info", "Rede", "Algoritmo de Nagle não afeta o CS2",
              "O CS2 usa UDP; ajustes de TCP (Nagle/TcpAckFrequency) só ajudam jogos que usam TCP."))
    return {"facts": facts, "findings": found, "nics": nics}


def ping_stats(host: str = "1.1.1.1", count: int = 20) -> dict | None:
    if not IS_WINDOWS:
        return None
    out = run(["ping", "-n", str(count), "-w", "1000", host], timeout=60).stdout
    times = [float(x) for x in re.findall(r"[=<](\d+)\s*ms", out)]
    times = times[:count]
    if not times:
        return {"avg": 0, "jitter": 0, "loss": 100}
    jitter = statistics.mean(abs(a - b) for a, b in zip(times, times[1:])) if len(times) > 1 else 0
    return {"avg": statistics.mean(times), "jitter": jitter, "loss": (count - len(times)) / count * 100}


# ============================================================================ DISCO
def boot_events() -> dict:
    """Tempo de boot e itens que atrasaram a inicialização (log Diagnostics-Performance; requer admin)."""
    rows = powershell_json(
        "Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-Diagnostics-Performance/Operational'; "
        "Id=100,101,102,103,106,109} -MaxEvents 60 -ErrorAction SilentlyContinue | ForEach-Object { $x=[xml]$_.ToXml(); "
        "$d=@{}; $x.Event.EventData.Data | ForEach-Object { $d[$_.Name]=$_.'#text' }; [pscustomobject]@{Id=$_.Id; "
        "Time=$_.TimeCreated.ToString('yyyy-MM-dd HH:mm'); Boot=$d['BootTime']; MainPath=$d['MainPathBootTime']; "
        "Post=$d['BootPostBootTime']; Name=$d['FriendlyName']; File=$d['FileName']; Total=$d['TotalTime']; "
        "Degr=$d['DegradationTime']} }", timeout=90)
    last = next((r for r in rows if r.get("Id") == 100), None)
    slow = []
    for r in rows:
        if r.get("Id") != 100 and (r.get("Name") or r.get("File")):
            name = r.get("Name") or os.path.basename(str(r.get("File")))
            if name not in [s[0] for s in slow]:
                slow.append((name, int(r.get("Degr") or r.get("Total") or 0)))
    return {"last": last, "slow": sorted(slow, key=lambda x: -x[1])[:6]}


def disk_io_top(seconds: float = 4) -> list[tuple[str, float]]:
    first = {}
    for p in psutil.process_iter(["pid", "name"]):
        try:
            io = p.io_counters()
            first[p.pid] = (p.info["name"], io.read_bytes + io.write_bytes)
        except (psutil.Error, AttributeError):
            pass
    time.sleep(seconds)
    rates = []
    for pid, (name, b0) in first.items():
        try:
            io = psutil.Process(pid).io_counters()
            rate = (io.read_bytes + io.write_bytes - b0) / seconds
            if rate > 256 * 1024:
                rates.append((name, rate))
        except (psutil.Error, AttributeError):
            pass
    return sorted(rates, key=lambda x: -x[1])[:6]


def disk_report() -> dict:
    from . import storage
    facts, found = [], []
    F = found.append
    vols = storage.list_volumes() if IS_WINDOWS else []
    sysd = os.environ.get("SystemDrive", "C:")[0].upper()
    for v in vols:
        facts.append((f"Unidade {v['letter']}:", f"{v['kind']} · {v['bus']} · {fmt_bytes(v['free'])} livres de "
                                                 f"{fmt_bytes(v['size'])}"))
        if v["letter"] and v["letter"].upper() == sysd and v["kind"] == "HDD":
            F(Finding("critico", "Disco", "Windows em HD mecânico", "Maior gargalo possível de carregamento e "
                      "travadas por streaming de texturas. Migre para SSD."))
    trim = storage.trim_enabled() if IS_WINDOWS else None
    facts.append(("TRIM", {True: "ativado", False: "DESATIVADO", None: "?"}[trim]))
    if trim is False:
        F(Finding("alto", "Disco", "TRIM desativado", "O SSD perde desempenho de escrita com o tempo.", "trim:on",
                  "Ativar TRIM"))
    sd = powershell_json("Get-ScheduledTask -TaskPath '\\Microsoft\\Windows\\Defrag\\' -TaskName 'ScheduledDefrag' "
                         "-ErrorAction SilentlyContinue | Select-Object @{n='State';e={[string]$_.State}}")
    if sd:
        facts.append(("Otimização automática de unidades", "ativa" if sd[0].get("State") != "Disabled" else
                      "DESATIVADA"))
        if sd[0].get("State") == "Disabled":
            F(Finding("medio", "Disco", "Otimização automática de unidades desativada",
                      "Esta tarefa executa o TRIM semanal dos SSDs. Reative em 'Desfragmentar e Otimizar Unidades'."))
    if IS_WINDOWS:
        b = boot_events()
        last = b["last"]
        if last and last.get("Boot"):
            boot_s = int(last["Boot"]) / 1000
            facts.append(("Último boot", f"{boot_s:.1f} s (núcleo {int(last.get('MainPath') or 0) / 1000:.1f} s + "
                                         f"pós-boot {int(last.get('Post') or 0) / 1000:.1f} s) em {last.get('Time')}"))
            if boot_s > 60:
                F(Finding("medio", "Disco", f"Inicialização lenta ({boot_s:.0f} s)",
                          "Veja abaixo os itens que atrasaram o boot e desative os desnecessários na aba "
                          "Desempenho › Inicialização.", "page:performance", "Gerenciar"))
        if b["slow"]:
            facts.append(("Itens que atrasaram o boot", ", ".join(f"{n} (+{t / 1000:.1f} s)" for n, t in b["slow"])))
    io = disk_io_top()
    if io:
        facts.append(("Uso de disco agora", ", ".join(f"{n} {fmt_bytes(r)}/s" for n, r in io)))
    return {"facts": facts, "findings": found}


# ============================================================================ PROCESSOS EM IDLE
KNOWN_HOGS = {
    "searchindexer.exe": "Indexação da busca (serviço WSearch)", "msmpeng.exe": "Varredura do Defender (normal "
    "ocasionalmente; constante = verifique a agenda de varredura)", "tiworker.exe": "Instalação de atualizações",
    "compattelrunner.exe": "Telemetria de compatibilidade (tarefa Appraiser)", "onedrive.exe": "Sincronização OneDrive",
    "widgets.exe": "Widgets", "phoneexperiencehost.exe": "Vincular ao Celular", "nvidia share.exe": "Overlay NVIDIA",
    "nvcontainer.exe": "Contêiner NVIDIA (telemetria/overlay)", "radeonsoftware.exe": "Overlay AMD Adrenalin",
    "steamwebhelper.exe": "Navegador interno/overlay da Steam", "discord.exe": "Discord (overlay e aceleração de "
    "hardware)", "wallpaper64.exe": "Wallpaper Engine (configure para pausar em tela cheia)", "icue.exe": "Corsair "
    "iCUE (conhecido por picos de DPC)", "lghub.exe": "Logitech G HUB", "lghub_agent.exe": "Logitech G HUB",
    "armourycrate.service.exe": "Armoury Crate", "razer synapse service process.exe": "Razer Synapse",
    "signalrgb.exe": "SignalRGB", "msedge.exe": "Edge (abas em segundo plano)", "chrome.exe": "Chrome (abas)",
}


def process_audit(seconds: float = 6) -> dict:
    """CPU média por processo com o PC parado: o que rouba recursos do CS2 continuamente."""
    procs = {}
    for p in psutil.process_iter(["pid", "name"]):
        try:
            p.cpu_percent(None)
            procs[p.pid] = p
        except psutil.Error:
            pass
    time.sleep(seconds)
    ncpu = psutil.cpu_count() or 1
    usage: dict[str, float] = {}
    for pid, p in procs.items():
        try:
            n = (p.info["name"] or "").lower()
            if pid in (0, 4) or n in ("system idle process", "idle"):
                continue
            usage[n] = usage.get(n, 0) + p.cpu_percent(None) / ncpu
        except psutil.Error:
            pass
    top = sorted(usage.items(), key=lambda x: -x[1])[:12]
    rows = [{"name": n, "cpu": round(c, 2), "why": KNOWN_HOGS.get(n, "")} for n, c in top if c >= 0.3]
    found = []
    F = found.append
    total = sum(r["cpu"] for r in rows)
    if total > 5:
        F(Finding("alto", "Processos", f"{total:.0f}% de CPU usados em repouso",
                  "Com o PC parado o uso deveria ficar abaixo de 3%. Veja a lista: cada ponto percentual aqui é "
                  "tempo de CPU que o CS2 (dependente de CPU) deixa de ter."))
    for r in rows:
        if r["why"] and r["cpu"] >= 0.5:
            F(Finding("medio", "Processos", f"{r['name']}: {r['cpu']:.1f}% de CPU em repouso", r["why"]))
    return {"rows": rows, "findings": found}


# ============================================================================ TWEAKS AVALIADOS E REJEITADOS
REJECTED = [
    ("bcdedit /set useplatformclock true (forçar HPET)", "Aumenta o custo de leitura do relógio e piora o frametime "
     "na maioria dos PCs atuais. O Windows já escolhe a melhor fonte (TSC)."),
    ("bcdedit /set disabledynamictick yes", "Sem ganho mensurável em jogos; aumenta consumo e calor em repouso."),
    ("Timer de 0,5 ms permanente", "O CS2 já pede 1 ms; forçar 0,5 ms sempre custa energia. Aqui só com teste A/B."),
    ("Limpar o cache em espera (Standby List) durante jogos", "Força o jogo a reler texturas do disco: causa travadas."),
    ("DisablePagingExecutive / LargeSystemCache / IoPageLockLimit", "Valores de Windows XP; ignorados ou "
     "prejudiciais no Windows 10/11."),
    ("Desativar arquivo de paginação", "Não aumenta FPS e pode fechar jogos por falta de memória de commit."),
    ("Desativar compressão de memória", "Faz o Windows paginar no disco em vez de comprimir na RAM (mais lento)."),
    ("Prioridade 'Tempo real' para o jogo", "Pode travar entrada de mouse/teclado e áudio. Usamos 'Alta'."),
    ("Afinidade de CPU manual para o CS2", "Atrapalha o agendador (Thread Director/X3D) e reduz o 1% low."),
    ("Desativar mitigações Spectre/Meltdown", "Risco de segurança real; o ganho em jogos é pequeno."),
    ("Desativar Integridade de Memória (HVCI)", "Ganho de 3-10% em alguns jogos, mas remove proteção contra "
     "drivers maliciosos. Decisão manual do usuário."),
    ("Nagle/TcpAckFrequency para CS2", "O CS2 usa UDP; não há efeito."),
    ("Desativar MPO (OverlayTestMode)", "Corrige cintilação em alguns drivers, mas não aumenta desempenho."),
    ("Overclock/undervolt/limites de energia da GPU", "Risco de instabilidade e garantia; nunca alterados pelo app."),
    ("'MouseDataQueueSize' / 'KeyboardDataQueueSize'", "Sem evidência técnica de redução de latência."),
]
