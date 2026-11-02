"""Serviços do Windows: catálogo de serviços otimizáveis, parada temporária e tipo de inicialização.

Regras de segurança:
- Windows Defender, Firewall, Windows Update e serviços críticos estão na lista PROTECTED e nunca
  são parados nem alterados.
- 'Parar durante a sessão' é temporário: o serviço volta a rodar ao desativar o Turbo/Modo Gamer,
  ao restaurar ou no próximo reinício.
- 'Definir como Manual' guarda o tipo original e é revertível.
"""
from __future__ import annotations

import psutil

from ..config import IS_WINDOWS
from ..utils import log, run
from . import registry as reg
from .journal import Journal

PROTECTED = {
    "windefend", "wdnissvc", "sense", "mdcoresvc", "securityhealthservice", "wscsvc", "mpssvc", "bfe",
    "wuauserv", "usosvc", "waasmedicsvc", "bits", "cryptsvc", "trustedinstaller", "eventlog", "rpcss",
    "dcomlaunch", "rpceptmapper", "dhcp", "dnscache", "nsi", "lanmanworkstation", "audiosrv",
    "audioendpointbuilder", "themes", "profsvc", "schedule", "samss", "lsm", "power", "plugplay",
    "winmgmt", "netprofm", "nlasvc", "wlansvc", "eaphost", "bthserv", "gpsvc", "coremessagingregistrar",
    "brokerinfrastructure", "systemeventsbroker", "userManager".lower(), "staterepository", "appxsvc",
    "clipsvc", "tokenbroker", "keyiso", "vaultsvc", "netlogon", "mpsdrv", "textinputmanagementservice",
    "storsvc", "defragsvc", "vds", "smphost", "dosvc", "installservice", "wlidsvc", "licensemanager",
    "xboxgipsvc", "xblauthmanager", "gamingservices", "gamingservicesnet", "bthavctpsvc", "btagservice",
    "nvdisplay.containerlocalsystem", "amd external events utility", "fontcache", "sysmain_never",
}

