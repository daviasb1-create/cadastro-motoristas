"""Gerenciador de desempenho: processos, inicialização, serviços e recomendações."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import customtkinter as ctk

from ...core import processes, services, startup, winapi
from ...core.engine import engine
from ...utils import fmt_bytes
from .. import theme as T
from ..dialogs import ask_admin
from ..widgets import ghost_button, page_header, primary_button, run_bg


def style_tree():
    st = ttk.Style()
    st.theme_use("default")
    st.configure("TBP.Treeview", background=T.CARD, fieldbackground=T.CARD, foreground=T.TEXT, rowheight=28,
                 borderwidth=0, font=(T.FAMILY, 10))
    st.configure("TBP.Treeview.Heading", background=T.CARD_HI, foreground=T.NEON, relief="flat",
                 font=(T.FAMILY, 10, "bold"))
    st.map("TBP.Treeview", background=[("selected", T.NEON_DARK)], foreground=[("selected", T.TEXT)])
    st.map("TBP.Treeview.Heading", background=[("active", T.BORDER)])


class PerformancePage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color=T.BG)
        self.app = app
        style_tree()
        page_header(self, "Gerenciador de Desempenho", "Processos pesados, programas de inicialização e serviços "
                    "otimizáveis.").pack(anchor="w", padx=24, pady=(20, 6))
        self.tabs = ctk.CTkTabview(self, fg_color=T.PANEL, segmented_button_selected_color=T.NEON_DARK,
                                   segmented_button_selected_hover_color=T.NEON_DIM,
                                   segmented_button_fg_color=T.CARD, segmented_button_unselected_color=T.CARD,
                                   text_color=T.TEXT, command=self._tab_changed)
        self.tabs.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        self._build_processes(self.tabs.add("Processos"))
        self._build_startup(self.tabs.add("Inicialização"))
        self._build_services(self.tabs.add("Serviços"))
        self._loaded = set()

    def _tab_changed(self):
        name = self.tabs.get()
        if name == "Inicialização" and name not in self._loaded:
            self.load_startup()
        if name == "Serviços" and name not in self._loaded:
            self.load_services()

    def on_show(self):
        self._tab_changed()

    # ================================================================ processos
    def _build_processes(self, tab):
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", pady=4)
        self.sort_by = ctk.CTkSegmentedButton(bar, values=["CPU", "Memória"], selected_color=T.NEON_DARK,
                                              unselected_color=T.CARD, command=lambda v: self._refresh_procs())
        self.sort_by.set("CPU")
        self.sort_by.pack(side="left")
        self.prio = ctk.CTkComboBox(bar, values=[k for k in processes.PRIORITIES if k != "Tempo real"], width=160,
                                    fg_color=T.CARD_HI, border_color=T.BORDER, button_color=T.NEON_DARK)
        self.prio.set("Alta")
        primary_button(bar, "Definir prioridade", self._set_prio, width=150).pack(side="right", padx=4)
        self.prio.pack(side="right", padx=4)
        ghost_button(bar, "Encerrar processo", self._kill, width=150, border_color=T.BAD, text_color=T.BAD).pack(
            side="right", padx=4)
        frame = tk.Frame(tab, bg=T.CARD)
        frame.pack(fill="both", expand=True, pady=4)
        cols = ("name", "pid", "cpu", "mem", "info")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", style="TBP.Treeview")
        for c, label, w in (("name", "Processo", 240), ("pid", "PID", 70), ("cpu", "CPU", 80),
                            ("mem", "Memória", 110), ("info", "Observação", 360)):
            self.tree.heading(c, text=label)
            self.tree.column(c, width=w, anchor="w" if c in ("name", "info") else "center")
        self.tree.tag_configure("hot", foreground=T.WARN)
        self.tree.tag_configure("prot", foreground=T.SUBTLE)
        self.tree.tag_configure("bg", foreground=T.NEON)
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        ctk.CTkLabel(tab, text="Azul: app de segundo plano dispensável · Laranja: consumo alto · Cinza: protegido "
                     "pelo sistema (não pode ser encerrado).", text_color=T.MUTED, font=T.font(11)).pack(anchor="w")
        self._proc_job = None
        self._refresh_procs()

    def _refresh_procs(self):
        if self._proc_job:
            self.after_cancel(self._proc_job)
        if self.app.current == "performance" and self.tabs.get() == "Processos":
            by = "cpu" if self.sort_by.get() == "CPU" else "mem"

            def done(procs):
                sel = self.tree.selection()
                sel_pid = self.tree.item(sel[0])["values"][1] if sel else None
                self.tree.delete(*self.tree.get_children())
                for p in procs:
                    name = p["name"].lower()
                    info = processes.BACKGROUND_APPS.get(name, "")
                    tag = "prot" if p["protected"] else "bg" if info else (
                        "hot" if p["cpu"] > 20 or p["mem"] > 1024 ** 3 else "")
                    if p["protected"]:
                        info = "Processo do sistema"
                    iid = self.tree.insert("", "end", values=(p["name"], p["pid"], f"{p['cpu']:.1f}%",
                                                              fmt_bytes(p["mem"]), info), tags=(tag,))
                    if p["pid"] == sel_pid:
                        self.tree.selection_set(iid)
            run_bg(self, lambda: processes.top_processes(by, 40), done)
        self._proc_job = self.after(2500, self._refresh_procs)

    def _selected_pid(self):
        sel = self.tree.selection()
        return int(self.tree.item(sel[0])["values"][1]) if sel else None

    def _kill(self):
        pid = self._selected_pid()
        if pid and messagebox.askyesno("Encerrar", "Encerrar este processo? Dados não salvos nele serão perdidos.",
                                       parent=self):
            ok, msg = processes.kill_pid(pid)
            self.app.notify(msg, "info" if ok else "warn")

    def _set_prio(self):
        pid = self._selected_pid()
        if pid:
            ok, msg = processes.set_priority(pid, self.prio.get())
            self.app.notify(msg, "info" if ok else "warn")

    # ================================================================ inicialização
    def _build_startup(self, tab):
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", pady=4)
        self.startup_info = ctk.CTkLabel(bar, text="", font=T.font(13, "bold"), text_color=T.TEXT)
        self.startup_info.pack(side="left")
        primary_button(bar, "Desativar recomendados", self._disable_recommended, width=200).pack(side="right")
        ghost_button(bar, "Atualizar", self.load_startup, width=100).pack(side="right", padx=6)
        self.startup_box = ctk.CTkScrollableFrame(tab, fg_color=T.PANEL)
        self.startup_box.pack(fill="both", expand=True)

    def load_startup(self):
        self._loaded.add("Inicialização")
        run_bg(self, startup.list_entries, self._render_startup)

    def _render_startup(self, entries):
        self.startup_entries = entries
        for w in self.startup_box.winfo_children():
            w.destroy()
        on = sum(e["enabled"] for e in entries)
        self.startup_info.configure(text=f"{on} de {len(entries)} programas iniciam com o Windows")
        admin = winapi.is_admin()
        rec_txt = {"desativar": ("RECOMENDADO DESATIVAR", T.WARN), "manter": ("MANTER (driver/sistema)", T.OK),
                   "neutro": ("", T.MUTED)}
        for e in entries:
            row = ctk.CTkFrame(self.startup_box, fg_color=T.CARD, corner_radius=10, border_width=1,
                               border_color=T.BORDER)
            row.pack(fill="x", pady=3, padx=2)
            row.grid_columnconfigure(0, weight=1)
            head = ctk.CTkFrame(row, fg_color="transparent")
            head.grid(row=0, column=0, sticky="w", padx=12, pady=(8, 0))
            ctk.CTkLabel(head, text=e["name"], font=T.font(13, "bold"), text_color=T.TEXT).pack(side="left")
            txt, col = rec_txt[e["rec"]]
            if txt:
                ctk.CTkLabel(head, text=f" {txt} ", font=T.font(9, "bold"), text_color=col,
                             fg_color=T.blend(T.CARD, col, 0.2), corner_radius=6).pack(side="left", padx=8)
            ctk.CTkLabel(row, text=f"{e['source']} · {e['command'][:110]}", font=T.font(11), text_color=T.MUTED,
                         anchor="w").grid(row=1, column=0, sticky="w", padx=12, pady=(0, 8))
            v = ctk.BooleanVar(value=e["enabled"])
            sw = ctk.CTkSwitch(row, text="", variable=v, progress_color=T.NEON, width=50,
                               command=lambda e=e, v=v: self._toggle_startup(e, v))
            sw.grid(row=0, column=1, rowspan=2, padx=12)
            if e["admin"] and not admin:
                sw.configure(state="disabled")

    def _toggle_startup(self, e, v):
        try:
            msg = startup.set_enabled(e, v.get(), engine.journal)
            self.app.notify(msg)
        except PermissionError:
            v.set(not v.get())
            ask_admin(self, "Este item pertence a todos os usuários e exige administrador.")

    def _disable_recommended(self):
        entries = [e for e in getattr(self, "startup_entries", []) if e["enabled"] and e["rec"] == "desativar"
                   and (not e["admin"] or winapi.is_admin())]
        if not entries:
            messagebox.showinfo("Inicialização", "Nenhum item recomendado para desativar.", parent=self)
            return
        names = "\n".join(f"• {e['name']}" for e in entries)
        if messagebox.askyesno("Inicialização", f"Desativar a inicialização automática de:\n\n{names}\n\n"
                               "Os programas continuam instalados e podem ser reativados aqui.", parent=self):
            for e in entries:
                startup.set_enabled(e, False, engine.journal)
            self.load_startup()

    # ================================================================ serviços
    def _build_services(self, tab):
        ctk.CTkLabel(tab, text="Windows Defender, Firewall e Windows Update são protegidos e nunca alterados. "
                     "'Pausar' vale até reiniciar; 'Manual' faz o serviço iniciar só quando algum app precisar "
                     "(revertível).", text_color=T.MUTED, font=T.font(12), wraplength=900, justify="left").pack(
            anchor="w", pady=4)
        self.services_box = ctk.CTkScrollableFrame(tab, fg_color=T.PANEL)
        self.services_box.pack(fill="both", expand=True)

    def load_services(self):
        self._loaded.add("Serviços")
        run_bg(self, services.catalog_status, self._render_services)

    def _render_services(self, items):
        for w in self.services_box.winfo_children():
            w.destroy()
        if not items:
            ctk.CTkLabel(self.services_box, text="Nenhum serviço do catálogo encontrado.", text_color=T.SUBTLE).pack(
                pady=20)
        for s in items:
            row = ctk.CTkFrame(self.services_box, fg_color=T.CARD, corner_radius=10, border_width=1,
                               border_color=T.BORDER)
            row.pack(fill="x", pady=3, padx=2)
            row.grid_columnconfigure(0, weight=1)
            run_col = T.OK if s["status"] == "running" else T.SUBTLE
            ctk.CTkLabel(row, text=f"{s['label']}  ({s['name']})", font=T.font(13, "bold"), text_color=T.TEXT,
                         anchor="w").grid(row=0, column=0, sticky="w", padx=12, pady=(8, 0))
            ctk.CTkLabel(row, text=f"● {'Em execução' if s['status'] == 'running' else 'Parado'} · Inicialização: "
                         f"{s['start_label']}", text_color=run_col, font=T.font(11), anchor="w").grid(
                row=1, column=0, sticky="w", padx=12)
            ctk.CTkLabel(row, text=s["desc"], text_color=T.MUTED, font=T.font(11), anchor="w", justify="left",
                         wraplength=640).grid(row=2, column=0, sticky="w", padx=12, pady=(0, 8))
            btns = ctk.CTkFrame(row, fg_color="transparent")
            btns.grid(row=0, column=1, rowspan=3, padx=10)
            if s["status"] == "running":
                ghost_button(btns, "Pausar", lambda n=s["name"]: self._svc("stop", n), width=90, height=28).pack(
                    pady=2)
            if engine.journal.has_group(f"service:{s['name']}"):
                ghost_button(btns, "Restaurar", lambda n=s["name"]: self._svc("restore", n), width=90,
                             height=28, border_color=T.OK, text_color=T.OK).pack(pady=2)
            elif s["rec"] == "manual" and s["start"] in ("auto", "delayed-auto"):
                primary_button(btns, "Manual", lambda n=s["name"]: self._svc("manual", n), width=90,
                               height=28).pack(pady=2)

    def _svc(self, op, name):
        if not winapi.is_admin():
            ask_admin(self, "Alterar serviços exige administrador.")
            return

        def work():
            if op == "stop":
                return services.stop_temporarily(name, engine.journal, "session:manual")[1]
            if op == "manual":
                return services.set_manual(name, engine.journal)[1]
            errs = services.restore_start(name, engine.journal)
            return "Restaurado." if not errs else "; ".join(errs)
        run_bg(self, work, lambda msg: (self.app.notify(msg), self.load_services()))
