"""Janela principal: barra lateral, carregamento sob demanda das páginas e notificações."""
from __future__ import annotations

import importlib
import queue

import customtkinter as ctk

from .. import __version__
from ..config import resource_path, settings
from ..core import winapi
from ..core.engine import MODE_NAMES, engine
from ..core.monitor import SystemMonitor
from . import theme as T
from .widgets import run_bg

PAGES = [
    ("dashboard", "◉  Painel", "dashboard.DashboardPage"),
    ("gaming", "🎮  Gaming Boost", "gaming.GamingPage"),
    ("cleaner", "🧹  Limpeza", "cleaner.CleanerPage"),
    ("performance", "📊  Desempenho", "performance.PerformancePage"),
    ("advanced", "⚙  Windows Avançado", "advanced.AdvancedPage"),
    ("diagnostics", "🔍  Diagnóstico", "diagnostics.DiagnosticsPage"),
    ("security", "🛡  Segurança", "security.SecurityPage"),
]


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title(f"TURBO BOOST PRO {__version__}")
        self.geometry("1320x840")
        self.minsize(1120, 720)
        self.configure(fg_color=T.BG)
        try:
            self.iconbitmap(resource_path("assets/icon.ico"))
        except Exception:
            pass
        self.monitor = SystemMonitor(settings.get("monitor_interval_ms", 1000) / 1000)
        self.monitor.start()
        engine.autopilot.monitor = self.monitor
        engine.autopilot.start()
        self.pages: dict[str, ctk.CTkFrame] = {}
        self.current = None
        self.nav_buttons = {}
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self.content = ctk.CTkFrame(self, fg_color=T.BG, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self.toast = None
        self.show("dashboard")
        self.protocol("WM_DELETE_WINDOW", self.shutdown)
        self.after(500, self._tick)
        self.after(300, self._poll_events)

    # ---------------------------------------------------------------- sidebar
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, fg_color=T.SIDEBAR, corner_radius=0, width=240, border_width=0)
        sb.grid(row=0, column=0, sticky="nsw")
        sb.grid_propagate(False)
        logo = ctk.CTkFrame(sb, fg_color="transparent")
        logo.pack(fill="x", padx=20, pady=(24, 4))
        ctk.CTkLabel(logo, text="⚡ TURBO", font=T.font(28, "bold", True), text_color=T.NEON).pack(anchor="w")
        ctk.CTkLabel(logo, text="BOOST PRO", font=T.font(16, "bold", True), text_color=T.TEXT).pack(anchor="w")
        ctk.CTkFrame(sb, height=2, fg_color=T.NEON_DARK).pack(fill="x", padx=20, pady=(12, 16))
        for key, label, _ in PAGES:
            b = ctk.CTkButton(sb, text=label, anchor="w", height=44, corner_radius=10, font=T.font(14, "bold"),
                              fg_color="transparent", hover_color=T.CARD_HI, text_color=T.MUTED,
                              command=lambda k=key: self.show(k))
            b.pack(fill="x", padx=12, pady=2)
            self.nav_buttons[key] = b
        bottom = ctk.CTkFrame(sb, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=16, pady=16)
        self.mode_label = ctk.CTkLabel(bottom, text="", font=T.font(12, "bold"), text_color=T.NEON)
        self.mode_label.pack(anchor="w")
        admin = winapi.is_admin()
        ctk.CTkLabel(bottom, text="● Administrador" if admin else "● Usuário padrão",
                     font=T.font(11), text_color=T.OK if admin else T.WARN).pack(anchor="w")
        if not admin:
            ctk.CTkButton(bottom, text="Elevar para admin", height=28, fg_color=T.CARD, hover_color=T.CARD_HI,
                          border_width=1, border_color=T.WARN, text_color=T.WARN, font=T.font(11, "bold"),
                          command=self._elevate).pack(fill="x", pady=(6, 0))
        ctk.CTkLabel(bottom, text=f"v{__version__} · 100% offline", font=T.font(10),
                     text_color=T.SUBTLE).pack(anchor="w", pady=(6, 0))

    def _elevate(self):
        from .dialogs import ask_admin
        ask_admin(self, "Recursos como serviços, plano de energia avançado, registro do sistema e limpeza "
                        "do Windows exigem administrador.")

    def refresh_mode_label(self):
        turbo = " · TURBO ON" if engine.turbo_active else ""
        auto = " · AUTO" if settings.get("auto_mode") else ""
        self.mode_label.configure(text=f"Modo: {MODE_NAMES.get(engine.mode, engine.mode)}{turbo}{auto}")

    # ---------------------------------------------------------------- páginas
    def show(self, key: str):
        if key not in self.pages:
            mod_name, cls_name = next(p[2] for p in PAGES if p[0] == key).split(".")
            mod = importlib.import_module(f"tbp.ui.pages.{mod_name}")
            holder = ctk.CTkFrame(self.content, fg_color=T.BG, corner_radius=0)
            holder.grid(row=0, column=0, sticky="nsew")
            page = getattr(mod, cls_name)(holder, self)
            page.pack(fill="both", expand=True)
            page.holder = holder
            self.pages[key] = page
        for k, b in self.nav_buttons.items():
            sel = k == key
            b.configure(fg_color=T.NEON_DARK if sel else "transparent", text_color=T.NEON if sel else T.MUTED)
        page = self.pages[key]
        page.holder.tkraise()
        self.current = key
        if hasattr(page, "on_show"):
            page.on_show()
        self.refresh_mode_label()

    def _tick(self):
        snap = self.monitor.get()
        page = self.pages.get(self.current)
        if snap and page is not None and hasattr(page, "on_tick"):
            try:
                page.on_tick(snap)
            except Exception:
                pass
        self.after(1000, self._tick)

    # ---------------------------------------------------------------- notificações
    def _poll_events(self):
        try:
            while True:
                level, text = engine.events.get_nowait()
                self.notify(text, level)
        except queue.Empty:
            pass
        self.after(500, self._poll_events)

    def notify(self, text: str, level: str = "info"):
        if self.toast is not None:
            self.toast.destroy()
        color = {"info": T.NEON, "game": T.OK, "warn": T.WARN, "error": T.BAD}.get(level, T.NEON)
        t = ctk.CTkFrame(self, fg_color=T.CARD_HI, corner_radius=12, border_width=1, border_color=color)
        ctk.CTkLabel(t, text=text, text_color=T.TEXT, font=T.font(12, "bold"), wraplength=420,
                     justify="left").pack(padx=16, pady=10)
        t.place(relx=1.0, rely=1.0, x=-20, y=-20, anchor="se")
        self.toast = t
        self.after(5000, lambda: t.winfo_exists() and t.destroy())
        self.refresh_mode_label()

    def run_async(self, fn, on_done=None):
        run_bg(self, fn, on_done)

    def plan_and_run(self, title, builder, after=None, subtitle=""):
        """Monta o plano em segundo plano (pode consultar o sistema) e abre a prévia."""
        from .dialogs import run_plan
        self.configure(cursor="watch")

        def ready(actions):
            self.configure(cursor="")
            run_plan(self, title, actions, after=lambda res: (self.refresh_mode_label(), after and after(res)),
                     subtitle=subtitle)
        run_bg(self, builder, ready, lambda e: (self.configure(cursor=""), self.notify(f"Erro: {e}", "error")))

    def shutdown(self):
        try:
            self.monitor.stop()
            engine.autopilot.stop()
            winapi.set_timer_resolution(False)
        finally:
            self.destroy()


def main():
    app = App()
    app.mainloop()