# id: (nome amigável, descrição, recomendação) | recomendação: "temp" = parar só durante a sessão,
# "manual" = pode ser definido como Manual (inicia sob demanda), "info" = apenas informativo.
CATALOG = {
    "DiagTrack": ("Telemetria (Experiências do Usuário Conectado)",
                  "Coleta e envia dados de diagnóstico. Definir como Manual não afeta o uso do PC.", "manual"),
    "dmwappushservice": ("Roteamento de mensagens WAP Push",
                         "Auxiliar da telemetria. Pode ficar Manual com segurança.", "manual"),
    "WSearch": ("Windows Search (indexação)",
                "Indexa arquivos continuamente. Parar durante jogos reduz uso de disco e CPU; a busca "
                "continua funcionando (mais lenta) e a indexação volta depois.", "temp"),
    "SysMain": ("SysMain (Superfetch)",
                "Pré-carrega apps na RAM. Em HDD com pouca RAM pode causar disco a 100%; em SSD costuma "
                "ajudar, então só pare durante jogos se notar uso de disco alto.", "temp"),
    "MapsBroker": ("Gerenciador de Mapas Baixados", "Só usado pelo app Mapas.", "manual"),
    "Fax": ("Fax", "Raramente usado.", "manual"),
    "RetailDemo": ("Serviço de Demonstração de Varejo", "Modo demonstração de loja. Inútil em PCs pessoais.",
                   "manual"),
    "WpcMonSvc": ("Controle dos Pais", "Necessário só se usa Microsoft Family.", "manual"),
    "PhoneSvc": ("Serviço de Telefonia", "Usado para chamadas via celular vinculado.", "manual"),
    "TrkWks": ("Cliente de Rastreamento de Link Distribuído", "Rastreia atalhos em redes corporativas.", "manual"),
    "Spooler": ("Spooler de Impressão", "Necessário para imprimir. Pare só durante jogos se não for imprimir.",
                "temp"),
    "edgeupdate": ("Atualizador do Microsoft Edge", "O Edge continua se atualizando ao ser aberto.", "manual"),
    "edgeupdatem": ("Atualizador do Microsoft Edge (m)", "O Edge continua se atualizando.", "manual"),
    "gupdate": ("Google Update", "O Chrome continua se atualizando ao ser aberto.", "manual"),
    "gupdatem": ("Google Update (m)", "O Chrome continua se atualizando.", "manual"),
    "AdobeARMservice": ("Atualizador Adobe Acrobat", "Atualizações serão verificadas ao abrir o Acrobat.",
                        "manual"),
    "WerSvc": ("Relatório de Erros do Windows", "Envia relatórios de falhas. Pode parar durante jogos.", "temp"),
    "DPS": ("Serviço de Política de Diagnóstico", "Diagnósticos automáticos. Pode parar durante jogos.", "temp"),
    "PcaSvc": ("Assistente de Compatibilidade de Programas", "Monitora apps antigos para sugerir modos de "
               "compatibilidade.", "manual"),
    "lfsvc": ("Geolocalização", "Fornece localização para apps. Manual: inicia quando um app pedir.", "manual"),
    "SEMgrSvc": ("Pagamentos e NFC", "Pagamentos por aproximação em notebooks com NFC.", "manual"),
    "wisvc": ("Windows Insider", "Só necessário no programa Insider.", "manual"),
    "WMPNetworkSvc": ("Compartilhamento de rede do Windows Media Player", "Streaming do WMP legado.", "manual"),
    "RemoteRegistry": ("Registro Remoto", "Permite editar o registro pela rede (risco de segurança).", "manual"),
    "PrintNotify": ("Notificações de Impressora", "Extensões de driver de impressora.", "manual"),
    "stisvc": ("Aquisição de Imagens do Windows (WIA)", "Scanners e importação de câmeras. Manual: inicia "
               "quando usar o scanner.", "manual"),
    "diagnosticshub.standardcollector.service": ("Coletor do Hub de Diagnóstico", "Coleta para ferramentas "
                                                 "de desenvolvedor.", "manual"),
    "WdiServiceHost": ("Host do Serviço de Diagnóstico", "Diagnósticos automáticos.", "manual"),
    "WdiSystemHost": ("Host do Sistema de Diagnóstico", "Diagnósticos automáticos.", "manual"),
    "InventorySvc": ("Inventário e Avaliação de Compatibilidade", "Coleta inventário de apps para telemetria "
                     "(Windows 11 23H2+); conhecido por picos de CPU.", "manual"),
    "whesvc": ("Integridade e Experiências Otimizadas", "Coleta dados de 'saúde' do Windows.", "manual"),
    "NcdAutoSetup": ("Configuração Automática de Dispositivos de Rede", "Instala sozinho impressoras/TVs da rede.",
                     "manual"),
    "AJRouter": ("Roteador AllJoyn", "Protocolo de IoT sem uso em PCs de jogos.", "manual"),
    "SharedRealitySvc": ("Dados Espaciais", "Realidade mista.", "manual"),
    "MixedRealityOpenXRSvc": ("Realidade Misturada OpenXR", "Óculos de realidade mista.", "manual"),
    "NvContainerLocalSystem": ("Contêiner NVIDIA (overlay/telemetria)", "Necessário só para o overlay, gravação e "
                               "atualizações automáticas do NVIDIA App. O driver e o painel continuam.", "manual"),
    "ESRV_SVC_QUEENCREEK": ("Intel System Usage Report", "Telemetria da Intel.", "manual"),
    "brave": ("Atualizador do Brave", "O Brave continua se atualizando ao ser aberto.", "manual"),
    "OneDrive Updater Service": ("Atualizador do OneDrive", "O OneDrive se atualiza ao iniciar.", "manual"),
    "iphlpsvc": ("Auxiliar IP (IPv6 de transição)", "Túneis Teredo/6to4. Em raros casos o chat de grupo do "
                 "Xbox usa Teredo.", "manual"),
}

