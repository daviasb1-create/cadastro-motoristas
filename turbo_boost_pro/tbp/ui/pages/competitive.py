"""Aba COMPETITIVO (Etapa 2): análise técnica, Modo CS2, benchmark com FPS/1% low/frametime e testes A/B."""
from __future__ import annotations

import os
import time
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from ...config import settings
from ...core import analysis2 as A, bench, power, stage2, storage, system_mods, ultralite as UL, winapi
from ...core.diagnostics import SEV_COLOR, SEV_LABEL
from ...core.engine import engine
from ...core.tweaks import TWEAKS_BY_ID
from ...utils import fmt_bytes
from .. import theme as T
from ..dialogs import MONO, ask_admin
from ..widgets import Card, ghost_button, page_header, primary_button, run_bg


class CompetitivePage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color=T.BG)
        self.app = app
        self._loaded: set[str] = set()
        page_header(self, "COMPETITIVO · ETAPA 2", "Análise técnica de CPU, RAM, GPU, latência e disco, Modo CS2 e "
                    "benchmark real (FPS médio, 1% low, frametime). Só ajustes com efeito comprovado; medidos antes e "
                    "depois.").pack(anchor="w", padx=24, pady=(20, 6))
        self.tabs = ctk.CTkTabview(self, fg_color=T.PANEL, segmented_button_selected_color=T.NEON_DARK,
                                   segmented_button_selected_hover_color=T.NEON_DIM, segmented_button_fg_color=T.CARD,
                                   segmented_button_unselected_color=T.CARD, text_color=T.TEXT,
                                   command=self._tab_changed)
        self.tabs.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        self.builders = {"Análise": self._build_analysis, "Modo CS2": self._build_cs2,
                         "Benchmark": self._build_bench, "Testes A/B": self._build_ab,
                         "Ajustes rejeitados": self._build_rejected}
        self.frames = {n: self.tabs.add(n) for n in self.builders}
        self._tab_changed()

    def _tab_changed(self):
        name = self.tabs.get()
        if name not in self._loaded:
            self._loaded.add(name)
            self.builders[name](self.frames[name])
        fn = {"Modo CS2": self._refresh_cs2, "Benchmark": self._refresh_bench, "Testes A/B": self._refresh_ab}.get(name)
        if fn:
            fn()

    def on_show(self):
        self._tab_changed()

    def _admin(self, what) -> bool:
        if winapi.is_admin():
            return True
        ask_admin(self, f"{what} exige administrador.")
        return False

    # ================================================================ ANÁLISE
    def _build_analysis(self, tab):
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", pady=4)
        self.an_btn = primary_button(bar, "🔬 ANALISAR CPU · RAM · GPU · LATÊNCIA · DISCO", self._analyze, width=380)
        self.an_btn.pack(side="left")
        self.an_status = ctk.CTkLabel(bar, text="Leva cerca de 40 segundos. Deixe o PC parado durante a análise.",
                                      text_color=T.MUTED)
        self.an_status.pack(side="left", padx=12)
        self.s2_btn = ghost_button(bar, "", self._toggle_stage2, width=220)
        self.s2_btn.pack(side="right")
        self._stage2_label()
        self.an_box = ctk.CTkScrollableFrame(tab, fg_color=T.PANEL)
        self.an_box.pack(fill="both", expand=True, pady=4)

    def _stage2_label(self):
        on = UL.is_active(UL.STAGE2_GID)
        self.s2_btn.configure(text="DESFAZER ETAPA 2" if on else "⚡ APLICAR ETAPA 2",
                              border_color=T.WARN if on else T.NEON, text_color=T.WARN if on else T.NEON)

    def _toggle_stage2(self):
        if UL.is_active(UL.STAGE2_GID):
            if messagebox.askyesno("Etapa 2", "Desfazer as otimizações da Etapa 2?", parent=self):
                run_bg(self, lambda: UL.deactivate(UL.STAGE2_GID), lambda e: (self._stage2_label(),
                       self.app.notify("Etapa 2 desfeita." if not e else "; ".join(e[:3]))))
            return
        if not self._admin("A Etapa 2"):
            return
        self.app.notify("Montando o plano da Etapa 2 (somente itens ainda não aplicados)…")
        self.app.plan_and_run("OTIMIZAÇÃO ETAPA 2", stage2.plan_stage2, after=lambda r: self._stage2_label(),
                              subtitle="Somente otimizações ainda não aplicadas. Recomendado: faça um benchmark do "
                                       "CS2 antes e outro depois (aba Benchmark).")

    def _analyze(self):
        self.an_btn.configure(state="disabled")
        for w in self.an_box.winfo_children():
            w.destroy()
        steps = [("CPU", A.cpu_report), ("Memória RAM", A.ram_report), ("GPU", A.gpu_report),
                 ("Latência e rede", A.latency_report), ("Disco e inicialização", A.disk_report),
                 ("Processos em repouso", A.process_audit)]

        def run_step(i=0):
            if i >= len(steps):
                self.an_btn.configure(state="normal")
                self.an_status.configure(text="Análise concluída.")
                return
            name, fn = steps[i]
            self.an_status.configure(text=f"Analisando {name}… ({i + 1}/{len(steps)})")
            run_bg(self, fn, lambda rep: (self._render_section(name, rep), run_step(i + 1)),
                   lambda e: (self._render_section(name, {"facts": [("Erro", str(e))], "findings": []}),
                              run_step(i + 1)))
        run_step()

    def _render_section(self, name, rep):
        card = Card(self.an_box, name)
        card.pack(fill="x", pady=4, padx=2)
        grid = ctk.CTkFrame(card, fg_color="transparent")
        grid.pack(fill="x", padx=16, pady=(4, 6))
        grid.grid_columnconfigure(1, weight=1)
        for i, (k, v) in enumerate(rep.get("facts", [])):
            ctk.CTkLabel(grid, text=k, font=T.font(12), text_color=T.MUTED, anchor="w").grid(row=i, column=0,
                                                                                             sticky="w", padx=(0, 16))
            ctk.CTkLabel(grid, text=str(v), font=T.font(12, "bold"), text_color=T.TEXT, anchor="w", justify="left",
                         wraplength=760).grid(row=i, column=1, sticky="w")
        if rep.get("rows"):  # auditoria de processos
            lines = [f"{r['name']:<34} {r['cpu']:>5.1f}%  {r['why']}" for r in rep["rows"]]
            ctk.CTkLabel(card, text="\n".join(lines) or "Nenhum processo relevante.", font=(MONO, 11),
                         text_color=T.TEXT, justify="left").pack(anchor="w", padx=16, pady=4)
        for f in rep.get("findings", []):
            col = SEV_COLOR[f.severity]
            row = ctk.CTkFrame(card, fg_color=T.CARD_HI, corner_radius=8)
            row.pack(fill="x", padx=12, pady=2)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=f" {SEV_LABEL[f.severity]} ", font=T.font(9, "bold"), text_color="#000",
                         fg_color=col, corner_radius=6, width=60).grid(row=0, column=0, rowspan=2, padx=8, pady=6)
            ctk.CTkLabel(row, text=f.title, font=T.font(12, "bold"), text_color=T.TEXT, anchor="w").grid(
                row=0, column=1, sticky="w", pady=(6, 0))
            ctk.CTkLabel(row, text=f.detail, font=T.font(11), text_color=T.MUTED, anchor="w", justify="left",
                         wraplength=720).grid(row=1, column=1, sticky="w", pady=(0, 6))
            if f.action:
                primary_button(row, f.action_label or "Corrigir", lambda a=f.action: self._do(a), width=150,
                               height=28).grid(row=0, column=2, rowspan=2, padx=8)
        for vendor, tips in (rep.get("tips") or {}).items():
            ctk.CTkLabel(card, text=f"CONFIGURAÇÕES RECOMENDADAS {vendor} (no painel do driver; o app não altera "
                         "clocks, tensão nem limites de energia)", font=T.font(11, "bold"), text_color=T.NEON).pack(
                anchor="w", padx=16, pady=(8, 0))
            ctk.CTkLabel(card, text="\n".join("• " + t for t in tips), font=T.font(12), text_color=T.TEXT,
                         justify="left").pack(anchor="w", padx=16, pady=(2, 8))
        ctk.CTkFrame(card, height=6, fg_color="transparent").pack()

    def _do(self, action: str):
        j = engine.journal
        if action.startswith("open:"):
            if os.name == "nt":
                os.startfile(action[5:])  # noqa: S606
            return
        if action.startswith("page:"):
            self.app.show(action[5:])
            return
        if action.startswith("tweak:"):
            tid = action[6:]
            self.app.plan_and_run(TWEAKS_BY_ID[tid].title, lambda: engine.plan_tweaks([tid]))
            return
        if not self._admin("Esta correção"):
            return
        fn = {"cpu:competitivo": lambda: power.set_cpu_profile("competitivo", j),
              "cpu:eficiente": lambda: power.set_cpu_profile("eficiente", j),
              "parking:allow": lambda: power.set_core_parking(True, j),
              "pagefile:auto": lambda: system_mods.set_pagefile_auto(j),
              "nic:eee": lambda: " · ".join(system_mods.disable_nic_power_saving(j)),
              "trim:on": lambda: storage.enable_trim(j)}.get(action)
        if fn:
            run_bg(self, fn, lambda m: self.app.notify(str(m)))

    # ================================================================ MODO CS2
    def _build_cs2(self, tab):
        f = ctk.CTkScrollableFrame(tab, fg_color=T.PANEL)
        f.pack(fill="both", expand=True)
        top = Card(f)
        top.pack(fill="x", pady=4)
        r = ctk.CTkFrame(top, fg_color="transparent")
        r.pack(fill="x", padx=16, pady=14)
        txt = ctk.CTkFrame(r, fg_color="transparent")
        txt.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(txt, text="🎯 MODO CS2", font=T.font(22, "bold", True), text_color=T.NEON).pack(anchor="w")
        ctk.CTkLabel(txt, text="Antes de abrir: plano de energia TURBO, serviços de fundo pausados (busca, telemetria, "
                     "SysMain), apps desnecessários fechados e timer apenas se aprovado no teste A/B. Ao fechar o "
                     "CS2 tudo volta sozinho.", font=T.font(12), text_color=T.MUTED, wraplength=640,
                     justify="left").pack(anchor="w")
        self.cs2_play = primary_button(r, "▶ JOGAR CS2 OTIMIZADO", self._play, width=240, height=50)
        self.cs2_play.pack(side="right")
        self.cs2_session_lbl = ctk.CTkLabel(top, text="", font=T.font(12, "bold"))
        self.cs2_session_lbl.pack(anchor="w", padx=16)
        self.auto_var = ctk.BooleanVar(value=settings.get("cs2_auto_session", False))
        ctk.CTkSwitch(top, text="Ativar o Modo CS2 automaticamente sempre que o cs2.exe abrir (sem fechar apps)",
                      variable=self.auto_var, progress_color=T.NEON, text_color=T.TEXT,
                      command=lambda: settings.set("cs2_auto_session", self.auto_var.get())).pack(
            anchor="w", padx=16, pady=(4, 14))

        st = Card(f, "Perfil do cs2.exe")
        st.pack(fill="x", pady=4)
        self.cs2_info = ctk.CTkLabel(st, text="Procurando CS2…", font=T.font(12), text_color=T.TEXT, justify="left")
        self.cs2_info.pack(anchor="w", padx=16, pady=4)
        b = ctk.CTkFrame(st, fg_color="transparent")
        b.pack(fill="x", padx=16, pady=(4, 6))
        primary_button(b, "Prioridade Alta + GPU dedicada", lambda: self._cs2_apply(), width=230).pack(side="left")
        self.fso_btn = ghost_button(b, "", self._toggle_fso, width=260)
        self.fso_btn.pack(side="left", padx=8)
        ghost_button(b, "Reverter perfil CS2", lambda: run_bg(self, lambda: engine.journal.revert_group("game:cs2"),
                                                               lambda e: self._refresh_cs2()), width=160,
                     border_color=T.BAD, text_color=T.BAD).pack(side="left")
        ctk.CTkLabel(st, text="Tela cheia exclusiva: no Windows 11 o modo 'flip independente' já tem a mesma latência "
                     "na maioria dos PCs. Ative, rode o benchmark e compare (Testes A/B › Tela cheia).",
                     font=T.font(11), text_color=T.MUTED, wraplength=900, justify="left").pack(anchor="w", padx=16,
                                                                                              pady=(0, 12))
        cpu = Card(f, "Perfil de CPU (plano TURBO BOOST PRO)")
        cpu.pack(fill="x", pady=4)
        self.cpu_lbl = ctk.CTkLabel(cpu, text="", font=T.font(12), text_color=T.TEXT, justify="left")
        self.cpu_lbl.pack(anchor="w", padx=16, pady=4)
        cb = ctk.CTkFrame(cpu, fg_color="transparent")
        cb.pack(fill="x", padx=16, pady=(4, 14))
        for key, p in power.CPU_PROFILES.items():
            ghost_button(cb, p["label"], lambda k=key: self._cpu(k), width=200).pack(side="left", padx=(0, 8))
        ghost_button(cb, "Permitir estacionamento", lambda: self._parking(True), width=200).pack(side="left", padx=8)
        ghost_button(cb, "Desativar estacionamento", lambda: self._parking(False), width=200).pack(side="left")
        for key, p in power.CPU_PROFILES.items():
            ctk.CTkLabel(cpu, text=f"{p['label']}: {p['desc']}", font=T.font(11), text_color=T.MUTED,
                         wraplength=900, justify="left").pack(anchor="w", padx=16)
        ctk.CTkFrame(cpu, height=10, fg_color="transparent").pack()

    def _refresh_cs2(self):
        on = stage2.cs2_session_active()
        self.cs2_session_lbl.configure(text="● Modo CS2 ATIVO (restaura sozinho ao fechar o jogo)" if on else
                                       "○ Modo CS2 inativo", text_color=T.OK if on else T.MUTED)
        self.cs2_play.configure(text="■ ENCERRAR MODO CS2" if on else "▶ JOGAR CS2 OTIMIZADO")

        def done(st):
            if not st.get("found"):
                self.cs2_info.configure(text="CS2 não encontrado nas bibliotecas da Steam.", text_color=T.MUTED)
                self.fso_btn.configure(text="Tela cheia exclusiva: N/D", state="disabled")
                return
            ok = lambda v: "✔" if v else "✘"  # noqa: E731
            self.cs2_info.configure(text=f"{st['exe']}\n{ok(st['priority'])} Prioridade Alta (CPU/E-S)   "
                                    f"{ok(st['gpu'])} GPU de alto desempenho   {ok(st.get('fso_off'))} Tela cheia "
                                    f"exclusiva   {ok(st['autoexec'])} autoexec.cfg", text_color=T.TEXT)
            self.fso_btn.configure(state="normal", text="Voltar ao padrão (FSO ligado)" if st.get("fso_off") else
                                   "Testar tela cheia exclusiva")
            self._fso_on = bool(st.get("fso_off"))
        run_bg(self, system_mods.cs2_status, done)
        prof = settings.get("cpu_profile")
        sens = " · Ryzen X3D de 2 CCDs: mantenha o estacionamento PERMITIDO" if power.parking_sensitive_cpu() else ""
        self.cpu_lbl.configure(text=f"Perfil atual: {power.CPU_PROFILES.get(prof, {}).get('label', 'não definido')}"
                                    f"{sens}")

    def _play(self):
        if stage2.cs2_session_active():
            run_bg(self, stage2.end_cs2_session, lambda e: self._refresh_cs2())
            return
        if not winapi.is_admin() and not messagebox.askyesno(
                "Modo CS2", "Sem administrador os serviços não serão pausados. Continuar?", parent=self):
            return
        run_bg(self, stage2.start_cs2_session, lambda m: self._refresh_cs2())

    def _cs2_apply(self):
        if self._admin("O perfil do CS2"):
            self.app.plan_and_run("Perfil do CS2", lambda: UL.plan_cs2(False), after=lambda r: self._refresh_cs2())

    def _toggle_fso(self):
        run_bg(self, lambda: system_mods.cs2_fso(not getattr(self, "_fso_on", False), engine.journal),
               lambda m: (self.app.notify(m), self._refresh_cs2()))

    def _cpu(self, key):
        if self._admin("Alterar o perfil de CPU"):
            run_bg(self, lambda: power.set_cpu_profile(key, engine.journal),
                   lambda m: (self.app.notify(m), self._refresh_cs2()))

    def _parking(self, allow):
        if self._admin("Alterar o estacionamento de núcleos"):
            run_bg(self, lambda: power.set_core_parking(allow, engine.journal), self.app.notify)

    # ================================================================ BENCHMARK
    def _build_bench(self, tab):
        cfg = ctk.CTkFrame(tab, fg_color="transparent")
        cfg.pack(fill="x", pady=4)
        ctk.CTkLabel(cfg, text="Processo:", text_color=T.MUTED).pack(side="left")
        self.b_proc = ctk.CTkEntry(cfg, width=120, fg_color=T.CARD_HI, border_color=T.BORDER)
        self.b_proc.insert(0, "cs2.exe")
        self.b_proc.pack(side="left", padx=6)
        ctk.CTkLabel(cfg, text="Duração:", text_color=T.MUTED).pack(side="left")
        self.b_secs = ctk.CTkComboBox(cfg, values=["30", "60", "90", "120"], width=80, fg_color=T.CARD_HI,
                                      border_color=T.BORDER, button_color=T.NEON_DARK)
        self.b_secs.set(str(settings.get("bench_seconds", 60)))
        self.b_secs.pack(side="left", padx=6)
        ctk.CTkLabel(cfg, text="Nome:", text_color=T.MUTED).pack(side="left")
        self.b_label = ctk.CTkEntry(cfg, width=200, fg_color=T.CARD_HI, border_color=T.BORDER,
                                    placeholder_text="ex.: antes da etapa 2")
        self.b_label.pack(side="left", padx=6)
        self.b_btn = primary_button(cfg, "● INICIAR CAPTURA (10 s)", self._bench_start, width=220)
        self.b_btn.pack(side="left", padx=6)
        ghost_button(cfg, "PresentMon…", self._pick_pm, width=110).pack(side="right")
        self.b_status = ctk.CTkLabel(tab, text="", font=T.font(12), text_color=T.MUTED, justify="left",
                                     wraplength=1000)
        self.b_status.pack(anchor="w")
        body = ctk.CTkFrame(tab, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)
        self.b_list = ctk.CTkScrollableFrame(body, fg_color=T.PANEL, width=330)
        self.b_list.grid(row=0, column=0, sticky="nsw", padx=(0, 6))
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        self.b_chart = tk.Canvas(right, height=170, bg=T.CARD, highlightthickness=0)
        self.b_chart.pack(fill="x", pady=(4, 6))
        self.b_result = ctk.CTkScrollableFrame(right, fg_color=T.CARD)
        self.b_result.pack(fill="both", expand=True)
        self.b_sel: list[int] = []

    def _pick_pm(self):
        p = filedialog.askopenfilename(title="Selecione o PresentMon.exe", filetypes=[("Executável", "*.exe")],
                                       parent=self)
        if p:
            settings.set("presentmon_path", p)
            self._refresh_bench()

    def _refresh_bench(self):
        pm = bench.presentmon_path()
        hint = ("Como medir: abra o CS2 › Workshop › mapa de benchmark de FPS (ou uma partida contra bots no mesmo "
                "mapa/posição) › clique em INICIAR, volte ao jogo em até 10 s e não mexa até terminar. Compare "
                "sempre o mesmo cenário.")
        self.b_status.configure(text=(f"PresentMon: {pm}" if pm else "⚠ PresentMon não encontrado: use o botão "
                                      "'PresentMon…'") + "\n" + hint, text_color=T.MUTED if pm else T.WARN)
        for w in self.b_list.winfo_children():
            w.destroy()
        runs = list(reversed(bench.load()))
        if not runs:
            ctk.CTkLabel(self.b_list, text="Nenhuma captura ainda.", text_color=T.SUBTLE).pack(pady=10)
        for r in runs:
            sel = r["id"] in self.b_sel
            f = ctk.CTkFrame(self.b_list, fg_color=T.NEON_DARK if sel else T.CARD, corner_radius=8)
            f.pack(fill="x", pady=2)
            t = time.strftime("%d/%m %H:%M", time.localtime(r["time"]))
            lbl = ctk.CTkLabel(f, text=f"{r['label']}  ·  {t}\n{r['fps_avg']:.0f} FPS · 1% low {r['fps_1low']:.0f} · "
                               f"{r['ft_avg']:.2f} ms", font=T.font(11, "bold"), text_color=T.TEXT, justify="left",
                               anchor="w")
            lbl.pack(side="left", padx=8, pady=4, fill="x", expand=True)
            for w in (f, lbl):
                w.bind("<Button-1>", lambda e, i=r["id"]: self._select(i))
            ctk.CTkButton(f, text="✕", width=24, height=24, fg_color="transparent", text_color=T.BAD,
                          hover_color=T.CARD_HI, command=lambda i=r["id"]: (bench.delete(i), self._refresh_bench())
                          ).pack(side="right", padx=4)
        if not self.b_sel and runs:
            self.b_sel = [runs[0]["id"]] if len(runs) == 1 else [runs[1]["id"], runs[0]["id"]]
            self._refresh_bench()
            return
        self._render_result()

    def _select(self, rid):
        if rid in self.b_sel:
            self.b_sel.remove(rid)
        else:
            self.b_sel = (self.b_sel + [rid])[-2:]
        self._refresh_bench()

    def _bench_start(self):
        if not self._admin("O benchmark (eventos ETW)"):
            return
        proc = self.b_proc.get().strip() or "cs2.exe"
        secs = int(self.b_secs.get() or 60)
        settings.set("bench_seconds", secs)
        label = self.b_label.get().strip() or f"Captura {time.strftime('%H:%M')}"
        self.b_btn.configure(state="disabled")

        def countdown(n=10):
            if n > 0:
                self.b_status.configure(text=f"Volte ao jogo! Captura começa em {n} s…", text_color=T.WARN)
                self.after(1000, lambda: countdown(n - 1))
                return

            def prog(p, t):
                self.after(0, lambda: self.b_status.configure(text=t, text_color=T.NEON))

            def done(r):
                self.b_btn.configure(state="normal")
                self.b_sel = (self.b_sel + [r["id"]])[-2:]
                self.app.notify(f"Benchmark: {r['fps_avg']:.0f} FPS médio, 1% low {r['fps_1low']:.0f}")
                self._refresh_bench()

            def err(e):
                self.b_btn.configure(state="normal")
                self.b_status.configure(text=f"⚠ {e}", text_color=T.BAD)
            run_bg(self, lambda: bench.capture(proc, secs, label, self.app.monitor, prog), done, err)
        countdown()

    def _render_result(self):
        for w in self.b_result.winfo_children():
            w.destroy()
        runs = {r["id"]: r for r in bench.load()}
        sel = [runs[i] for i in self.b_sel if i in runs]
        self._draw_chart(sel)
        if not sel:
            return
        if len(sel) == 1:
            r = sel[0]
            rows = [(lab, r.get(k)) for k, lab, _h in bench.METRICS if r.get(k) is not None]
            for i, (lab, v) in enumerate(rows):
                ctk.CTkLabel(self.b_result, text=lab, text_color=T.MUTED, font=T.font(12)).grid(row=i, column=0,
                                                                                                sticky="w", padx=10)
                ctk.CTkLabel(self.b_result, text=f"{v}", text_color=T.TEXT, font=T.font(13, "bold")).grid(
                    row=i, column=1, sticky="w", padx=10)
            self._extra(r, len(rows))
            return
        a, b = sel
        rows = bench.compare(a, b)
        for c, h in enumerate(("Métrica", a["label"][:22], b["label"][:22], "Diferença", "")):
            ctk.CTkLabel(self.b_result, text=h, font=T.font(12, "bold"), text_color=T.NEON).grid(row=0, column=c,
                                                                                                sticky="w", padx=10)
        for i, r in enumerate(rows, start=1):
            col = T.OK if r["verdict"] == "melhor" else T.BAD if r["verdict"] == "pior" else T.MUTED
            for c, v in enumerate((r["label"], r["a"], r["b"], f"{r['pct']:+.1f}%", r["verdict"])):
                ctk.CTkLabel(self.b_result, text=str(v), font=T.font(12, "bold" if c == 0 else "normal"),
                             text_color=col if c >= 3 else T.TEXT).grid(row=i, column=c, sticky="w", padx=10)
        v = bench.verdict(rows)
        ctk.CTkLabel(self.b_result, text=v, font=T.font(14, "bold", True),
                     text_color=T.OK if "GANHO" in v or "Ganho" in v else T.BAD if "PIOROU" in v else T.WARN).grid(
            row=len(rows) + 1, column=0, columnspan=5, sticky="w", padx=10, pady=(10, 2))
        diff = [k for k in set(a.get("config", {})) | set(b.get("config", {}))
                if a.get("config", {}).get(k) != b.get("config", {}).get(k)]
        ctk.CTkLabel(self.b_result, text="Configurações diferentes entre as capturas: " + (", ".join(diff) or
                     "nenhuma registrada"), font=T.font(11), text_color=T.MUTED).grid(row=len(rows) + 2, column=0,
                                                                                   columnspan=5, sticky="w", padx=10)
        self._extra(b, len(rows) + 3)

    def _extra(self, r, row):
        info = []
        if r.get("bound") and r.get("cpu_busy_ms") is not None:
            tip = ("CPU/RAM/serviços de fundo fazem diferença" if r["bound"] == "CPU" else
                   "reduza resolução/MSAA/sombras para ganhar FPS")
            info.append(f"Limitado por: {r['bound']} (CPU {r['cpu_busy_ms']} ms · GPU {r['gpu_busy_ms']} ms por quadro)"
                        f" → {tip}")
        if r.get("present_mode"):
            pm = r["present_mode"]
            ok = "Independent Flip" in pm or "Hardware" in pm
            info.append(f"Modo de apresentação: {pm} " + ("✔ (latência mínima)" if ok else
                                                          "⚠ composto pelo Windows: +latência; use tela cheia"))
        if r.get("latency_ms"):
            info.append(f"Latência ({r.get('latency_kind')}): {r['latency_ms']} ms")
        if r.get("competitors"):
            info.append("Processos concorrentes (pico de CPU): " + ", ".join(f"{n} {c}%" for n, c in r["competitors"]))
        if r.get("ram_used"):
            info.append(f"RAM em uso durante o jogo: {fmt_bytes(r['ram_used'])}")
        ctk.CTkLabel(self.b_result, text="\n".join(info), font=T.font(11), text_color=T.TEXT, justify="left",
                     wraplength=700).grid(row=row, column=0, columnspan=5, sticky="w", padx=10, pady=8)

    def _draw_chart(self, runs):
        c = self.b_chart
        c.delete("all")
        c.update_idletasks()
        w, h = max(200, c.winfo_width()), 170
        c.create_text(10, 10, anchor="w", text="Frametime (ms) — picos = travadas", fill=T.MUTED,
                      font=(T.FAMILY, 9, "bold"))
        series = [r.get("series") or [] for r in runs]
        allv = [v for s in series for v in s]
        if not allv:
            return
        top = max(sorted(allv)[int(len(allv) * 0.995) - 1] * 1.2, 1)
        for i, (r, s, color) in enumerate(zip(runs, series, (T.MUTED, T.NEON))):
            if len(s) < 2:
                continue
            color = T.NEON if len(runs) == 1 else color
            step = w / (len(s) - 1)
            pts = []
            for k, v in enumerate(s):
                pts += [k * step, h - 6 - (h - 26) * min(v, top) / top]
            c.create_line(*pts, fill=color, width=1)
            c.create_text(w - 10, 12 + i * 14, anchor="e", text=f"● {r['label'][:30]}", fill=color,
                          font=(T.FAMILY, 9, "bold"))

    # ================================================================ TESTES A/B
    def _build_ab(self, tab):
        f = ctk.CTkScrollableFrame(tab, fg_color=T.PANEL)
        f.pack(fill="both", expand=True)
        t = Card(f, "Timer de 0,5 ms: decide com números")
        t.pack(fill="x", pady=4)
        self.ab_timer_info = ctk.CTkLabel(t, text="", font=T.font(12), text_color=T.TEXT, justify="left",
                                          wraplength=950)
        self.ab_timer_info.pack(anchor="w", padx=16, pady=4)
        tb = ctk.CTkFrame(t, fg_color="transparent")
        tb.pack(fill="x", padx=16, pady=(4, 6))
        self.ab_timer_btn = primary_button(tb, "Rodar teste A/B (4 × 20 s, CS2 aberto)", self._ab_timer, width=300)
        self.ab_timer_btn.pack(side="left")
        ghost_button(tb, "Ativar pedidos globais (reinício)", lambda: self.app.plan_and_run(
            "Pedidos globais de timer", lambda: engine.plan_tweaks(["global_timer"])), width=250).pack(side="left",
                                                                                                    padx=8)
        ctk.CTkLabel(tb, text="Uso do timer:", text_color=T.MUTED).pack(side="left", padx=(12, 4))
        self.timer_mode = ctk.CTkSegmentedButton(tb, values=["auto", "on", "off"], selected_color=T.NEON_DARK,
                                                 command=lambda v: (settings.set("timer_mode", v), self._refresh_ab()))
        self.timer_mode.pack(side="left")
        ctk.CTkLabel(t, text="auto = usa 0,5 ms só se o teste A/B aprovar · on = sempre durante jogos · off = nunca. "
                     "Nunca é permanente: termina ao fechar o app ou o jogo.", font=T.font(11), text_color=T.MUTED,
                     wraplength=950, justify="left").pack(anchor="w", padx=16, pady=(0, 12))
        for key, title, steps in (
            ("hags", "Agendamento de GPU por hardware (HAGS)",
             "1) Benchmark com o estado atual  2) Alternar HAGS  3) REINICIAR  4) Benchmark no mesmo cenário"),
            ("cs2_fso_off", "Tela cheia exclusiva do CS2 (FSO)",
             "1) Benchmark  2) Alternar em Modo CS2 › Testar tela cheia exclusiva  3) Reabrir o CS2  4) Benchmark"),
            ("cpu_profile", "Perfil de CPU (Competitivo x Eficiente)",
             "1) Benchmark  2) Trocar o perfil em Modo CS2  3) Benchmark"),
        ):
            c = Card(f, title)
            c.pack(fill="x", pady=4)
            ctk.CTkLabel(c, text=steps, font=T.font(12), text_color=T.MUTED).pack(anchor="w", padx=16, pady=2)
            row = ctk.CTkFrame(c, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=(2, 12))
            if key == "hags":
                ghost_button(row, "Alternar HAGS", self._toggle_hags, width=150).pack(side="left", padx=(0, 8))
            lbl = ctk.CTkLabel(row, text="", font=T.font(12, "bold"), text_color=T.TEXT, justify="left",
                               wraplength=800)
            lbl.pack(side="left")
            setattr(self, f"ab_{key}_lbl", lbl)

    def _refresh_ab(self):
        self.timer_mode.set(settings.get("timer_mode", "auto"))
        tr = winapi.query_timer_resolution()
        cfg = bench.config_snapshot() if os.name == "nt" else {"global_timer": False, "hags": None}
        ab = settings.get("timer_ab_result")
        lines = [f"Timer atual: {tr['current']:.3f} ms" if tr else "Timer: N/D",
                 "Pedidos globais: " + ("ATIVOS (o timer do app vale para o jogo)" if cfg.get("global_timer") else
                                        "padrão do Windows 11 (o timer do app NÃO afeta o jogo; o resultado esperado "
                                        "é 'sem diferença')")]
        if ab:
            s = ab["summary"]
            lines.append(f"Último teste: padrão {s['off']['fps_avg']} FPS / 1% low {s['off']['fps_1low']}  →  0,5 ms "
                         f"{s['on']['fps_avg']} FPS / 1% low {s['on']['fps_1low']}  ({ab['gain_1low_pct']:+.1f}% no 1% "
                         f"low) → {'RECOMENDADO' if ab['recommend'] else 'NÃO recomendado'}")
        self.ab_timer_info.configure(text="\n".join(lines))
        for key in ("hags", "cs2_fso_off", "cpu_profile"):
            pair = bench.last_pair_by(key)
            lbl = getattr(self, f"ab_{key}_lbl")
            if not pair:
                lbl.configure(text="Aguardando duas capturas com estados diferentes.", text_color=T.MUTED)
                continue
            a, b = pair
            rows = bench.compare(a, b)
            get = {r["key"]: r for r in rows}
            lbl.configure(text=f"{key}={a['config'].get(key)}: {a['fps_avg']:.0f} FPS / 1% low {a['fps_1low']:.0f}  →  "
                               f"{key}={b['config'].get(key)}: {b['fps_avg']:.0f} FPS / 1% low {b['fps_1low']:.0f} "
                               f"({get.get('fps_1low', {}).get('pct', 0):+.1f}%) · {bench.verdict(rows)}",
                          text_color=T.TEXT)
        if cfg.get("hags") is not None:
            self.ab_hags_lbl.configure(text=f"HAGS agora: {'ativado' if cfg['hags'] else 'desativado'} · " +
                                       self.ab_hags_lbl.cget("text"))

    def _toggle_hags(self):
        t = TWEAKS_BY_ID["hags"]
        if engine.journal.has_group(t.gid):
            self.app.plan_and_run("Reverter HAGS", lambda: engine.plan_tweaks(["hags"], revert=True),
                                  after=lambda r: self._refresh_ab())
        else:
            self.app.plan_and_run("Ativar HAGS", lambda: engine.plan_tweaks(["hags"]), after=lambda r: self._refresh_ab())

    def _ab_timer(self):
        if not self._admin("O teste A/B"):
            return
        self.ab_timer_btn.configure(state="disabled")
        self.app.notify("Teste A/B do timer: volte ao CS2 em 10 s e não mexa por ~90 s.")

        def prog(p, t):
            self.after(0, lambda: self.ab_timer_info.configure(text=t))

        def done(r):
            self.ab_timer_btn.configure(state="normal")
            self._refresh_ab()

        def err(e):
            self.ab_timer_btn.configure(state="normal")
            self.ab_timer_info.configure(text=f"⚠ {e}")
        self.after(10000, lambda: run_bg(self, lambda: bench.ab_test_timer("cs2.exe", 20, 2, self.app.monitor, prog),
                                         done, err))

    # ================================================================ REJEITADOS
    def _build_rejected(self, tab):
        f = ctk.CTkScrollableFrame(tab, fg_color=T.PANEL)
        f.pack(fill="both", expand=True)
        ctk.CTkLabel(f, text="Ajustes populares na internet que foram AVALIADOS e NÃO são aplicados, e por quê:",
                     font=T.font(13, "bold"), text_color=T.NEON).pack(anchor="w", pady=6)
        for name, why in A.REJECTED:
            c = ctk.CTkFrame(f, fg_color=T.CARD, corner_radius=8)
            c.pack(fill="x", pady=2)
            ctk.CTkLabel(c, text="✘ " + name, font=T.font(12, "bold"), text_color=T.WARN).pack(anchor="w", padx=12,
                                                                                               pady=(6, 0))
            ctk.CTkLabel(c, text=why, font=T.font(11), text_color=T.MUTED, wraplength=950, justify="left").pack(
                anchor="w", padx=12, pady=(0, 6))
