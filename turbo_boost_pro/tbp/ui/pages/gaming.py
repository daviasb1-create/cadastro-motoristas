"""GAMING BOOST: otimizações de FPS/latência, timer, detecção automática e perfis por jogo."""
from __future__ import annotations

import os
from tkinter import filedialog, messagebox

import customtkinter as ctk

from ...config import settings
from ...core import winapi
from ...core.engine import Action, engine
from ...core.gaming import apply_profile_registry, detect_steam_games, profiles
from ...core.processes import PRIORITIES
from ...core.tweaks import TWEAKS
from .. import theme as T
from ..widgets import Card, TweakRow, ghost_button, page_header, primary_button


def tweak_toggle(app, tweak, rows_refresh):
    """Liga/desliga uma otimização com prévia; usada por várias páginas."""
    def handler(on: bool, row: TweakRow):
        row.set_state(not on)  # o estado real é aplicado após a confirmação
        if on:
            app.plan_and_run(tweak.title, lambda: engine.plan_tweaks([tweak.id]), after=lambda r: rows_refresh())
        else:
            if not engine.journal.has_group(tweak.gid):
                messagebox.showinfo("TURBO BOOST PRO", "Esta configuração já estava assim antes do TURBO BOOST "
                                    "PRO; não há backup para restaurar.", parent=row)
                return
            app.plan_and_run(f"Reverter: {tweak.title}", lambda: engine.plan_tweaks([tweak.id], revert=True),
                             after=lambda r: rows_refresh())
    return handler