# Perfis: serviço -> (conservador, avançado, extremo). None = não altera, "demand" = Manual, "disabled".
# Todos revertíveis: o tipo de inicialização original é salvo no backup.
PROFILES = {
    "DiagTrack": ("demand", "disabled", "disabled"),
    "dmwappushservice": ("demand", "disabled", "disabled"),
    "MapsBroker": ("demand", "disabled", "disabled"),
    "RetailDemo": ("demand", "disabled", "disabled"),
    "Fax": ("demand", "demand", "disabled"),
    "edgeupdate": ("demand", "demand", "demand"),
    "edgeupdatem": ("demand", "demand", "demand"),
    "gupdate": ("demand", "demand", "demand"),
    "gupdatem": ("demand", "demand", "demand"),
    "AdobeARMservice": ("demand", "demand", "demand"),
    "RemoteRegistry": ("disabled", "disabled", "disabled"),
    "wisvc": ("demand", "demand", "disabled"),
    "WMPNetworkSvc": ("demand", "disabled", "disabled"),
    "diagnosticshub.standardcollector.service": ("demand", "demand", "disabled"),
    "PcaSvc": (None, "demand", "demand"),
    "TrkWks": (None, "demand", "demand"),
    "lfsvc": (None, "demand", "demand"),
    "SEMgrSvc": (None, "demand", "demand"),
    "WerSvc": (None, "demand", "disabled"),
    "SysMain": (None, "demand", "disabled"),
    "PhoneSvc": (None, "demand", "demand"),
    "WpcMonSvc": (None, "demand", "demand"),
    "WSearch": (None, None, "disabled"),
    "Spooler": (None, None, "demand"),
    "PrintNotify": (None, None, "demand"),
    "stisvc": (None, None, "demand"),
    "WdiServiceHost": (None, None, "demand"),
    "WdiSystemHost": (None, None, "demand"),
    "iphlpsvc": (None, None, "demand"),
    "DPS": (None, None, "demand"),
    # ---- etapa 2
    "InventorySvc": ("demand", "demand", "demand"),
    "whesvc": (None, "demand", "demand"),
    "NcdAutoSetup": ("demand", "demand", "demand"),
    "AJRouter": ("demand", "demand", "disabled"),
    "SharedRealitySvc": ("demand", "demand", "demand"),
    "MixedRealityOpenXRSvc": ("demand", "demand", "demand"),
    "NvContainerLocalSystem": (None, "demand", "demand"),
    "ESRV_SVC_QUEENCREEK": ("demand", "demand", "demand"),
    "brave": ("demand", "demand", "demand"),
    "OneDrive Updater Service": (None, "demand", "demand"),
}
PROFILE_INDEX = {"conservador": 0, "avancado": 1, "extremo": 2}
PROFILE_NOTES = {
    "conservador": "Só telemetria, atualizadores de terceiros e serviços sem uso doméstico. Zero impacto perceptível.",
    "avancado": "Inclui SysMain, compatibilidade e diagnóstico em Manual. Recomendado para PCs de jogos com SSD.",
    "extremo": "Desativa a indexação de busca (busca do Iniciar mais lenta, sem busca no Outlook) e coloca "
               "impressão/scanner em Manual (a impressora para de funcionar até reverter).",
}
_RANK = {"boot": 0, "system": 0, "auto": 1, "delayed-auto": 2, "demand": 3, "disabled": 4}

_START_MAP = {"automatic": "auto", "manual": "demand", "disabled": "disabled"}
_LABEL = {"auto": "Automático", "delayed-auto": "Automático (atraso)", "demand": "Manual",
          "disabled": "Desativado", "boot": "Boot", "system": "Sistema"}


def _start_type(name: str) -> str | None:
    path = rf"SYSTEM\CurrentControlSet\Services\{name}"
    ok, _t, start = reg.read_value("HKLM", path, "Start")
    if not ok:
        return None
    if start == 2:
        _ok, _t, delayed = reg.read_value("HKLM", path, "DelayedAutostart")
        return "delayed-auto" if delayed == 1 else "auto"
    return {0: "boot", 1: "system", 3: "demand", 4: "disabled"}.get(start, "demand")


def get_service(name: str) -> dict | None:
    if not IS_WINDOWS:
        return None
    try:
        s = psutil.win_service_get(name)
        info = s.as_dict()
    except Exception:
        return None
    start = _start_type(name) or _START_MAP.get(info.get("start_type"), "demand")
    return {"name": info["name"], "display": info.get("display_name", name), "status": info.get("status"),
            "start": start, "start_label": _LABEL.get(start, start), "pid": info.get("pid")}


def catalog_status() -> list[dict]:
    out = []
    for name, (label, desc, rec) in CATALOG.items():
        s = get_service(name)
        if not s:
            continue
        s.update({"label": label, "desc": desc, "rec": rec})
        out.append(s)
    return out


def stop_temporarily(name: str, journal: Journal, gid: str) -> tuple[bool, str]:
    if name.lower() in PROTECTED:
        return False, f"{name} é protegido e não será parado."
    s = get_service(name)
    if not s or s["status"] != "running":
        return False, f"{name} não está em execução."
    r = run(["sc.exe", "stop", name], timeout=30)
    if r.returncode != 0 and "1062" not in r.stdout:
        return False, f"Não foi possível parar {name}: {r.stdout.strip()[:120]}"
    journal.group(gid, "Sessão de otimização", "sessao")
    journal.add_action(gid, {"kind": "service_running", "name": name, "desc": f"Reiniciar serviço {name}"})
    log.info("Serviço %s parado temporariamente (%s)", name, gid)
    return True, f"{CATALOG.get(name, (name,))[0]} parado durante a sessão."


