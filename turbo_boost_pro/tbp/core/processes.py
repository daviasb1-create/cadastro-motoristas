"""Processos: monitoramento de consumo, encerramento seguro e prioridade."""
from __future__ import annotations

import os
import threading
import time

import psutil

from ..utils import log
from .journal import Journal

# Nunca encerrados nem tocados pelo otimizador.
PROTECTED = {
    "system", "system idle process", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
    "services.exe", "lsass.exe", "lsaiso.exe", "svchost.exe", "dwm.exe", "explorer.exe", "fontdrvhost.exe",
    "sihost.exe", "ctfmon.exe", "taskhostw.exe", "runtimebroker.exe", "startmenuexperiencehost.exe",
    "shellexperiencehost.exe", "searchhost.exe", "textinputhost.exe", "audiodg.exe", "conhost.exe",
    "msmpeng.exe", "nissrv.exe", "mpdefendercoreservice.exe", "securityhealthservice.exe",
    "securityhealthsystray.exe", "smartscreen.exe", "wudfhost.exe", "spoolsv.exe", "memory compression",
    "secure system", "lsm.exe", "dllhost.exe", "applicationframehost.exe", "systemsettings.exe",
    "turboboostpro.exe", "python.exe", "pythonw.exe", "trustedinstaller.exe", "tiworker.exe",
    "msiexec.exe", "nvcontainer.exe", "nvdisplay.container.exe", "atiesrxx.exe", "atieclxx.exe",
    "igfxem.exe", "rtkauduservice64.exe", "wlanext.exe", "usocoreworker.exe", "wuauclt.exe",
}

# Apps de segundo plano não essenciais que podem ser fechados com segurança durante a sessão.
BACKGROUND_APPS = {
    "onedrive.exe": "OneDrive (sincronização)",
    "ms-teams.exe": "Microsoft Teams",
    "teams.exe": "Microsoft Teams (clássico)",
    "skype.exe": "Skype",
    "phoneexperiencehost.exe": "Vincular ao Celular",
    "yourphone.exe": "Vincular ao Celular",
    "widgets.exe": "Widgets",
    "widgetservice.exe": "Serviço de Widgets",
    "gamebarpresencewriter.exe": "Game Bar (presença)",
    "cortana.exe": "Cortana",
    "dropbox.exe": "Dropbox",
    "googledrivefs.exe": "Google Drive",
    "adobearm.exe": "Atualizador Adobe",
    "adobecollabsync.exe": "Adobe Collab Sync",
    "ccxprocess.exe": "Adobe Creative Cloud",
    "coresync.exe": "Adobe Core Sync",
    "adobe desktop service.exe": "Adobe Desktop Service",
    "creative cloud.exe": "Adobe Creative Cloud",
    "jusched.exe": "Atualizador Java",
    "ituneshelper.exe": "iTunes Helper",
    "spotify.exe": "Spotify",
    "epicgameslauncher.exe": "Epic Games Launcher (fechar só se o jogo não for da Epic)",
    "eadesktop.exe": "EA App",
    "upc.exe": "Ubisoft Connect",
    "battle.net.exe": "Battle.net",
    "zoom.exe": "Zoom",
    "msedge.exe": "Microsoft Edge (todas as abas!)",
    "ccleaner64.exe": "CCleaner",
    "utorrent.exe": "uTorrent",
    "qbittorrent.exe": "qBittorrent",
    "slack.exe": "Slack",
    "whatsapp.exe": "WhatsApp Desktop",
    "telegram.exe": "Telegram",
}
# Apps que só fechamos se o usuário marcar explicitamente na prévia (podem estar em uso).
OPT_IN_ONLY = {"msedge.exe", "spotify.exe", "epicgameslauncher.exe", "eadesktop.exe", "upc.exe",
               "battle.net.exe", "zoom.exe", "slack.exe", "whatsapp.exe", "telegram.exe", "ms-teams.exe",
               "teams.exe", "skype.exe"}


class ProcessSampler:
    """Mantém objetos psutil.Process em cache para medir CPU% corretamente entre amostras."""

    def __init__(self):
        self._procs: dict[int, psutil.Process] = {}
        self._lock = threading.Lock()
        self._ncpu = psutil.cpu_count() or 1

    def sample(self) -> list[dict]:
        out = []
        with self._lock:
            seen = set()
            for p in psutil.process_iter(["pid", "name", "memory_info", "username", "exe"]):
                pid = p.pid
                seen.add(pid)
                proc = self._procs.get(pid)
                if proc is None:
                    proc = p
                    self._procs[pid] = p
                    try:
                        proc.cpu_percent(None)
                    except psutil.Error:
                        pass
                    continue
                try:
                    cpu = proc.cpu_percent(None) / self._ncpu
                    mi = p.info["memory_info"]
                    out.append({"pid": pid, "name": p.info["name"] or "?", "cpu": cpu,
                                "mem": mi.rss if mi else 0,
                                "exe": p.info.get("exe") or "",
                                "protected": (p.info["name"] or "").lower() in PROTECTED})
                except psutil.Error:
                    continue
            for pid in list(self._procs):
                if pid not in seen:
                    del self._procs[pid]
        return out


