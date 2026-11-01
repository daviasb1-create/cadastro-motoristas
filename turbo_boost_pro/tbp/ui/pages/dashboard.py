"""Painel: monitoramento em tempo real, índice de desempenho, TURBO MODE e modos."""
from __future__ import annotations

import time
from tkinter import messagebox

import customtkinter as ctk
import psutil

from ...core import memory
from ...core.engine import MODE_NAMES, engine
from ...core.monitor import score_label
from ...utils import fmt_bytes, fmt_rate
from .. import theme as T
from ..widgets import Card, Gauge, Sparkline, StatTile, TurboButton, ghost_button, page_header

MODE_KEYS = {v: k for k, v in MODE_NAMES.items()}
MODE_ORDER = ["Automático", "Gamer", "Máximo Desempenho", "Equilibrado"]
MODE_DESC = {
    "Automático": "Otimiza sozinho: libera RAM sob pressão e dá boost aos jogos que você abrir.",
    "Gamer": "Máximo desempenho + todas as otimizações de jogos + timer 0,5 ms + detecção de jogos.",
    "Máximo Desempenho": "Plano de energia TURBO, CPU sem economia e Windows mais responsivo.",
    "Equilibrado": "Volta ao plano de energia original e desativa sessões TURBO/jogo.",
}


