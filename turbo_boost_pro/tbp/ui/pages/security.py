"""Segurança: RESTAURAR CONFIGURAÇÕES, histórico de alterações, ponto de restauração e preferências."""
from __future__ import annotations

import os
import subprocess
import time
from tkinter import messagebox

import customtkinter as ctk

from ...config import BACKUP_DIR, LOG_DIR, settings
from ...core import restore_point, winapi
from ...core.engine import engine
from .. import theme as T
from ..dialogs import ask_admin
from ..widgets import Card, ghost_button, page_header, primary_button, run_bg

CAT_LABEL = {"sessao": "Sessão", "energia": "Energia", "rede": "Rede", "inicializacao": "Inicialização",
             "servicos": "Serviços", "armazenamento": "Armazenamento", "jogos": "Jogos", "gaming": "Jogos",
             "responsividade": "Responsividade", "visual": "Visual", "segundo_plano": "Segundo plano",
             "geral": "Geral", "debloat": "Debloat", "recursos": "Recursos opcionais", "tarefas": "Tarefas",
             "perfil": "Perfil", "privacidade": "Privacidade"}


def _open(path):
    if os.name == "nt":
        os.startfile(path)  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", str(path)])


class SecurityPage(ctk.CTkScrollableFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color=T.BG)
        self.app = app
        page_header(self, "Segurança e Restauração", "Toda alteração tem backup do valor original. Defender, "
                    "Firewall e Windows Update nunca são desativados.").pack(anchor="w", padx=24, pady=(20, 10))

        big = Card(self)
        big.pack(fill="x", padx=24, pady=6)
        r = ctk.CTkFrame(big, fg_color="transparent")
        r.pack(fill="x", padx=18, pady=16)
        txt = ctk.CTkFrame(r, fg_color="transparent")
        txt.pack(side="left")
        ctk.CTkLabel(txt, text="↺  RESTAURAR CONFIGURAÇÕES", font=T.font(20, "bold", True),
                     text_color=T.TEXT).pack(anchor="w")
        ctk.CTkLabel(txt, text="Desfaz TODAS as modificações feitas pelo TURBO BOOST PRO: registro, serviços, "
                     "plano de energia, DNS, inicialização e sessões.", font=T.font(12), text_color=T.MUTED,
                     wraplength=640, justify="left").pack(anchor="w")
        ctk.CTkButton(r, text="RESTAURAR TUDO", command=self.restore_all, width=200, height=48, fg_color=T.BAD,
                      hover_color="#ff6680", text_color="#ffffff", font=T.font(15, "bold", True),
                      corner_radius=12).pack(side="right")

        rp = Card(self, "Ponto de restauração do Windows")
        rp.pack(fill="x", padx=24, pady=6)
        r2 = ctk.CTkFrame(rp, fg_color="transparent")
        r2.pack(fill="x", padx=16, pady=(6, 14))
        primary_button(r2, "Criar ponto agora", self.create_rp, width=170).pack(side="left")
        ghost_button(r2, "Abrir Restauração do Sistema", restore_point.open_system_restore, width=230).pack(
            side="left", padx=8)
        ghost_button(r2, "Ativar Proteção do Sistema (C:)", self.enable_protection, width=240).pack(side="left")
        self.rp_label = ctk.CTkLabel(rp, text="", font=T.font(12), text_color=T.MUTED)
        self.rp_label.pack(anchor="w", padx=16, pady=(0, 10))

        hist = Card(self, "Alterações ativas (backup disponível)")
        hist.pack(fill="x", padx=24, pady=6)
        hb = ctk.CTkFrame(hist, fg_color="transparent")
        hb.pack(fill="x", padx=16, pady=(4, 0))
        ghost_button(hb, "Pasta de backups", lambda: _open(BACKUP_DIR), width=150, height=30).pack(side="left")
        ghost_button(hb, "Salvar cópia do backup", lambda: self.app.notify(
            "Backup salvo em " + engine.journal.export_copy()), width=180, height=30).pack(side="left", padx=6)
        ghost_button(hb, "Logs", lambda: _open(LOG_DIR), width=80, height=30).pack(side="left")
        self.hist_box = ctk.CTkFrame(hist, fg_color="transparent")
        self.hist_box.pack(fill="x", padx=12, pady=10)

        pref = Card(self, "Preferências")
        pref.pack(fill="x", padx=24, pady=(6, 24))
        for key, label in (
                ("restore_point_before_changes", "Criar ponto de restauração antes de alterações críticas "
                                                 "(recomendado)"),
                ("close_bg_apps_in_turbo", "TURBO MODE sugere fechar apps de segundo plano"),
                ("stop_services_in_turbo", "TURBO MODE sugere pausar serviços não essenciais"),
                ("relaunch_closed_apps", "Reabrir apps fechados ao desativar o TURBO/fechar o jogo"),
                ("auto_mode", "Modo automático (liberação de RAM + detecção de jogos)")):
            v = ctk.BooleanVar(value=settings.get(key))
            ctk.CTkSwitch(pref, text=label, variable=v, progress_color=T.NEON, font=T.font(13),
                          text_color=T.TEXT, command=lambda k=key, v=v: (settings.set(k, v.get()),
                                                                         self.app.refresh_mode_label())).pack(
                anchor="w", padx=16, pady=4)
        sr = ctk.CTkFrame(pref, fg_color="transparent")
        sr.pack(fill="x", padx=16, pady=6)
        self.thr_label = ctk.CTkLabel(sr, text="", text_color=T.TEXT, font=T.font(13))
        self.thr_label.pack(side="left")
        sl = ctk.CTkSlider(sr, from_=60, to=95, number_of_steps=35, progress_color=T.NEON, button_color=T.NEON,
                           command=self._thr)
        sl.set(settings.get("auto_ram_threshold"))
        sl.pack(side="left", padx=12, fill="x", expand=True)
        self._thr(settings.get("auto_ram_threshold"))
        nk = ctk.CTkFrame(pref, fg_color="transparent")
        nk.pack(fill="x", padx=16, pady=(6, 14))
        ctk.CTkLabel(nk, text="Nunca fechar (exe separados por vírgula):", text_color=T.TEXT).pack(side="left")
        self.never = ctk.CTkEntry(nk, fg_color=T.CARD_HI, border_color=T.BORDER)
        self.never.insert(0, ", ".join(settings.get("never_kill")))
        self.never.pack(side="left", fill="x", expand=True, padx=8)
        ghost_button(nk, "Salvar", self._save_never, width=80, height=30).pack(side="left")

    def _thr(self, v):
        settings.set("auto_ram_threshold", int(v))
        self.thr_label.configure(text=f"Liberar RAM automaticamente acima de {int(v)}%")

    def _save_never(self):
        items = [x.strip().lower() for x in self.never.get().split(",") if x.strip()]
        settings.set("never_kill", items)
        self.app.notify("Lista salva.")

    def on_show(self):
        self.render_history()

    def render_history(self):
        for w in self.hist_box.winfo_children():
            w.destroy()
        groups = [g for g in engine.journal.describe() if g["reg"] or g["actions"] or g["id"].startswith("session")
                  or g["id"].startswith("profile:ultra") or g["id"].startswith("profile:gaming")]
        if not groups:
            ctk.CTkLabel(self.hist_box, text="Nenhuma alteração ativa. Seu Windows está nas configurações originais.",
                         text_color=T.OK, font=T.font(12)).pack(anchor="w", pady=4)
            return
        for g in reversed(groups):
            row = ctk.CTkFrame(self.hist_box, fg_color=T.CARD_HI, corner_radius=8)
            row.pack(fill="x", pady=2)
            when = time.strftime("%d/%m %H:%M", time.localtime(g["time"]))
            ctk.CTkLabel(row, text=f"{g['title']}", font=T.font(12, "bold"), text_color=T.TEXT).pack(
                side="left", padx=10, pady=6)
            ctk.CTkLabel(row, text=f"{CAT_LABEL.get(g['category'], g['category'])} · {when} · "
                         f"{g['reg']} valor(es) de registro · {g['actions']} ação(ões)", text_color=T.MUTED,
                         font=T.font(11)).pack(side="left", padx=6)
            ghost_button(row, "Reverter", lambda gid=g["id"]: self.revert(gid), width=90, height=26).pack(
                side="right", padx=8)

    def revert(self, gid):
        def work():
            if gid == "session:turbo":
                return engine.turbo_off()
            if gid.startswith("profile:ultra_lite") or gid.startswith("profile:gaming_edition"):
                from ...core import ultralite
                return ultralite.deactivate(gid)
            return engine.journal.revert_group(gid)

        def done(errs):
            if errs:
                if any("permissão" in e.lower() or "access" in e.lower() for e in errs):
                    ask_admin(self, "Reverter este item exige administrador.")
                else:
                    messagebox.showwarning("Reverter", "\n".join(errs), parent=self)
            else:
                self.app.notify("Revertido com sucesso.")
            winapi.broadcast_settings_change()
            self.render_history()
        run_bg(self, work, done)

    def restore_all(self):
        if not messagebox.askyesno("RESTAURAR CONFIGURAÇÕES", "Desfazer TODAS as alterações feitas pelo TURBO BOOST "
                                   "PRO e voltar às configurações originais?", parent=self):
            return

        def done(errs):
            self.render_history()
            self.app.refresh_mode_label()
            if errs:
                msg = "Restauração parcial:\n\n" + "\n".join(errs[:15])
                if not winapi.is_admin():
                    msg += "\n\nAlguns itens exigem administrador."
                messagebox.showwarning("Restaurar", msg, parent=self)
            else:
                messagebox.showinfo("Restaurar", "Todas as configurações originais foram restauradas.\nReinicie o "
                                    "Windows para garantir que todos os ajustes voltaram.", parent=self)
        from ...core import ultralite
        run_bg(self, ultralite.restore_windows_original, done)

    def create_rp(self):
        if not winapi.is_admin():
            ask_admin(self, "Criar ponto de restauração exige administrador.")
            return
        self.rp_label.configure(text="Criando ponto de restauração (pode levar 1 minuto)…")
        run_bg(self, restore_point.create, lambda r: self.rp_label.configure(
            text=r[1], text_color=T.OK if r[0] else T.WARN))

    def enable_protection(self):
        if not winapi.is_admin():
            ask_admin(self, "Ativar a Proteção do Sistema exige administrador.")
            return
        run_bg(self, restore_point.enable_protection_c, lambda r: self.rp_label.configure(
            text=r[1], text_color=T.OK if r[0] else T.WARN))