def set_manual(name: str, journal: Journal) -> tuple[bool, str]:
    if name.lower() in PROTECTED:
        return False, f"{name} é protegido."
    s = get_service(name)
    if not s:
        return False, f"Serviço {name} não encontrado."
    if s["start"] in ("demand", "disabled"):
        return True, f"{name} já está como {s['start_label']}."
    gid = f"service:{name}"
    r = run(["sc.exe", "config", name, "start=", "demand"])
    if r.returncode != 0:
        return False, f"Falha: {r.stdout.strip()[:150]}"
    journal.group(gid, f"Serviço {CATALOG.get(name, (name,))[0]} → Manual", "servicos")
    journal.add_action(gid, {"kind": "service_start", "name": name, "start": s["start"],
                             "desc": f"Restaurar inicialização de {name} ({s['start_label']})"})
    return True, f"{name} definido como Manual (revertível)."


def set_start(name: str, start: str, journal: Journal) -> tuple[bool, str]:
    """Altera o tipo de inicialização (demand/disabled), guardando o original. Nunca torna mais 'ativo'."""
    if name.lower() in PROTECTED or start not in ("demand", "disabled"):
        return False, f"{name} é protegido."
    s = get_service(name)
    if not s:
        return False, f"Serviço {name} não existe nesta versão do Windows."
    if _RANK.get(s["start"], 3) >= _RANK[start]:
        return True, f"{s['display']} já está como {s['start_label']}."
    gid = f"service:{name}"
    r = run(["sc.exe", "config", name, "start=", start])
    if r.returncode != 0:
        return False, f"Falha em {name}: {r.stdout.strip()[:150]}"
    if not journal.has_group(gid):  # guarda só o tipo ORIGINAL (primeira alteração)
        journal.group(gid, f"Serviço {CATALOG.get(name, (name,))[0]} → {_LABEL[start]}", "servicos")
        journal.add_action(gid, {"kind": "service_start", "name": name, "start": s["start"],
                                 "desc": f"Restaurar inicialização de {name} ({s['start_label']})"})
    if start == "disabled" and s["status"] == "running":
        run(["sc.exe", "stop", name], timeout=30)
        journal.add_action(gid, {"kind": "service_running", "name": name, "desc": f"Reiniciar {name}"})
    return True, f"{CATALOG.get(name, (name,))[0]} → {_LABEL[start]}"


def detailed_status() -> list[dict]:
    """Catálogo com consumo de RAM do processo hospedeiro, compartilhamento e alvo de cada perfil."""
    pid_count: dict[int, int] = {}
    if IS_WINDOWS:
        for svc in psutil.win_service_iter():
            try:
                pid = svc.pid()
            except Exception:
                continue
            if pid:
                pid_count[pid] = pid_count.get(pid, 0) + 1
    out = []
    for s in catalog_status():
        mem = 0
        if s.get("pid"):
            try:
                mem = psutil.Process(s["pid"]).memory_info().rss
            except psutil.Error:
                pass
        s["mem"] = mem
        s["shared"] = pid_count.get(s.get("pid") or -1, 0) > 1
        s["profiles"] = PROFILES.get(s["name"], (None, None, None))
        out.append(s)
    return out


def profile_plan(profile: str) -> list[dict]:
    """Lista de mudanças do perfil para os serviços existentes nesta máquina."""
    idx = PROFILE_INDEX[profile]
    out = []
    for name, targets in PROFILES.items():
        target = targets[idx]
        if not target:
            continue
        s = get_service(name)
        if not s or _RANK.get(s["start"], 3) >= _RANK[target]:
            continue
        label, desc, _rec = CATALOG.get(name, (name, "", ""))
        out.append({"name": name, "label": label, "desc": desc, "current": s["start_label"],
                    "target": target, "target_label": _LABEL[target], "status": s["status"]})
    return out


def restore_start(name: str, journal: Journal) -> list[str]:
    return journal.revert_group(f"service:{name}")


def session_candidates() -> list[dict]:
    """Serviços que podem ser parados durante uma sessão de jogo/turbo."""
    return [s for s in catalog_status() if s["rec"] in ("temp", "manual") and s["status"] == "running"]
