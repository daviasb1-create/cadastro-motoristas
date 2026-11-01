"""ANALISAR MEU PC: diagnóstico com recomendações acionáveis e relatório HTML."""
from __future__ import annotations

import os
import webbrowser

import customtkinter as ctk

from ...core import diagnostics, memory, services, winapi
from ...core.engine import engine
from ...utils import fmt_bytes
from .. import theme as T
from ..dialogs import ask_admin
from ..widgets import Card, Gauge, ghost_button, page_header, primary_button, run_bg


class DiagnosticsPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color=T.BG)
        self.app = app
        self.report = None
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=24, pady=(20, 6))
        page_header(top, "Diagnóstico Automático", "Identifica gargalos de hardware e software, programas pesados e "
                    "configurações que prejudicam o desempenho.").pack(side="left")
        self.btn = primary_button(top, "🔍 ANALISAR MEU PC", self.analyze, width=220, height=46)
        self.btn.pack(side="right")
        self.export_btn = ghost_button(top, "📄 Exportar relatório", self.export, width=180)
        self.export_btn.pack(side="right", padx=8)
        self.export_btn.configure(state="disabled")

        mid = ctk.CTkFrame(self, fg_color="transparent")
        mid.pack(fill="x", padx=18)
        mid.grid_columnconfigure(1, weight=1)
        sc = Card(mid, "Nota do diagnóstico")
        sc.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.gauge = Gauge(sc, "SAÚDE", size=180, unit="/100")
        self.gauge.color_fn = T.score_color
        self.gauge.set(None)
        self.gauge.pack(padx=20, pady=(4, 0))
        self.status = ctk.CTkLabel(sc, text="Aguardando análise", font=T.font(12), text_color=T.MUTED)
        self.status.pack(pady=(0, 12))
        self.progress = ctk.CTkProgressBar(sc, progress_color=T.NEON, fg_color=T.TRACK, height=6, width=200)
        self.progress.set(0)
        self.progress.pack(pady=(0, 12))
        hw = Card(mid, "Hardware e uso medido")
        hw.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)
        self.hw_text = ctk.CTkLabel(hw, text="-", font=T.font(13), text_color=T.TEXT, justify="left", anchor="w",
                                    wraplength=760)
        self.hw_text.pack(anchor="w", padx=16, pady=10)
        ctk.CTkLabel(self, text="RECOMENDAÇÕES PERSONALIZADAS", font=T.font(12, "bold", True),
                     text_color=T.NEON).pack(anchor="w", padx=26, pady=(8, 2))
        self.list = ctk.CTkScrollableFrame(self, fg_color=T.PANEL)
        self.list.pack(fill="both", expand=True, padx=24, pady=(0, 16))

    def analyze(self):
        self.btn.configure(state="disabled", text="ANALISANDO…")
        for w in self.list.winfo_children():
            w.destroy()

        def prog(p, text):
            self.after(0, lambda: (self.progress.set(p), self.status.configure(text=text)))
        run_bg(self, lambda: diagnostics.analyze(self.app.monitor, prog), self._render,
               lambda e: (self.btn.configure(state="normal", text="🔍 ANALISAR MEU PC"),
                          self.status.configure(text=f"Erro: {e}")))

    def _render(self, rep):
        self.report = rep
        self.btn.configure(state="normal", text="🔍 ANALISAR NOVAMENTE")
        self.export_btn.configure(state="normal")
        self.gauge.set(rep.score)
        n = sum(1 for f in rep.findings if f.severity in ("critico", "alto", "medio"))
        self.status.configure(text=f"{n} ponto(s) de melhoria encontrados")
        h, s = rep.hardware, rep.samples
        f = lambda v, u="%": "-" if v is None else f"{v:.0f}{u}"  # noqa: E731
        gpus = ", ".join(g.get("Name", "") for g in h.get("gpus", [])) or h.get("gpu_name") or "-"
        vols = "  ".join(f"{v['letter']}: {v['kind']} ({fmt_bytes(v['free'])} livres)" for v in h.get("volumes", []))
        self.hw_text.configure(text=(
            f"CPU: {h.get('cpu_name', '-')} · {h.get('cores')} núcleos / {h.get('threads')} threads\n"
            f"GPU: {gpus}\n"
            f"RAM: {fmt_bytes(h.get('ram_total', 0))} · {h.get('ram_modules') or '?'} módulo(s) · "
            f"{h.get('ram_speed') or '?'} MT/s\n"
            f"Discos: {vols or '-'}\n"
            f"Uso medido → CPU {f(s.get('cpu'))} · GPU {f(s.get('gpu'))} · RAM {f(s.get('ram'))} · "
            f"Disco {f(s.get('disk'))} · Temp. CPU {f(s.get('cpu_temp'), ' °C')}\n"
            f"Gargalo atual: {rep.bottleneck or 'nenhum'}"))
        for fd in rep.findings:
            col = diagnostics.SEV_COLOR[fd.severity]
            row = ctk.CTkFrame(self.list, fg_color=T.CARD, corner_radius=10, border_width=1,
                               border_color=T.blend(T.CARD, col, 0.4))
            row.pack(fill="x", pady=3, padx=2)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=f" {diagnostics.SEV_LABEL[fd.severity]} ", font=T.font(10, "bold"),
                         text_color="#000000", fg_color=col, corner_radius=6, width=70).grid(
                row=0, column=0, rowspan=2, padx=12, pady=10)
            ctk.CTkLabel(row, text=f"{fd.title}", font=T.font(13, "bold"), text_color=T.TEXT, anchor="w").grid(
                row=0, column=1, sticky="w", pady=(8, 0))
            ctk.CTkLabel(row, text=f"{fd.area} · {fd.detail}", font=T.font(11), text_color=T.MUTED, anchor="w",
                         justify="left", wraplength=700).grid(row=1, column=1, sticky="w", pady=(0, 8))
            if fd.action:
                primary_button(row, fd.action_label or "Corrigir", lambda a=fd.action: self.fix(a), width=130,
                               height=30).grid(row=0, column=2, rowspan=2, padx=12)
        procs = ctk.CTkFrame(self.list, fg_color=T.CARD, corner_radius=10)
        procs.pack(fill="x", pady=(10, 3), padx=2)
        ctk.CTkLabel(procs, text="PROGRAMAS MAIS PESADOS AGORA", font=T.font(11, "bold", True),
                     text_color=T.NEON).pack(anchor="w", padx=12, pady=(8, 2))
        lines = [f"{p['name']:<32} RAM {fmt_bytes(p['mem']):>10}   CPU {p['cpu']:5.1f}%" for p in rep.top_ram[:8]]
        ctk.CTkLabel(procs, text="\n".join(lines), font=("Consolas", 12), text_color=T.TEXT, justify="left").pack(
            anchor="w", padx=12, pady=(0, 10))

    def fix(self, action: str):
        app = self.app
        if action.startswith("tweak:"):
            tid = action.split(":", 1)[1]
            app.plan_and_run("Aplicar recomendação", lambda: engine.plan_tweaks([tid]))
        elif action == "power":
            app.plan_and_run("Plano de energia TURBO", lambda: engine._power_action())
        elif action == "ram":
            run_bg(self, lambda: memory.optimize_ram(deep=True),
                   lambda r: app.notify(f"RAM: {fmt_bytes(r['freed'])} liberados. {r['message']}"))
        elif action == "turbo":
            app.show("dashboard")
            app.pages["dashboard"].toggle_turbo()
        elif action.startswith("page:"):
            app.show(action.split(":", 1)[1])
        elif action.startswith("service:"):
            if not winapi.is_admin():
                ask_admin(self, "Alterar serviços exige administrador.")
                return
            name = action.split(":", 1)[1]
            run_bg(self, lambda: services.set_manual(name, engine.journal)[1], app.notify)

    def export(self):
        if self.report:
            path = diagnostics.export_html(self.report)
            self.app.notify(f"Relatório salvo em {path}")
            try:
                webbrowser.open("file://" + os.path.abspath(path))
            except Exception:
                pass
