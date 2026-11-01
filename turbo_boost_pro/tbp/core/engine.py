"""Motor de otimização: monta planos (exibidos antes da execução), executa com segurança
(ponto de restauração + backup) e controla TURBO MODE, modos e sessões de jogo automáticas."""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import psutil

from ..config import settings
from ..utils import fmt_bytes, log
from . import memory, network, power, processes, restore_point, services, winapi
from .gaming import apply_profile_registry, profiles
from .journal import journal
from .tweaks import TWEAKS, TWEAKS_BY_ID

TURBO_GID = "session:turbo"
GAME_GID = "session:game"


@dataclass
class Action:
    id: str
    section: str
    title: str
    details: list[str] = field(default_factory=list)
    run: Callable[[], str] | None = None
    admin: bool = False
    critical: bool = False     # altera configuração do sistema -> ponto de restauração
    selected: bool = True
    note: str = ""
    locked: bool = False       # não pode ser desmarcado na prévia


@dataclass
class ExecResult:
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped_admin: list[str] = field(default_factory=list)


class Engine:
    def __init__(self):
        self.journal = journal
        self.events: queue.Queue = queue.Queue()
        self._busy = threading.Lock()
        self.autopilot = AutoPilot(self)

    # ================================================================ util
    def notify(self, text: str, level: str = "info"):
        self.events.put((level, text))
        log.info("EVENTO %s: %s", level, text)

    @property
    def turbo_active(self) -> bool:
        return self.journal.has_group(TURBO_GID)

    @property
    def mode(self) -> str:
        return settings.get("current_mode")

    # ================================================================ blocos de plano
    def _tweak_actions(self, ids: list[str], section: str, only_pending: bool = True,
                       track_turbo: bool = False) -> list[Action]:
        out = []
        for tid in ids:
            t = TWEAKS_BY_ID[tid]
            st = t.status()
            if st == "indisponivel" or (only_pending and st == "aplicado"):
                continue

            def _run(t=t):
                t.apply(self.journal)
                if track_turbo:
                    g = self.journal.group(TURBO_GID)
                    lst = g["meta"].setdefault("tweaks", [])
                    if t.id not in lst:
                        lst.append(t.id)
                    self.journal.save()
                return f"✔ {t.title}"
            out.append(Action(f"tweak:{t.id}", section, t.title, [t.description] + t.preview_lines(), _run,
                              admin=t.requires_admin(), critical=True, note=t.note))
        return out

    def _power_action(self, track_turbo=False) -> list[Action]:
        if power.is_turbo_active():
            return []
        bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None

        def _run():
            msg = power.apply_turbo_plan(self.journal)
            if track_turbo:
                self.journal.set_meta(TURBO_GID, "power", True)
            return "✔ " + msg
        return [Action("power", "Energia e processador", "Plano de energia TURBO BOOST PRO (desempenho máximo)",
                       power.preview(bool(bat and not bat.power_plugged)), _run, critical=True)]

    def _ram_action(self) -> Action:
        st = memory.ram_status()

        def _run():
            r = memory.optimize_ram(deep=True)
            return f"✔ RAM: {fmt_bytes(r['freed'])} liberados ({r['processes']} processos compactados). {r['message']}"
        details = [f"Uso atual: {st['percent']:.0f}% ({fmt_bytes(st['used'])} de {fmt_bytes(st['total'])})",
                   "Compacta a memória de processos em segundo plano (nada é fechado)",
                   "Com administrador: também esvazia o cache em espera (Standby List)"]
        return Action("ram", "Memória RAM", "Liberar memória RAM", details, _run)

    def _bg_apps_actions(self, gid: str) -> list[Action]:
        out = []
        apps = processes.find_background_apps(settings.get("never_kill"), settings.get("custom_kill_list"))
        for app in apps:
            def _run(app=app):
                n, freed = processes.close_apps([app], self.journal, gid, settings.get("relaunch_closed_apps"))
                return f"✔ {app['label']} encerrado (~{fmt_bytes(freed)})"
            out.append(Action(f"app:{app['name']}", "Apps em segundo plano", f"Encerrar {app['label']}",
                              [f"{app['name']} - {len(app['pids'])} processo(s) - {fmt_bytes(app['mem'])} de RAM",
                               "Será reaberto ao desativar o modo (se a opção estiver ativa)"],
                              _run, selected=app["default"]))
        return out

    def _service_actions(self, gid: str) -> list[Action]:
        out = []
        default_on = {"WSearch", "DiagTrack", "dmwappushservice", "WerSvc", "DPS", "MapsBroker"}
        for s in services.session_candidates():
            def _run(name=s["name"]):
                ok, msg = services.stop_temporarily(name, self.journal, gid)
                if not ok:
                    raise RuntimeError(msg)
                return "✔ " + msg
            out.append(Action(f"svc:{s['name']}", "Serviços (parados só durante a sessão)",
                              f"Parar {s['label']}", [s["desc"], "Volta a rodar ao desativar o modo ou reiniciar."],
                              _run, admin=True, selected=s["name"] in default_on))
        return out

    # ================================================================ planos
    def plan_turbo(self) -> list[Action]:
        def _init():
            self.journal.group(TURBO_GID, "TURBO MODE", "sessao")
            self.journal.set_meta(TURBO_GID, "keep", True)
            self.journal.set_meta(TURBO_GID, "since", time.time())
            return "⚡ Sessão TURBO registrada (tudo poderá ser desfeito)"
        acts = [Action("turbo_init", "Segurança", "Registrar sessão TURBO para reversão com 1 clique",
                       ["Backup dos valores originais é salvo antes de cada alteração."], _init, locked=True)]
        acts += self._power_action(track_turbo=True)
        acts.append(self._ram_action())
        if settings.get("close_bg_apps_in_turbo"):
            acts += self._bg_apps_actions(TURBO_GID)
        if settings.get("stop_services_in_turbo"):
            acts += self._service_actions(TURBO_GID)
        acts += self._tweak_actions([t.id for t in TWEAKS if t.turbo], "Otimizações do Windows e jogos",
                                    track_turbo=True)
        acts.append(Action("dns_flush", "Rede", "Limpar cache DNS", ["ipconfig /flushdns"],
                           lambda: "✔ Cache DNS limpo" if network.flush_dns() else "Cache DNS: falha"))
        return acts

    def turbo_off(self) -> list[str]:
        g = self.journal.data["groups"].get(TURBO_GID)
        errors = []
        if g:
            tweaks_applied = list(g["meta"].get("tweaks", []))
            used_power = g["meta"].get("power")
            errors += self.journal.revert_group(TURBO_GID)
            for tid in tweaks_applied:
                if tid in TWEAKS_BY_ID:
                    errors += TWEAKS_BY_ID[tid].revert(self.journal)
            if used_power and self.mode not in ("maximo", "gamer"):
                power.set_balanced(self.journal)
        self.notify("TURBO MODE desativado. Configurações anteriores restauradas.")
        return errors

    def plan_mode(self, mode: str) -> list[Action]:
        acts: list[Action] = []
        if mode == "equilibrado":
            def _run():
                errs = []
                if self.turbo_active:
                    errs += self.turbo_off()
                errs += self.journal.revert_group(GAME_GID)
                winapi.set_timer_resolution(False)
                msg = power.set_balanced(self.journal)
                return "✔ " + msg + (f" (avisos: {'; '.join(errs)})" if errs else "")
            acts.append(Action("mode_bal", "Modo Equilibrado", "Voltar ao plano de energia anterior/Equilibrado",
                               ["Desativa TURBO/sessões de jogo e restaura o plano de energia original.",
                                "Otimizações permanentes continuam até você usar RESTAURAR CONFIGURAÇÕES."], _run))
        if mode in ("maximo", "gamer"):
            acts += self._power_action()
            acts += self._tweak_actions([t.id for t in TWEAKS if t.turbo], "Máximo desempenho")
        if mode == "gamer":
            acts += self._tweak_actions([t.id for t in TWEAKS if t.gamer and not t.turbo], "Jogos")
            acts.append(Action("timer", "Jogos", "Resolução de timer de 0,5 ms (enquanto o app estiver aberto)",
                               ["Reduz a latência de agendamento do Windows para jogos.",
                                "Desfeito automaticamente ao fechar o TURBO BOOST PRO."],
                               lambda: f"✔ Timer: {winapi.set_timer_resolution(True) or 0.5:.1f} ms"))
            acts.append(Action("game_detect", "Jogos", "Ativar detecção automática de jogos",
                               ["Ao abrir um jogo com perfil (ou detectado automaticamente), aplica prioridade "
                                "alta, para serviços temporários e libera RAM. Tudo volta ao fechar o jogo."],
                               lambda: (settings.set("auto_game_boost", True), "✔ Detecção de jogos ativa")[1]))
        if mode == "automatico":
            acts.append(Action("auto", "Modo Automático", "Ativar otimização automática em segundo plano",
                               [f"Libera RAM quando o uso passar de {settings.get('auto_ram_threshold')}%",
                                "Detecta jogos e aplica boost de sessão (revertido ao fechar o jogo)",
                                "Não fecha apps sem sua autorização"],
                               lambda: (settings.set("auto_mode", True), settings.set("auto_game_boost", True),
                                        "✔ Modo automático ativo")[2]))
        else:
            if mode != "gamer":
                acts.append(Action("auto_off", "Geral", "Desativar otimização automática", [],
                                   lambda: (settings.set("auto_mode", False), "✔ Automático desativado")[1]))
        acts.append(Action("mode_mark", "Geral", "Registrar modo selecionado", [],
                           lambda: (settings.set("current_mode", mode), f"Modo atual: {MODE_NAMES[mode]}")[1]))
        return acts

    def plan_tweaks(self, ids: list[str], revert: bool = False) -> list[Action]:
        if not revert:
            return self._tweak_actions(ids, "Otimizações selecionadas", only_pending=True)
        out = []
        for tid in ids:
            t = TWEAKS_BY_ID[tid]
            if not self.journal.has_group(t.gid):
                continue
            out.append(Action(f"revert:{tid}", "Reverter", f"Reverter: {t.title}",
                              ["Restaura os valores originais salvos no backup."],
                              lambda t=t: "✔ Revertido: " + t.title if not t.revert(self.journal)
                              else f"Revertido parcialmente: {t.title}", admin=t.requires_admin()))
        return out

    # ================================================================ execução
    def execute(self, actions: list[Action], progress: Callable[[float, str], None] | None = None) -> ExecResult:
        res = ExecResult()
        sel = [a for a in actions if a.selected]
        if not sel:
            return res
        with self._busy:
            admin = winapi.is_admin()
            if any(a.critical for a in sel):
                self.journal.export_copy()
                if settings.get("restore_point_before_changes") and admin:
                    if progress:
                        progress(0.02, "Criando ponto de restauração do sistema…")
                    ok, msg = restore_point.create()
                    (res.messages if ok else res.errors).append(("✔ " if ok else "⚠ ") + msg)
            for i, a in enumerate(sel):
                if progress:
                    progress((i + 1) / (len(sel) + 1), a.title)
                if a.admin and not admin:
                    res.skipped_admin.append(a.title)
                    continue
                try:
                    msg = a.run() if a.run else ""
                    if msg:
                        res.messages.append(msg)
                except PermissionError:
                    res.skipped_admin.append(a.title)
                except Exception as e:
                    log.exception("Falha em %s", a.id)
                    res.errors.append(f"{a.title}: {e}")
            if progress:
                progress(1.0, "Concluído")
        return res

    def restore_everything(self) -> list[str]:
        """Desfaz TODAS as modificações registradas (botão RESTAURAR CONFIGURAÇÕES)."""
        errors = []
        if self.turbo_active:
            errors += self.turbo_off()
        errors += self.journal.revert_all()
        winapi.set_timer_resolution(False)
        settings.set("auto_mode", False)
        settings.set("current_mode", "equilibrado")
        winapi.broadcast_settings_change()
        winapi.apply_mouse_settings_live()
        return errors

    # ================================================================ sessão de jogo
    def start_game_session(self, pid: int, name: str, profile: dict | None):
        if self.journal.has_group(GAME_GID):
            return
        p = profile or {"priority": "Alta", "close_bg": False, "stop_services": True, "trim_ram": True,
                        "timer": True}
        self.journal.group(GAME_GID, f"Sessão de jogo: {name}", "sessao")
        self.journal.set_meta(GAME_GID, "keep", True)
        self.journal.set_meta(GAME_GID, "pid", pid)
        done = []
        ok, _ = processes.set_priority(pid, p.get("priority", "Alta"))
        if ok:
            done.append(f"prioridade {p.get('priority', 'Alta')}")
        if p.get("stop_services") and winapi.is_admin():
            for svc in ("WSearch", "DiagTrack", "WerSvc"):
                if services.stop_temporarily(svc, self.journal, GAME_GID)[0]:
                    done.append(f"{svc} pausado")
        if p.get("close_bg"):
            apps = [a for a in processes.find_background_apps(settings.get("never_kill")) if a["default"]]
            n, _f = processes.close_apps(apps, self.journal, GAME_GID, settings.get("relaunch_closed_apps"))
            if n:
                done.append(f"{n} apps fechados")
        if p.get("trim_ram"):
            r = memory.optimize_ram(deep=True, exclude_pids={pid})
            done.append(f"{fmt_bytes(r['freed'])} de RAM liberados")
        if p.get("timer") and not winapi.timer_resolution_active():
            winapi.set_timer_resolution(True)
            self.journal.set_meta(GAME_GID, "timer", True)
        self.notify(f"🎮 {name} detectado: {', '.join(done) or 'boost aplicado'}.", "game")

    def end_game_session(self):
        g = self.journal.data["groups"].get(GAME_GID)
        if not g:
            return
        if g["meta"].get("timer") and self.mode != "gamer":
            winapi.set_timer_resolution(False)
        self.journal.revert_group(GAME_GID)
        self.notify("Jogo encerrado: serviços e apps restaurados.", "game")


