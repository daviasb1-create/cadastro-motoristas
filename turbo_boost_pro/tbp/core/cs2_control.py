"""Controle do CS2 para benchmark reproduzível.

Usa o console de rede OFICIAL do motor Source 2 (opção de inicialização -netconport): o TURBO BOOST PRO envia
comandos de console como 'playdemo' e 'demo_gototick', exatamente como se você os digitasse no console.
Não injeta código, não lê a memória do jogo e não usa -insecure (o VAC continua ativo).

Reprodutibilidade: cada medição carrega a MESMA demo e pula para o MESMO tick, então todas as configurações
renderizam exatamente as mesmas cenas.
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import threading
import time

import psutil

from ..config import IS_WINDOWS, settings
from ..utils import log
from . import registry as reg
from .system_mods import find_cs2

NETCON_PORT = 29031
DEMO_NAME = "tbp_bench"


class CS2Error(RuntimeError):
    pass


def steam_exe() -> str | None:
    for hive, path, val in (("HKCU", r"Software\Valve\Steam", "SteamExe"),
                            ("HKLM", r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")):
        ok, _t, v = reg.read_value(hive, path, val)
        if ok and v:
            exe = v if str(v).lower().endswith(".exe") else os.path.join(v, "steam.exe")
            if os.path.isfile(exe):
                return os.path.normpath(exe)
    return None


def cs2_pid() -> int | None:
    for p in psutil.process_iter(["name"]):
        if (p.info["name"] or "").lower() == "cs2.exe":
            return p.pid
    return None


def demo_path() -> str | None:
    cs = find_cs2()
    if not cs:
        return None
    return os.path.join(os.path.dirname(cs["cfg_dir"]), f"{DEMO_NAME}.dem")


def install_demo(src: str) -> str:
    """Copia a demo escolhida para a pasta do CS2 com um nome fixo (tbp_bench.dem)."""
    dst = demo_path()
    if not dst:
        raise CS2Error("CS2 não encontrado.")
    if not src.lower().endswith(".dem") or not os.path.isfile(src):
        raise CS2Error("Selecione um arquivo .dem válido.")
    shutil.copy2(src, dst)
    settings.set("bench_demo_src", src)
    return dst


def demo_ready() -> bool:
    p = demo_path()
    return bool(p and os.path.isfile(p))


class NetCon:
    """Cliente do console de rede do CS2 (texto simples via TCP em localhost)."""

    def __init__(self, port: int = NETCON_PORT):
        self.port = port
        self.sock: socket.socket | None = None
        self.buffer = ""
        self._lock = threading.Lock()

    def connect(self, timeout: float = 240, cancel=None) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if cancel is not None and cancel.is_set():
                return False
            try:
                s = socket.create_connection(("127.0.0.1", self.port), timeout=3)
                s.settimeout(0.2)
                self.sock = s
                log.info("NETCON conectado na porta %s", self.port)
                return True
            except OSError:
                time.sleep(2)
        return False

    def send(self, cmd: str):
        if not re.fullmatch(r"[A-Za-z0-9_ .\-+]{1,120}", cmd):
            raise CS2Error(f"Comando de console inválido: {cmd!r}")
        if not self.sock:
            raise CS2Error("Console do CS2 desconectado.")
        log.info("NETCON > %s", cmd)
        self.sock.sendall((cmd + "\n").encode())

    def pump(self) -> str:
        if not self.sock:
            return ""
        chunks = []
        try:
            while True:
                data = self.sock.recv(65536)
                if not data:
                    break
                chunks.append(data.decode("utf-8", "replace"))
        except (socket.timeout, BlockingIOError):
            pass
        except OSError:
            self.sock = None
        text = "".join(chunks)
        with self._lock:
            self.buffer = (self.buffer + text)[-200000:]
        return text

    def wait_for(self, pattern: str, timeout: float, cancel=None) -> bool:
        rx = re.compile(pattern, re.I)
        end = time.time() + timeout
        seen = ""
        while time.time() < end:
            if cancel is not None and cancel.is_set():
                return False
            seen += self.pump()
            if rx.search(seen):
                return True
            time.sleep(0.3)
        return False

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        finally:
            self.sock = None


def launch_cs2(port: int = NETCON_PORT) -> None:
    exe = steam_exe()
    if not exe:
        raise CS2Error("Steam não encontrada.")
    args = [exe, "-applaunch", "730", "-netconport", str(port), "-novid", "-nojoy"]
    log.info("Iniciando CS2: %s", args)
    subprocess.Popen(args, close_fds=True)


def quit_cs2(con: NetCon | None, timeout: float = 40):
    pid = cs2_pid()
    if not pid:
        return
    try:
        if con and con.sock:
            con.send("quit")
    except Exception:
        pass
    end = time.time() + timeout
    while time.time() < end and cs2_pid():
        time.sleep(1)
    pid = cs2_pid()
    if pid:
        try:
            psutil.Process(pid).terminate()
        except psutil.Error:
            pass
        time.sleep(3)


class DemoRunner:
    """Prepara uma medição reproduzível: playdemo → aguarda carregar → demo_gototick → captura."""

    def __init__(self, port: int = NETCON_PORT):
        self.con = NetCon(port)
        self.loaded = False

    def ensure_game(self, cancel=None, status=lambda t: None) -> None:
        """Garante o CS2 aberto COM o console de rede. Reinicia o jogo se ele foi aberto sem a opção."""
        if self.con.sock:
            return
        if cs2_pid():
            status("Conectando ao console do CS2…")
            if self.con.connect(timeout=6, cancel=cancel):
                return
            status("CS2 aberto sem o console de rede: reiniciando o jogo…")
            quit_cs2(None)
        status("Abrindo o CS2 pela Steam…")
        launch_cs2(self.con.port)
        if not self.con.connect(timeout=300, cancel=cancel):
            raise CS2Error("Não foi possível conectar ao console do CS2 (-netconport). Use o modo manual.")
        status("CS2 aberto; aguardando o menu principal…")
        time.sleep(settings.get("bench_menu_wait", 25))

    def prepare(self, cancel=None, status=lambda t: None):
        if not demo_ready():
            raise CS2Error("Demo de benchmark não configurada.")
        self.ensure_game(cancel, status)
        self.con.pump()
        status("Carregando a demo de benchmark…")
        self.con.send(f"playdemo {DEMO_NAME}")
        time.sleep(settings.get("bench_load_wait", 30))
        tick = int(settings.get("bench_demo_tick", 2000))
        self.con.send(f"demo_gototick {tick}")
        self.con.send("demo_timescale 1")
        time.sleep(6)  # assenta após o salto (streaming de texturas)
        if not cs2_pid():
            raise CS2Error("O CS2 fechou durante o carregamento (instabilidade).")
        self.loaded = True

    def seek(self, cancel=None, status=lambda t: None):
        """Volta ao MESMO tick da demo antes de cada medição (cenas idênticas em todas as capturas)."""
        if not self.loaded or not self.con.sock or not cs2_pid():
            self.loaded = False
            self.prepare(cancel, status)
            return
        status("Reposicionando a demo no tick de referência…")
        self.con.send(f"demo_gototick {int(settings.get('bench_demo_tick', 2000))}")
        time.sleep(5)

    def finish(self):
        self.loaded = False
        try:
            self.con.send("disconnect")
        except Exception:
            pass
        time.sleep(3)

    def restart_game(self, cancel=None, status=lambda t: None):
        status("Reiniciando o CS2 para aplicar a configuração…")
        self.loaded = False
        quit_cs2(self.con)
        self.con.close()
        time.sleep(5)
        self.ensure_game(cancel, status)

    def close(self):
        self.loaded = False
        quit_cs2(self.con)
        self.con.close()


__all__ = ["DemoRunner", "CS2Error", "install_demo", "demo_ready", "demo_path", "cs2_pid", "steam_exe",
           "IS_WINDOWS"]
