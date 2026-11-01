"""Limpeza avançada: análise com tamanho antes de excluir + arquivos grandes (vão para a Lixeira)."""
from __future__ import annotations

import os
import subprocess
from tkinter import messagebox

import customtkinter as ctk

from ...core import cleaner, winapi
from ...utils import fmt_bytes
from .. import theme as T
from ..widgets import ghost_button, page_header, primary_button, run_bg


class CleanerPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color=T.BG)
        self.app = app
        self.results: dict[str, cleaner.ScanResult] = {}
        page_header(self, "Limpeza Avançada", "Analise primeiro: você vê exatamente quanto será liberado antes "
                    "de excluir. Arquivos do sistema nunca são tocados.").pack(anchor="w", padx=24, pady=(20, 6))
        tabs = ctk.CTkTabview(self, fg_color=T.PANEL, segmented_button_selected_color=T.NEON_DARK,
                              segmented_button_selected_hover_color=T.NEON_DIM, segmented_button_fg_color=T.CARD,
                              segmented_button_unselected_color=T.CARD, text_color=T.TEXT)
        tabs.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        self._build_junk(tabs.add("Arquivos desnecessários"))
        self._build_large(tabs.add("Arquivos grandes"))

    # ================================================================ lixo
    def _build_junk(self, tab):
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", padx=6, pady=6)
        self.total_label = ctk.CTkLabel(bar, text="Clique em ANALISAR para calcular o espaço recuperável.",
                                        font=T.font(15, "bold", True), text_color=T.TEXT)
        self.total_label.pack(side="left")
        self.clean_btn = primary_button(bar, "🧹 LIMPAR SELECIONADOS", self.clean, width=210)
        self.clean_btn.pack(side="right", padx=4)
        self.clean_btn.configure(state="disabled")
        self.scan_btn = ghost_button(bar, "🔍 ANALISAR", self.scan, width=140)
        self.scan_btn.pack(side="right", padx=4)
        self.progress = ctk.CTkProgressBar(tab, progress_color=T.NEON, fg_color=T.TRACK, height=6)
        self.progress.pack(fill="x", padx=8)
        self.progress.set(0)
        body = ctk.CTkScrollableFrame(tab, fg_color=T.PANEL)
        body.pack(fill="both", expand=True, pady=6)
        self.vars, self.size_labels = {}, {}
        admin = winapi.is_admin()
        group = None
        for c in cleaner.CATEGORIES:
            if c.group != group:
                group = c.group
                ctk.CTkLabel(body, text=group.upper(), font=T.font(11, "bold", True), text_color=T.NEON).pack(
                    anchor="w", padx=8, pady=(10, 2))
            row = ctk.CTkFrame(body, fg_color=T.CARD, corner_radius=10, border_width=1, border_color=T.BORDER)
            row.pack(fill="x", padx=4, pady=3)
            row.grid_columnconfigure(1, weight=1)
            v = ctk.BooleanVar(value=c.default and (admin or not c.admin))
            self.vars[c.id] = v
            cb = ctk.CTkCheckBox(row, text="", variable=v, width=24, fg_color=T.NEON, border_color=T.NEON_DIM,
                                 command=self._update_total)
            cb.grid(row=0, column=0, rowspan=2, padx=(12, 4))
            if c.admin and not admin:
                cb.configure(state="disabled")
            title = c.name + ("   [ADMIN]" if c.admin else "")
            ctk.CTkLabel(row, text=title, font=T.font(13, "bold"), text_color=T.TEXT, anchor="w").grid(
                row=0, column=1, sticky="w", pady=(8, 0))
            desc = c.description + (f"  ⓘ {c.note}" if c.note else "")
            ctk.CTkLabel(row, text=desc, font=T.font(11), text_color=T.MUTED, anchor="w", justify="left",
                         wraplength=720).grid(row=1, column=1, sticky="w", pady=(0, 8))
            lab = ctk.CTkLabel(row, text="-", font=T.font(14, "bold", True), text_color=T.SUBTLE, width=110)
            lab.grid(row=0, column=2, rowspan=2, padx=12)
            self.size_labels[c.id] = lab
        if not admin:
            ctk.CTkLabel(body, text="Itens [ADMIN] exigem executar como administrador (botão na barra lateral).",
                         text_color=T.WARN, font=T.font(11)).pack(anchor="w", padx=8, pady=8)

    def _update_total(self):
        total = sum(self.results[k].size for k, v in self.vars.items() if v.get() and k in self.results)
        if self.results:
            self.total_label.configure(text=f"{fmt_bytes(total)} podem ser liberados nos itens selecionados",
                                       text_color=T.NEON)

    def scan(self):
        self.scan_btn.configure(state="disabled")
        self.clean_btn.configure(state="disabled")
        cats = cleaner.CATEGORIES
        state = {"i": 0}

        def work():
            out = {}
            for i, c in enumerate(cats):
                state["i"] = i
                out[c.id] = cleaner.scan(c)
            return out

        def poll():
            if self.scan_btn.cget("state") == "disabled":
                self.progress.set(state["i"] / len(cats))
                self.total_label.configure(text=f"Analisando: {cats[state['i']].name}…")
                self.after(150, poll)

        def done(res):
            self.results = res
            self.scan_btn.configure(state="normal")
            self.clean_btn.configure(state="normal")
            self.progress.set(1)
            for k, r in res.items():
                c = cleaner.CATEGORIES_BY_ID[k]
                if c.id == "dism":
                    txt = "após limpar"
                else:
                    txt = fmt_bytes(r.size) if r.size else "0 B"
                col = T.NEON if r.size > 50 * 1024 ** 2 else T.TEXT if r.size else T.SUBTLE
                self.size_labels[k].configure(text=txt, text_color=col)
            self._update_total()
        poll()
        run_bg(self, work, done)

    def clean(self):
        sel = [cleaner.CATEGORIES_BY_ID[k] for k, v in self.vars.items() if v.get()]
        if not sel:
            return
        total = sum(self.results.get(c.id, cleaner.ScanResult()).size for c in sel)
        lines = "\n".join(f"• {c.name}: {fmt_bytes(self.results.get(c.id, cleaner.ScanResult()).size)}"
                          for c in sel)
        if not messagebox.askyesno("Confirmar limpeza", f"Serão excluídos aproximadamente {fmt_bytes(total)}:\n\n"
                                   f"{lines}\n\nArquivos em uso serão mantidos. Continuar?", parent=self):
            return
        self.clean_btn.configure(state="disabled")
        self.scan_btn.configure(state="disabled")

        def work():
            freed, msgs = 0, []
            for i, c in enumerate(sel):
                self.after(0, lambda i=i, c=c: (self.progress.set(i / len(sel)),
                                                self.total_label.configure(text=f"Limpando: {c.name}…")))
                f, m = cleaner.clean(c, self.results.get(c.id))
                freed += f
                msgs.append(m)
            return freed, msgs

        def done(r):
            freed, msgs = r
            self.progress.set(1)
            self.scan_btn.configure(state="normal")
            self.total_label.configure(text=f"✔ {fmt_bytes(freed)} liberados!", text_color=T.OK)
            self.results = {}
            for lab in self.size_labels.values():
                lab.configure(text="-", text_color=T.SUBTLE)
            messagebox.showinfo("Limpeza concluída", f"{fmt_bytes(freed)} liberados.\n\n" + "\n".join(msgs),
                                parent=self)
        run_bg(self, work, done)

    # ================================================================ arquivos grandes
    def _build_large(self, tab):
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", padx=6, pady=6)
        ctk.CTkLabel(bar, text="Tamanho mínimo (MB):", text_color=T.MUTED).pack(side="left")
        self.min_mb = ctk.CTkEntry(bar, width=70, fg_color=T.CARD, border_color=T.BORDER)
        self.min_mb.insert(0, "200")
        self.min_mb.pack(side="left", padx=6)
        ghost_button(bar, "🔍 Procurar", self.find_large, width=120).pack(side="left", padx=6)
        primary_button(bar, "🗑 Enviar selecionados para a Lixeira", self.trash_large, width=280).pack(side="right")
        self.large_info = ctk.CTkLabel(tab, text="Procura em Downloads, Área de Trabalho, Documentos, Vídeos, "
                                       "Músicas e Imagens. Instaladores/compactados antigos em Downloads vêm "
                                       "marcados como provavelmente desnecessários.", text_color=T.MUTED,
                                       font=T.font(12), wraplength=900, justify="left")
        self.large_info.pack(anchor="w", padx=8)
        self.large_box = ctk.CTkScrollableFrame(tab, fg_color=T.PANEL)
        self.large_box.pack(fill="both", expand=True, pady=6)
        self.large_vars = []

    def find_large(self):
        try:
            mb = max(10, int(self.min_mb.get()))
        except ValueError:
            mb = 200
        self.large_info.configure(text="Procurando…")

        def done(files):
            for w in self.large_box.winfo_children():
                w.destroy()
            self.large_vars = []
            total = sum(f["size"] for f in files)
            self.large_info.configure(text=f"{len(files)} arquivo(s) · {fmt_bytes(total)}. Nada é excluído "
                                           "definitivamente: os arquivos vão para a Lixeira.")
            for f in files:
                row = ctk.CTkFrame(self.large_box, fg_color=T.CARD, corner_radius=8)
                row.pack(fill="x", pady=2, padx=2)
                v = ctk.BooleanVar(value=False)
                self.large_vars.append((v, f))
                ctk.CTkCheckBox(row, text="", variable=v, width=24, fg_color=T.NEON).pack(side="left", padx=8)
                tag = "  ⚑ provavelmente desnecessário" if f["unneeded"] else ""
                ctk.CTkLabel(row, text=f"{os.path.basename(f['path'])}{tag}", font=T.font(12, "bold"),
                             text_color=T.WARN if f["unneeded"] else T.TEXT, anchor="w").pack(side="left")
                ctk.CTkLabel(row, text=f"{fmt_bytes(f['size'])}  ·  {f['age_days']} dias sem uso",
                             text_color=T.MUTED, font=T.font(11)).pack(side="right", padx=10)
                ghost_button(row, "Abrir pasta", lambda p=f["path"]: self._reveal(p), width=90, height=24).pack(
                    side="right")
        run_bg(self, lambda: cleaner.find_large_files(mb), done)

    def _reveal(self, path):
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", path])

    def trash_large(self):
        sel = [f for v, f in self.large_vars if v.get()]
        if not sel:
            return
        total = sum(f["size"] for f in sel)
        if not messagebox.askyesno("Lixeira", f"Enviar {len(sel)} arquivo(s) ({fmt_bytes(total)}) para a Lixeira?\n"
                                   "Você pode restaurá-los pela Lixeira do Windows.", parent=self):
            return

        def done(r):
            freed, errors = r
            msg = f"{fmt_bytes(freed)} enviados para a Lixeira."
            if errors:
                msg += "\n\nErros:\n" + "\n".join(errors[:10])
            messagebox.showinfo("Lixeira", msg, parent=self)
            self.find_large()
        run_bg(self, lambda: cleaner.send_to_recycle_bin([f["path"] for f in sel]), done)