class GamingPage(ctk.CTkScrollableFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color=T.BG)
        self.app = app
        self.rows: dict[str, TweakRow] = {}
        page_header(self, "GAMING BOOST", "Mais FPS, menos input lag e latência. Cada otimização mostra o que muda "
                    "e pode ser revertida.").pack(anchor="w", padx=24, pady=(20, 10))

        master_card = Card(self)
        master_card.pack(fill="x", padx=24, pady=6)
        mrow = ctk.CTkFrame(master_card, fg_color="transparent")
        mrow.pack(fill="x", padx=16, pady=14)
        ctk.CTkLabel(mrow, text="🎮  Todas as otimizações de jogos", font=T.font(18, "bold", True),
                     text_color=T.TEXT).pack(side="left")
        self.master_status = ctk.CTkLabel(mrow, text="", font=T.font(12, "bold"))
        self.master_status.pack(side="left", padx=14)
        ghost_button(mrow, "DESATIVAR TODAS", self.disable_all, width=150, border_color=T.BAD,
                     text_color=T.BAD).pack(side="right", padx=4)
        primary_button(mrow, "ATIVAR TODAS", self.enable_all, width=150).pack(side="right", padx=4)

        rt = Card(self, "Tempo de execução")
        rt.pack(fill="x", padx=24, pady=6)
        self.timer_var = ctk.BooleanVar(value=winapi.timer_resolution_active())
        ctk.CTkSwitch(rt, text="Resolução de timer 0,5 ms (reduz latência de quadros; ativo enquanto o app "
                      "estiver aberto)", variable=self.timer_var, command=self.toggle_timer,
                      progress_color=T.NEON, font=T.font(13), text_color=T.TEXT).pack(anchor="w", padx=16, pady=6)
        self.detect_var = ctk.BooleanVar(value=settings.get("auto_game_boost"))
        ctk.CTkSwitch(rt, text="Detecção automática de jogos (prioridade alta + boost de sessão ao abrir um jogo "
                      "com perfil)", variable=self.detect_var,
                      command=lambda: settings.set("auto_game_boost", self.detect_var.get()),
                      progress_color=T.NEON, font=T.font(13), text_color=T.TEXT).pack(anchor="w", padx=16,
                                                                                    pady=(0, 12))

        ctk.CTkLabel(self, text="OTIMIZAÇÕES DO SISTEMA PARA JOGOS", font=T.font(12, "bold", True),
                     text_color=T.NEON).pack(anchor="w", padx=26, pady=(14, 4))
        self.gamer_tweaks = [t for t in TWEAKS if t.gamer or t.category == "gaming"]
        for t in self.gamer_tweaks:
            row = TweakRow(self, t.title, t.description, tweak_toggle(app, t, self.refresh),
                           admin=t.requires_admin(), reboot=t.reboot, note=t.note, risk=t.risk, benefit=t.benefit)
            row.pack(fill="x", padx=24, pady=4)
            self.rows[t.id] = row

        # ------------------------------------------------ perfis
        ph = ctk.CTkFrame(self, fg_color="transparent")
        ph.pack(fill="x", padx=24, pady=(20, 4))
        ctk.CTkLabel(ph, text="PERFIS POR JOGO", font=T.font(12, "bold", True), text_color=T.NEON).pack(side="left")
        primary_button(ph, "+ Adicionar jogo (.exe)", self.add_game, width=190).pack(side="right", padx=4)
        ghost_button(ph, "Detectar jogos da Steam", self.detect_steam, width=190).pack(side="right", padx=4)
        ctk.CTkLabel(self, text="Ao abrir um jogo com perfil, o TURBO BOOST PRO aplica a prioridade escolhida, pausa "
                     "serviços, libera RAM e fecha apps de fundo (opcional). Tudo volta ao fechar o jogo.",
                     font=T.font(12), text_color=T.MUTED, wraplength=900, justify="left").pack(anchor="w", padx=26)
        self.profiles_box = ctk.CTkFrame(self, fg_color="transparent")
        self.profiles_box.pack(fill="x", padx=24, pady=(6, 24))
        self.refresh()

    def on_show(self):
        self.refresh()

    def refresh(self):
        def load():
            return {t.id: t.status() for t in self.gamer_tweaks}

        def done(st):
            for tid, s in st.items():
                self.rows[tid].set_state(s == "aplicado")
            n = sum(1 for s in st.values() if s == "aplicado")
            col = T.OK if n == len(st) else T.WARN if n else T.MUTED
            self.master_status.configure(text=f"{n}/{len(st)} ativas", text_color=col)
        self.app.run_async(load, done)
        self.timer_var.set(winapi.timer_resolution_active())
        self.render_profiles()

    def enable_all(self):
        def build():
            acts = engine.plan_tweaks([t.id for t in self.gamer_tweaks if t.risk == "Baixo"])
            acts.append(Action("timer", "Tempo de execução", "Resolução de timer 0,5 ms",
                               ["Ativo enquanto o app estiver aberto."],
                               lambda: f"✔ Timer: {winapi.set_timer_resolution(True) or 0.5:.1f} ms"))
            return acts
        self.app.plan_and_run("Ativar otimizações de jogos", build, after=lambda r: self.refresh(),
                              subtitle="Itens de risco médio (ex.: forçar tela cheia exclusiva) não entram no "
                                       "pacote; ative-os individualmente se quiser testar.")

    def disable_all(self):
        def build():
            acts = engine.plan_tweaks([t.id for t in self.gamer_tweaks], revert=True)
            acts.append(Action("timer_off", "Tempo de execução", "Desativar timer 0,5 ms", [],
                               lambda: (winapi.set_timer_resolution(False), "✔ Timer padrão")[1]))
            return acts
        self.app.plan_and_run("Desativar otimizações de jogos", build, after=lambda r: self.refresh())

    def toggle_timer(self):
        res = winapi.set_timer_resolution(self.timer_var.get())
        if res is not None:
            self.app.notify(f"Resolução do timer: {res:.2f} ms")

    # ---------------------------------------------------------------- perfis
    def add_game(self):
        path = filedialog.askopenfilename(title="Selecione o executável do jogo",
                                          filetypes=[("Executável", "*.exe")], parent=self)
        if path:
            p = profiles.add(path)
            apply_profile_registry(p, engine.journal)
            self.render_profiles()
            self.app.notify(f"Perfil criado para {p['name']}.")

    def detect_steam(self):
        def done(games):
            if not games:
                messagebox.showinfo("Steam", "Nenhum jogo da Steam encontrado.", parent=self)
                return
            new = [g for g in games if not profiles.get_by_exe(g["exe"])]
            if not new:
                messagebox.showinfo("Steam", "Todos os jogos encontrados já têm perfil.", parent=self)
                return
            names = "\n".join(f"• {g['name']}" for g in new[:25])
            if messagebox.askyesno("Steam", f"Criar perfis para {len(new)} jogo(s)?\n\n{names}", parent=self):
                for g in new:
                    p = profiles.add(g["exe"], g["name"])
                    apply_profile_registry(p, engine.journal)
                self.render_profiles()
        self.app.run_async(detect_steam_games, done)

    def render_profiles(self):
        for w in self.profiles_box.winfo_children():
            w.destroy()
        if not profiles.items:
            ctk.CTkLabel(self.profiles_box, text="Nenhum perfil ainda.", text_color=T.SUBTLE,
                         font=T.font(12)).pack(anchor="w", pady=8)
        for p in profiles.items:
            card = ctk.CTkFrame(self.profiles_box, fg_color=T.CARD, corner_radius=12, border_width=1,
                                border_color=T.BORDER)
            card.pack(fill="x", pady=4)
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=14, pady=(10, 2))
            ctk.CTkLabel(top, text="🎮 " + p["name"], font=T.font(14, "bold"), text_color=T.TEXT).pack(side="left")
            ctk.CTkLabel(top, text=os.path.basename(p["exe"]), font=T.font(11), text_color=T.SUBTLE).pack(
                side="left", padx=10)
            ghost_button(top, "Remover", lambda e=p["exe"]: self.remove(e), width=90, border_color=T.BAD,
                         text_color=T.BAD, height=28).pack(side="right")
            opts = ctk.CTkFrame(card, fg_color="transparent")
            opts.pack(fill="x", padx=14, pady=(2, 10))
            ctk.CTkLabel(opts, text="Prioridade:", text_color=T.MUTED, font=T.font(12)).pack(side="left")
            cb = ctk.CTkComboBox(opts, values=[k for k in PRIORITIES if k != "Tempo real"], width=150,
                                 command=lambda v, e=p["exe"]: profiles.update(e, priority=v),
                                 fg_color=T.CARD_HI, border_color=T.BORDER, button_color=T.NEON_DARK)
            cb.set(p.get("priority", "Alta"))
            cb.pack(side="left", padx=(6, 14))
            for key, label in (("gpu_high", "GPU dedicada"), ("disable_fso", "Tela cheia exclusiva"),
                               ("close_bg", "Fechar apps de fundo"), ("stop_services", "Pausar serviços"),
                               ("trim_ram", "Liberar RAM"), ("timer", "Timer 0,5 ms")):
                v = ctk.BooleanVar(value=p.get(key, False))
                ctk.CTkCheckBox(opts, text=label, variable=v, font=T.font(12), text_color=T.TEXT,
                                fg_color=T.NEON, border_color=T.NEON_DIM, checkbox_width=18, checkbox_height=18,
                                command=lambda k=key, v=v, e=p["exe"]: self.set_opt(e, k, v.get())).pack(
                    side="left", padx=6)

    def set_opt(self, exe, key, value):
        p = profiles.update(exe, **{key: value})
        if key in ("gpu_high", "disable_fso") and p:
            apply_profile_registry(p, engine.journal)

    def remove(self, exe):
        if messagebox.askyesno("Perfil", "Remover este perfil e reverter as configurações dele?", parent=self):
            profiles.remove(exe, engine.journal)
            self.render_profiles()