MODE_NAMES = {"automatico": "Automático", "gamer": "Gamer", "maximo": "Máximo Desempenho",
              "equilibrado": "Equilibrado"}

# Processos com alto uso de GPU que NÃO são jogos (evita falso positivo na detecção automática).
NOT_GAMES = {"chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe", "obs64.exe", "vlc.exe",
             "explorer.exe", "dwm.exe", "blender.exe", "premiere.exe", "afterfx.exe", "resolve.exe",
             "photoshop.exe", "mpc-hc64.exe", "potplayermini64.exe", "zoom.exe", "teams.exe", "ms-teams.exe",
             "discord.exe", "steam.exe", "steamwebhelper.exe", "turboboostpro.exe", "python.exe", "pythonw.exe"}


class AutoPilot(threading.Thread):
    """Modo automático: detecção de jogos (perfis + heurística) e liberação de RAM sob pressão."""

    def __init__(self, engine: Engine):
        super().__init__(daemon=True, name="AutoPilot")
        self.engine = engine
        self.monitor = None
        self._halt = threading.Event()
        self._last_trim = 0.0
        self._candidate: tuple[int, int] | None = None
        self.game_pid: int | None = None
        self._applied_profiles: set[str] = set()

    def stop(self):
        self._halt.set()

    def run(self):
        while not self._halt.wait(3):
            try:
                self._tick()
            except Exception:
                log.exception("AutoPilot")

    def _tick(self):
        eng = self.engine
        # 1) jogo da sessão terminou?
        if self.game_pid and not psutil.pid_exists(self.game_pid):
            self.game_pid = None
            eng.end_game_session()
        elif self.game_pid is None and eng.journal.has_group(GAME_GID):
            pid = eng.journal.group(GAME_GID)["meta"].get("pid")
            if not pid or not psutil.pid_exists(pid):  # sessão órfã (app fechado durante o jogo)
                eng.end_game_session()
        # 2) jogos com perfil
        if settings.get("auto_game_boost") and self.game_pid is None:
            prof_names = profiles.exe_names()
            if prof_names:
                for proc in psutil.process_iter(["pid", "name", "exe"]):
                    name = (proc.info["name"] or "").lower()
                    if name in prof_names:
                        prof = prof_names[name]
                        if prof["exe"] not in self._applied_profiles:
                            apply_profile_registry(prof, eng.journal)
                            self._applied_profiles.add(prof["exe"])
                        self.game_pid = proc.pid
                        eng.start_game_session(proc.pid, prof["name"], prof)
                        break
        # 3) heurística (modo automático): app em primeiro plano usando muita GPU por ~9 s
        snap = self.monitor.get() if self.monitor else {}
        if settings.get("auto_mode") and self.game_pid is None and (snap.get("gpu") or 0) > 55:
            fg = winapi.foreground_pid()
            try:
                name = psutil.Process(fg).name().lower() if fg else ""
            except psutil.Error:
                name = ""
            if fg and name and name not in NOT_GAMES and name not in processes.PROTECTED:
                if self._candidate and self._candidate[0] == fg:
                    self._candidate = (fg, self._candidate[1] + 1)
                    if self._candidate[1] >= 3:
                        self.game_pid = fg
                        eng.start_game_session(fg, name, None)
                        self._candidate = None
                else:
                    self._candidate = (fg, 1)
        # 4) RAM sob pressão
        if settings.get("auto_mode") and snap.get("ram", 0) > settings.get("auto_ram_threshold", 85):
            if time.time() - self._last_trim > 120:
                self._last_trim = time.time()
                r = memory.optimize_ram(deep=True, exclude_pids={self.game_pid} if self.game_pid else None)
                eng.notify(f"Modo automático: RAM em {snap['ram']:.0f}%, {fmt_bytes(r['freed'])} liberados.")


engine = Engine()

