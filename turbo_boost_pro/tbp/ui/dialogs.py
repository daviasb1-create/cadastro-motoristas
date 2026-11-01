"""Diálogos: prévia do que será alterado, progresso, resultado e solicitação de administrador."""
from __future__ import annotations

import sys
from tkinter import messagebox

import customtkinter as ctk

from ..config import settings
from ..core import winapi
from ..core.engine import Action, ExecResult, engine
from . import theme as T
from .widgets import ghost_button, primary_button, run_bg


MONO = "Consolas" if sys.platform == "win32" else "DejaVu Sans Mono"


class _Modal(ctk.CTkToplevel):
    def __init__(self, parent, title, w=820, h=640):
        super().__init__(parent)
        self.title(title)
        self.configure(fg_color=T.PANEL)
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        self.geometry(f"{w}x{h}+{px + max(0, (pw - w) // 2)}+{py + max(0, (ph - h) // 2)}")
        self.transient(parent)
        self.after(120, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
        except Exception:
            pass


def ask_admin(parent, reason: str) -> bool:
    """Pergunta se deve reiniciar como administrador. Retorna True se o app vai reiniciar."""
    if winapi.is_admin():
        return False
    if messagebox.askyesno("Permissão de administrador",
                           f"{reason}\n\nDeseja reabrir o TURBO BOOST PRO como administrador agora?\n"
                           "(Suas configurações e backups são mantidos.)", parent=parent):
        if winapi.relaunch_as_admin():
            parent.winfo_toplevel().shutdown()
            return True
        messagebox.showwarning("TURBO BOOST PRO", "A elevação foi cancelada.", parent=parent)
    return False


class PreviewDialog(_Modal):
    """Mostra EXATAMENTE o que será alterado; o usuário escolhe item a item antes de executar."""

    def __init__(self, parent, title: str, actions: list[Action], on_confirm, subtitle: str = ""):
        super().__init__(parent, f"Prévia · {title}")
        self.actions, self.on_confirm = actions, on_confirm
        self.vars = []
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=22, pady=(18, 6))
        ctk.CTkLabel(head, text=title, font=T.font(22, "bold", True), text_color=T.NEON).pack(anchor="w")
        ctk.CTkLabel(head, text=subtitle or "Revise as alterações abaixo. Desmarque o que não quiser aplicar. "
                     "Tudo pode ser desfeito em Segurança › RESTAURAR CONFIGURAÇÕES.",
                     font=T.font(12), text_color=T.MUTED, wraplength=760, justify="left").pack(anchor="w")
        admin = winapi.is_admin()
        n_admin = sum(1 for a in actions if a.admin)
        if n_admin and not admin:
            bar = ctk.CTkFrame(self, fg_color=T.blend(T.PANEL, T.WARN, 0.15), corner_radius=10)
            bar.pack(fill="x", padx=22, pady=6)
            ctk.CTkLabel(bar, text=f"⚠ {n_admin} item(ns) exigem administrador e serão ignorados nesta execução.",
                         text_color=T.WARN, font=T.font(12, "bold")).pack(side="left", padx=12, pady=8)
            ghost_button(bar, "Reiniciar como admin", lambda: (self.destroy(), ask_admin(parent, "Itens marcados "
                         "como ADMIN alteram configurações do sistema.")), width=170,
                         border_color=T.WARN, text_color=T.WARN).pack(side="right", padx=10, pady=6)
        body = ctk.CTkScrollableFrame(self, fg_color=T.PANEL)
        body.pack(fill="both", expand=True, padx=14, pady=4)
        section = None
        if not actions:
            ctk.CTkLabel(body, text="Nada a fazer: tudo já está otimizado. ✔", font=T.font(15, "bold"),
                         text_color=T.OK).pack(pady=40)
        for a in actions:
            if a.section != section:
                section = a.section
                ctk.CTkLabel(body, text=section.upper(), font=T.font(11, "bold", True),
                             text_color=T.NEON).pack(anchor="w", padx=8, pady=(12, 2))
            card = ctk.CTkFrame(body, fg_color=T.CARD, corner_radius=10, border_width=1, border_color=T.BORDER)
            card.pack(fill="x", padx=4, pady=3)
            v = ctk.BooleanVar(value=a.selected and (admin or not a.admin))
            self.vars.append(v)
            cb = ctk.CTkCheckBox(card, text=a.title + ("   [ADMIN]" if a.admin else ""), variable=v,
                                 font=T.font(13, "bold"), text_color=T.TEXT, fg_color=T.NEON,
                                 hover_color=T.NEON_DIM, border_color=T.NEON_DIM, command=self._update)
            cb.pack(anchor="w", padx=10, pady=(8, 2))
            if a.locked or (a.admin and not admin):
                cb.configure(state="disabled")
            if a.details:
                ctk.CTkLabel(card, text="\n".join(a.details), font=(MONO, 11), text_color=T.MUTED, anchor="w",
                             justify="left", wraplength=700).pack(anchor="w", padx=40, pady=(0, 2))
            if a.note:
                ctk.CTkLabel(card, text="ⓘ " + a.note, font=T.font(11), text_color=T.WARN, wraplength=720,
                             justify="left").pack(anchor="w", padx=34)
            ctk.CTkFrame(card, height=6, fg_color="transparent").pack()
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=22, pady=14)
        primary_button(foot, "EXECUTAR", self._go, width=160).pack(side="right")
        ghost_button(foot, "Cancelar", self.destroy, width=120).pack(side="right", padx=10)
        self.summary = ctk.CTkLabel(foot, text="", font=T.font(12), text_color=T.MUTED, wraplength=470,
                                    justify="left", anchor="w")
        self.summary.pack(side="left", fill="x", expand=True)
        self._update()

    def _update(self):
        n = sum(v.get() for v in self.vars)
        crit = any(v.get() and a.critical for v, a in zip(self.vars, self.actions))
        rp = settings.get("restore_point_before_changes") and winapi.is_admin() and crit
        self.summary.configure(text=f"{n} ação(ões) selecionada(s)" +
                               (" · ponto de restauração será criado" if rp else "") +
                               (" · backup do registro será salvo" if crit else ""))

    def _go(self):
        for v, a in zip(self.vars, self.actions):
            a.selected = bool(v.get())
        self.destroy()
        self.on_confirm(self.actions)