sampler = ProcessSampler()


def top_processes(by: str = "cpu", n: int = 15) -> list[dict]:
    procs = [p for p in sampler.sample() if p["pid"] not in (0, 4) and p["name"] != "System Idle Process"]
    procs.sort(key=lambda p: p[by], reverse=True)
    return procs[:n]


def find_background_apps(never_kill: list[str] | None = None, extra: list[str] | None = None) -> list[dict]:
    """Lista apps de segundo plano não essenciais em execução (agrupados por nome)."""
    never = {n.lower() for n in (never_kill or [])}
    catalog = dict(BACKGROUND_APPS)
    for e in extra or []:
        catalog.setdefault(e.lower(), e)
    me = os.getpid()
    fg = None
    try:
        from .winapi import foreground_pid
        fg = foreground_pid()
    except Exception:
        pass
    found: dict[str, dict] = {}
    for p in psutil.process_iter(["pid", "name", "memory_info", "exe", "cmdline"]):
        name = (p.info["name"] or "").lower()
        if name not in catalog or name in never or name in PROTECTED or p.pid in (me, fg):
            continue
        item = found.setdefault(name, {"name": name, "label": catalog[name], "pids": [], "mem": 0,
                                       "exe": p.info.get("exe") or "", "cmdline": p.info.get("cmdline") or [],
                                       "default": name not in OPT_IN_ONLY})
        item["pids"].append(p.pid)
        try:
            item["mem"] += p.info["memory_info"].rss
        except Exception:
            pass
    return sorted(found.values(), key=lambda x: x["mem"], reverse=True)


def close_apps(apps: list[dict], journal: Journal | None = None, gid: str = "session:turbo",
               relaunch: bool = True) -> tuple[int, int]:
    """Fecha os apps (primeiro de forma gentil, depois força). Registra para reabrir ao reverter."""
    closed, freed = 0, 0
    for app in apps:
        procs = []
        for pid in app["pids"]:
            try:
                procs.append(psutil.Process(pid))
            except psutil.Error:
                pass
        for p in procs:
            try:
                p.terminate()
            except psutil.Error:
                pass
        _gone, alive = psutil.wait_procs(procs, timeout=3)
        for p in alive:
            try:
                p.kill()
            except psutil.Error:
                pass
        closed += 1
        freed += app["mem"]
        if journal and relaunch and app.get("exe"):
            journal.group(gid, "Sessão de otimização", "sessao")
            journal.add_action(gid, {"kind": "relaunch", "exe": app["exe"], "cmdline": app["cmdline"],
                                     "desc": f"Reabrir {app['label']}"})
        log.info("Fechado %s (%s)", app["name"], app["pids"])
    return closed, freed


def kill_pid(pid: int) -> tuple[bool, str]:
    try:
        p = psutil.Process(pid)
        name = p.name()
        if name.lower() in PROTECTED or pid in (0, 4, os.getpid()):
            return False, f"{name} é um processo protegido do sistema."
        p.terminate()
        try:
            p.wait(3)
        except psutil.TimeoutExpired:
            p.kill()
        return True, f"{name} encerrado."
    except psutil.Error as e:
        return False, f"Não foi possível encerrar: {e}"


PRIORITIES = {
    "Tempo real": getattr(psutil, "REALTIME_PRIORITY_CLASS", -20),
    "Alta": getattr(psutil, "HIGH_PRIORITY_CLASS", -10),
    "Acima do normal": getattr(psutil, "ABOVE_NORMAL_PRIORITY_CLASS", -5),
    "Normal": getattr(psutil, "NORMAL_PRIORITY_CLASS", 0),
    "Abaixo do normal": getattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS", 5),
    "Baixa": getattr(psutil, "IDLE_PRIORITY_CLASS", 19),
}


def set_priority(pid: int, label: str) -> tuple[bool, str]:
    if label == "Tempo real":
        return False, "Prioridade Tempo real pode travar o sistema; use Alta."
    try:
        p = psutil.Process(pid)
        if p.name().lower() in PROTECTED:
            return False, "Processo protegido."
        p.nice(PRIORITIES[label])
        return True, f"Prioridade de {p.name()} definida como {label}."
    except psutil.Error as e:
        return False, str(e)


def wait_cpu_settle(seconds: float = 0.5):
    time.sleep(seconds)