class DashboardPage(ctk.CTkScrollableFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color=T.BG)
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 10))
        page_header(hdr, "Painel de Desempenho", "Monitoramento em tempo real e otimização com um clique.").pack(
            side="left")
        self.cpu_name = ctk.CTkLabel(hdr, text="", font=T.font(12), text_color=T.MUTED, justify="right")
        self.cpu_name.pack(side="right")

        # ------------------------------------------------ linha 1: índice + turbo + modos
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=1, column=0, sticky="ew", padx=18)
        top.grid_columnconfigure((0, 1, 2), weight=1, uniform="top")

        sc = Card(top, "Índice de desempenho")
        sc.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.score_gauge = Gauge(sc, "AGORA", size=200, unit="/100")
        self.score_gauge.color_fn = lambda v: T.score_color(v)
        self.score_gauge.pack(pady=(6, 0))
        self.score_label = ctk.CTkLabel(sc, text="", font=T.font(18, "bold", True), text_color=T.NEON)
        self.score_label.pack()
        self.score_hint = ctk.CTkLabel(sc, text="", font=T.font(11), text_color=T.MUTED, wraplength=260)
        self.score_hint.pack(pady=(0, 12))

        tc = Card(top, "Otimização completa")
        tc.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)
        self.turbo = TurboButton(tc, self.toggle_turbo, size=230)
        self.turbo.pack(pady=(4, 2))
        self.turbo_info = ctk.CTkLabel(tc, text="", font=T.font(11), text_color=T.MUTED, wraplength=280)
        self.turbo_info.pack(pady=(0, 12))

        mc = Card(top, "Modo de operação")
        mc.grid(row=0, column=2, sticky="nsew", padx=6, pady=6)
        grid = ctk.CTkFrame(mc, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=(10, 4))
        grid.grid_columnconfigure((0, 1), weight=1)
        self.mode_buttons = {}
        icons = {"Automático": "🤖", "Gamer": "🎮", "Máximo Desempenho": "🚀", "Equilibrado": "⚖"}
        for i, label in enumerate(MODE_ORDER):
            b = ctk.CTkButton(grid, text=f"{icons[label]} {label}", height=34, corner_radius=8,
                              font=T.font(12, "bold"), fg_color=T.CARD_HI, hover_color=T.BORDER,
                              text_color=T.TEXT, border_width=1, border_color=T.BORDER,
                              command=lambda l=label: self.change_mode(l))
            b.grid(row=i // 2, column=i % 2, sticky="ew", padx=3, pady=3)
            self.mode_buttons[label] = b
        self.mode_desc = ctk.CTkLabel(mc, text="", font=T.font(12), text_color=T.MUTED, wraplength=300,
                                      justify="left")
        self.mode_desc.pack(anchor="w", padx=16, pady=4)
        qa = ctk.CTkFrame(mc, fg_color="transparent")
        qa.pack(fill="x", padx=14, pady=(10, 12))
        qa.grid_columnconfigure((0, 1), weight=1)
        ghost_button(qa, "🧠 Liberar RAM", self.free_ram, width=10).grid(row=0, column=0, sticky="ew", padx=3, pady=3)
        ghost_button(qa, "🔍 Analisar meu PC", lambda: app.show("diagnostics"), width=10).grid(
            row=0, column=1, sticky="ew", padx=3, pady=3)
        ghost_button(qa, "🧹 Limpeza", lambda: app.show("cleaner"), width=10).grid(row=1, column=0, sticky="ew",
                                                                                   padx=3, pady=3)
        ghost_button(qa, "↺ Desfazer tudo", lambda: app.show("security"), width=10, border_color=T.BAD,
                     text_color=T.BAD).grid(row=1, column=1, sticky="ew", padx=3, pady=3)

        # ------------------------------------------------ linha 2: medidores
        gauges = Card(self, "Uso em tempo real")
        gauges.grid(row=2, column=0, sticky="ew", padx=24, pady=6)
        gr = ctk.CTkFrame(gauges, fg_color="transparent")
        gr.pack(fill="x", padx=10, pady=(4, 12))
        gr.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self.g = {}
        self.g_sub = {}
        for i, (key, label) in enumerate((("cpu", "CPU"), ("gpu", "GPU"), ("ram", "RAM"), ("disk", "DISCO"))):
            f = ctk.CTkFrame(gr, fg_color="transparent")
            f.grid(row=0, column=i, padx=6)
            self.g[key] = Gauge(f, label, size=170)
            self.g[key].pack()
            self.g_sub[key] = ctk.CTkLabel(f, text="", font=T.font(11), text_color=T.MUTED, wraplength=200)
            self.g_sub[key].pack()

        # ------------------------------------------------ linha 3: tiles
        tiles = ctk.CTkFrame(self, fg_color="transparent")
        tiles.grid(row=3, column=0, sticky="ew", padx=18, pady=0)
        tiles.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="t")
        self.t_cpu_temp = StatTile(tiles, "Temp. CPU", "🌡")
        self.t_gpu_temp = StatTile(tiles, "Temp. GPU", "🌡")
        self.t_net = StatTile(tiles, "Rede", "⇅")
        self.t_sys = StatTile(tiles, "Sistema", "⏱")
        for i, t in enumerate((self.t_cpu_temp, self.t_gpu_temp, self.t_net, self.t_sys)):
            t.grid(row=0, column=i, sticky="ew", padx=6, pady=6)

        # ------------------------------------------------ linha 4: gráfico
        ch = Card(self, "Histórico (60 s)")
        ch.grid(row=4, column=0, sticky="ew", padx=24, pady=(6, 24))
        self.chart = Sparkline(ch, height=150, series=[("CPU", T.NEON), ("RAM", "#a66bff"), ("GPU", T.OK),
                                                        ("Disco", T.WARN)])
        self.chart.pack(fill="x", padx=14, pady=(6, 14))
        self._sync_state()

    # ---------------------------------------------------------------- estado
    def _sync_state(self):
        active = engine.turbo_active
        self.turbo.set_state(active)
        if active:
            since = engine.journal.group("session:turbo")["meta"].get("since", time.time())
            self.turbo_info.configure(text=f"Ativo há {int((time.time() - since) // 60)} min. Clique para "
                                           "desfazer as otimizações da sessão.")
        else:
            self.turbo_info.configure(text="Energia máxima, RAM liberada, apps e serviços de fundo pausados e "
                                           "otimizações de jogos. Você verá tudo antes de aplicar.")
        label = MODE_NAMES.get(engine.mode, "Equilibrado")
        self._highlight_mode(label)
        self.mode_desc.configure(text=MODE_DESC[label])

    def _highlight_mode(self, label):
        for name, b in self.mode_buttons.items():
            sel = name == label
            b.configure(fg_color=T.NEON_DARK if sel else T.CARD_HI, border_color=T.NEON if sel else T.BORDER,
                        text_color=T.NEON if sel else T.TEXT)

    def on_show(self):
        self._sync_state()

    def on_tick(self, s: dict):
        self.cpu_name.configure(text=f"{s.get('cpu_name', '')}\n{s.get('gpu_name') or ''}")
        sc = s["score"]
        self.score_gauge.set(sc)
        self.score_label.configure(text=score_label(sc), text_color=T.score_color(sc))
        hint = "Folga total para jogos e apps pesados." if sc >= 85 else (
            "Carga moderada. TURBO MODE pode ajudar." if sc >= 65 else
            "Sistema sobrecarregado: ative o TURBO MODE ou feche programas.")
        self.score_hint.configure(text=hint)
        freq = f"{s['freq'] / 1000:.2f} GHz · " if s.get("freq") else ""
        self.g["cpu"].set(s["cpu"])
        self.g_sub["cpu"].configure(text=f"{freq}{s['cores']}C/{s['threads']}T")
        self.g["gpu"].set(s.get("gpu"))
        gm = s.get("gpu_mem")
        self.g_sub["gpu"].configure(text=(f"VRAM {fmt_bytes(gm)}" if gm else "") if s.get("gpu") is not None
                                    else "sem leitura de GPU")
        self.g["ram"].set(s["ram"])
        self.g_sub["ram"].configure(text=f"{fmt_bytes(s['ram_used'])} / {fmt_bytes(s['ram_total'])}")
        self.g["disk"].set(s["disk"])
        self.g_sub["disk"].configure(text=f"L {fmt_rate(s['disk_read'])} · E {fmt_rate(s['disk_write'])}\n"
                                          f"{fmt_bytes(s['disk_free'])} livres")
        ct, gt = s.get("cpu_temp"), s.get("gpu_temp")
        self.t_cpu_temp.set(f"{ct:.0f} °C" if ct else "N/D", s.get("temp_source") or
                            "use o LibreHardwareMonitor", T.temp_color(ct))
        self.t_gpu_temp.set(f"{gt:.0f} °C" if gt else "N/D", "via driver/sensor" if gt else "sensor indisponível",
                            T.temp_color(gt))
        self.t_net.set(f"↓ {fmt_rate(s['net_down'])}", f"↑ {fmt_rate(s['net_up'])}")
        up = time.time() - psutil.boot_time()
        self.t_sys.set(f"{int(up // 86400)}d {int(up % 86400 // 3600)}h",
                       f"ligado · {len(psutil.pids())} processos")
        mon = self.app.monitor
        self.chart.update_data({"CPU": mon.get_history("cpu"), "RAM": mon.get_history("ram"),
                                "GPU": mon.get_history("gpu"), "Disco": mon.get_history("disk")})
        if self.turbo.active != engine.turbo_active:
            self._sync_state()

    # ---------------------------------------------------------------- ações
    def toggle_turbo(self):
        if engine.turbo_active:
            if not messagebox.askyesno("TURBO MODE", "Desativar o TURBO MODE e restaurar serviços, apps, plano de "
                                       "energia e ajustes aplicados por ele?", parent=self):
                return
            self.turbo.set_state(True, busy=True)
            self.app.run_async(engine.turbo_off, lambda errs: (
                self._sync_state(), self.app.refresh_mode_label(),
                errs and messagebox.showwarning("TURBO MODE", "Avisos:\n" + "\n".join(errs), parent=self)))
            return
        self.turbo.set_state(False, busy=True)
        self.app.plan_and_run("TURBO MODE", engine.plan_turbo, after=lambda r: self._sync_state(),
                              subtitle="Otimização completa da sessão. Desative clicando no botão novamente: "
                                       "apps fechados são reabertos, serviços reiniciados e o plano de energia "
                                       "original restaurado.")
        self.after(1500, lambda: self.turbo.set_state(engine.turbo_active))

    def change_mode(self, label):
        key = MODE_KEYS[label]
        self.mode_desc.configure(text=MODE_DESC[label])
        self.app.plan_and_run(f"Modo {label}", lambda: engine.plan_mode(key),
                              after=lambda r: self._sync_state())
        self._highlight_mode(label)
        self.after(1500, self._sync_state)

    def free_ram(self):
        before = memory.ram_status()["percent"]

        def done(r):
            after = memory.ram_status()["percent"]
            self.app.notify(f"RAM: {fmt_bytes(r['freed'])} liberados ({before:.0f}% → {after:.0f}%). "
                            f"{r['message']}")
        self.app.run_async(lambda: memory.optimize_ram(deep=True), done)