class ProgressDialog(_Modal):
    def __init__(self, parent, title):
        super().__init__(parent, title, 520, 180)
        self.protocol("WM_DELETE_WINDOW", lambda: None)
        ctk.CTkLabel(self, text=title, font=T.font(17, "bold", True), text_color=T.NEON).pack(pady=(22, 8))
        self.bar = ctk.CTkProgressBar(self, progress_color=T.NEON, fg_color=T.TRACK, height=10, width=440)
        self.bar.pack(pady=6)
        self.bar.set(0)
        self.label = ctk.CTkLabel(self, text="Preparando…", font=T.font(12), text_color=T.MUTED, wraplength=460)
        self.label.pack(pady=6)

    def update_progress(self, p, text):
        self.after(0, lambda: (self.bar.set(p), self.label.configure(text=text)))


class ResultDialog(_Modal):
    def __init__(self, parent, title, res: ExecResult):
        super().__init__(parent, title, 720, 520)
        ok = not res.errors
        ctk.CTkLabel(self, text=("✔ " if ok else "⚠ ") + title, font=T.font(20, "bold", True),
                     text_color=T.OK if ok else T.WARN).pack(anchor="w", padx=22, pady=(18, 6))
        box = ctk.CTkTextbox(self, fg_color=T.CARD, text_color=T.TEXT, font=T.font(12), wrap="word")
        box.pack(fill="both", expand=True, padx=20, pady=6)
        for m in res.messages:
            box.insert("end", m + "\n")
        if res.skipped_admin:
            box.insert("end", "\nIgnorados (precisam de administrador):\n")
            for m in res.skipped_admin:
                box.insert("end", "  • " + m + "\n")
        if res.errors:
            box.insert("end", "\nAvisos/erros:\n")
            for m in res.errors:
                box.insert("end", "  • " + m + "\n")
        if any("Requer reinício" in m or "HAGS" in m for m in res.messages):
            box.insert("end", "\nAlgumas alterações só terão efeito completo após reiniciar o Windows.\n")
        box.configure(state="disabled")
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=20, pady=12)
        primary_button(foot, "OK", self.destroy, width=120).pack(side="right")
        if res.skipped_admin and not winapi.is_admin():
            ghost_button(foot, "Reiniciar como admin", lambda: (self.destroy(), ask_admin(parent, "Itens foram "
                         "ignorados por falta de permissão.")), width=180).pack(side="right", padx=10)


def run_plan(parent, title: str, actions: list[Action], after=None, subtitle: str = ""):
    """Fluxo padrão: prévia -> progresso -> resultado -> callback."""
    def confirm(acts):
        if not any(a.selected for a in acts):
            return
        prog = ProgressDialog(parent, title)

        def done(res):
            prog.destroy()
            ResultDialog(parent, title, res)
            if after:
                after(res)
        run_bg(parent, lambda: engine.execute(acts, prog.update_progress), done,
               lambda e: (prog.destroy(), messagebox.showerror("Erro", str(e), parent=parent)))
    PreviewDialog(parent, title, actions, confirm, subtitle)
