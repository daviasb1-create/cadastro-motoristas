"""Aba AUTO OPTIMIZER (TURBO BENCHMARK AI): laboratório de testes A/B com decisão estatística."""
from __future__ import annotations

import queue
import statistics
import time
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from ...config import settings
from ...core import autoopt as AO, bench, winapi
from ...core.cs2_control import CS2Error, demo_path, demo_ready, install_demo
from ...core.system_mods import find_cs2
from ...utils import fmt_bytes
from .. import theme as T
from ..dialogs import MONO, ask_admin
from ..widgets import Card, ghost_button, page_header, primary_button, run_bg

VERDICT_COLOR = {"melhor": T.OK, "pior": T.BAD, "instável": T.BAD, "igual": T.MUTED, "sem dados": T.SUBTLE}
SCOPE_LABEL = {"live": "AO VIVO", "game": "REINICIA O JOGO", "reboot": "REINICIA O PC"}


class AutoOptPage(ctk.CTkScrollableFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color=T.BG)
        self.app = app
        self.runner: AO.Runner = app.autoopt_runner
        self.requests: queue.Queue = queue.Queue()
        self.runner.ask = self._ask_from_worker
        self._was_running = False
        page_header(self, "AUTO OPTIMIZER · TURBO BENCHMARK AI", "Testa uma configuração por vez no CS2, repete as "
                    "medições, calcula a margem de erro e só recomenda o que melhorou de verdade (prioridade: 1% low "
                    "e estabilidade do frametime).").pack(anchor="w", padx=24, pady=(20, 8))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=24, pady=4)
        self.btns = {}
        specs = (("analyze", "🔍 ANALISAR MEU PC", self._analyze, "ghost"),
                 ("bench", "▶ INICIAR BENCHMARK", self._bench, "ghost"),
                 ("auto", "🧪 OTIMIZAR AUTOMATICAMENTE", self._auto, "primary"),
                 ("best", "✔ APLICAR MELHOR CONFIG.", self._apply_best, "ghost"),
                 ("restore", "↺ RESTAURAR CONFIGURAÇÕES", self._restore, "danger"))
        for i, (key, text, cmd, style) in enumerate(specs):
            bar.grid_columnconfigure(i, weight=1, uniform="b")
            if style == "primary":
                b = primary_button(bar, text, cmd, width=10, height=42)
            else:
                b = ghost_button(bar, text, cmd, width=10, height=42,
                                 border_color=T.BAD if style == "danger" else T.NEON_DIM,
                                 text_color=T.BAD if style == "danger" else T.NEON)
            b.grid(row=0, column=i, sticky="ew", padx=3)
            self.btns[key] = b
        self.stop_btn = ghost_button(self, "■ PARAR TESTE (reverte as configurações de teste)", self.runner.stop,
                                     width=10, height=36, border_color=T.WARN, text_color=T.WARN)
        self._bar = bar

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=18, pady=4)
        top.grid_columnconfigure(0, weight=2, uniform="t")
        top.grid_columnconfigure(1, weight=3, uniform="t")
        self._build_setup(top)
        self._build_live(top)

        self.tabs = ctk.CTkTabview(self, fg_color=T.PANEL, segmented_button_selected_color=T.NEON_DARK,
                                   segmented_button_selected_hover_color=T.NEON_DIM, segmented_button_fg_color=T.CARD,
                                   segmented_button_unselected_color=T.CARD, text_color=T.TEXT, height=520)
        self.tabs.pack(fill="x", padx=20, pady=(6, 20))
        self.res_tab = self.tabs.add("Resultados")
        self.cmp_tab = self.tabs.add("Comparação A × B")
        self.hist_tab = self.tabs.add("Histórico")
        self.hw_tab = self.tabs.add("Meu PC")
        self._build_compare()
        self.hist_box = ctk.CTkTextbox(self.hist_tab, fg_color=T.CARD, text_color=T.TEXT, font=(MONO, 11), height=460)
        self.hist_box.pack(fill="both", expand=True)
        self.hw_label = ctk.CTkLabel(self.hw_tab, text="Clique em ANALISAR MEU PC.", font=T.font(13), text_color=T.TEXT,
                                     justify="left", anchor="w", wraplength=1000)
        self.hw_label.pack(anchor="w", padx=12, pady=12)
        self._render_results()
        self._poll()

    # ================================================================ configuração do teste
    def _build_setup(self, parent):
        c = Card(parent, "Configuração do teste")
        c.grid(row=0, column=0, sticky="nsew", padx=6)
        r = ctk.CTkFrame(c, fg_color="transparent")
        r.pack(fill="x", padx=14, pady=(6, 2))
        ctk.CTkLabel(r, text="Método:", text_color=T.MUTED).pack(side="left")
        self.mode = ctk.CTkSegmentedButton(r, values=["Demo automática", "Manual"], selected_color=T.NEON_DARK,
                                           command=lambda v: self._update_estimate())
        self.mode.set("Demo automática" if settings.get("autoopt_mode", "demo") == "demo" else "Manual")
        self.mode.pack(side="left", padx=6)
        self.demo_lbl = ctk.CTkLabel(c, text="", font=T.font(11), text_color=T.MUTED, justify="left", wraplength=460)
        self.demo_lbl.pack(anchor="w", padx=14)
        d = ctk.CTkFrame(c, fg_color="transparent")
        d.pack(fill="x", padx=14, pady=2)
        ghost_button(d, "Escolher demo", self._pick_demo, width=120, height=28).pack(side="left")
        ctk.CTkLabel(d, text="Tick inicial:", text_color=T.MUTED).pack(side="left", padx=(10, 2))
        self.tick = ctk.CTkEntry(d, width=70, fg_color=T.CARD_HI, border_color=T.BORDER)
        self.tick.insert(0, str(settings.get("bench_demo_tick", 2000)))
        self.tick.pack(side="left")
        ctk.CTkLabel(d, text="Espera (s):", text_color=T.MUTED).pack(side="left", padx=(8, 2))
        self.loadw = ctk.CTkEntry(d, width=44, fg_color=T.CARD_HI, border_color=T.BORDER)
        self.loadw.insert(0, str(settings.get("bench_load_wait", 30)))
        self.loadw.pack(side="left")
        r2 = ctk.CTkFrame(c, fg_color="transparent")
        r2.pack(fill="x", padx=14, pady=4)
        ctk.CTkLabel(r2, text="Repetições:", text_color=T.MUTED).pack(side="left")
        self.reps = ctk.CTkComboBox(r2, values=["2", "3", "4", "5"], width=60, command=lambda v: self._update_estimate(),
                                    fg_color=T.CARD_HI, border_color=T.BORDER, button_color=T.NEON_DARK)
        self.reps.set(str(settings.get("autoopt_reps", 3)))
        self.reps.pack(side="left", padx=4)
        ctk.CTkLabel(r2, text="Duração (s):", text_color=T.MUTED).pack(side="left", padx=(8, 0))
        self.secs = ctk.CTkComboBox(r2, values=["20", "30", "45", "60"], width=60,
                                    command=lambda v: self._update_estimate(), fg_color=T.CARD_HI,
                                    border_color=T.BORDER, button_color=T.NEON_DARK)
        self.secs.set(str(settings.get("autoopt_seconds", 30)))
        self.secs.pack(side="left", padx=4)
        self.reboot_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(c, text="Incluir testes que reiniciam o PC (continua após o login)",
                        variable=self.reboot_var, command=self._update_estimate, font=T.font(11), text_color=T.TEXT,
                        fg_color=T.NEON, border_color=T.NEON_DIM).pack(anchor="w", padx=14, pady=2)
        ctk.CTkLabel(c, text="VARIÁVEIS A TESTAR", font=T.font(10, "bold", True), text_color=T.NEON).pack(
            anchor="w", padx=14, pady=(6, 0))
        box = ctk.CTkScrollableFrame(c, fg_color=T.CARD_HI, height=210)
        box.pack(fill="x", padx=10, pady=4)
        self.var_checks = {}
        for v in AO.VARIABLES:
            row = ctk.CTkFrame(box, fg_color="transparent")
            row.pack(fill="x")
            var = ctk.BooleanVar(value=v.scope != "reboot")
            ctk.CTkCheckBox(row, text=f"{v.title}", variable=var, command=self._update_estimate, font=T.font(11),
                            text_color=T.TEXT, fg_color=T.NEON, border_color=T.NEON_DIM, checkbox_width=16,
                            checkbox_height=16).pack(side="left")
            col = {"live": T.OK, "game": T.NEON, "reboot": T.WARN}[v.scope]
            ctk.CTkLabel(row, text=f" {SCOPE_LABEL[v.scope]} ", font=T.font(8, "bold"), text_color=col,
                         fg_color=T.blend(T.CARD_HI, col, 0.2), corner_radius=5).pack(side="left", padx=6)
            self.var_checks[v.id] = var
        self.estimate = ctk.CTkLabel(c, text="", font=T.font(12, "bold"), text_color=T.NEON)
        self.estimate.pack(anchor="w", padx=14, pady=(2, 12))
        self._refresh_demo()
        self._update_estimate()

    def _refresh_demo(self):
        cs = find_cs2()
        if not cs:
            txt, col = "CS2 não encontrado. Use o modo Manual (funciona com qualquer jogo).", T.WARN
        elif demo_ready():
            txt, col = f"✔ Demo pronta: {demo_path()}", T.OK
        else:
            txt, col = ("Demo automática: escolha um arquivo .dem (uma partida sua ou de HLTV). Dica: grave a sua em uma "
                        "partida contra bots com 'record tbp' / 'stop' no console. Demos antigas podem parar de "
                        "funcionar após atualizações do CS2."), T.WARN
        self.demo_lbl.configure(text=txt, text_color=col)

    def _pick_demo(self):
        p = filedialog.askopenfilename(title="Demo do CS2", filetypes=[("Demo CS2", "*.dem")], parent=self)
        if p:
            try:
                install_demo(p)
            except CS2Error as e:
                messagebox.showerror("Demo", str(e), parent=self)
            self._refresh_demo()

    def _selected_vars(self):
        return [k for k, v in self.var_checks.items() if v.get()]

    def _mode_key(self):
        return "demo" if self.mode.get() == "Demo automática" else "manual"

    def _update_estimate(self):
        steps = AO.build_steps(self._selected_vars(), int(self.reps.get()), self.reboot_var.get(), self._mode_key())
        n = sum(1 for s in steps if s["kind"] == "measure")
        mins = AO.estimate_minutes(steps, int(self.secs.get()), self._mode_key())
        reboots = sum(1 for s in steps if s["kind"] == "reboot")
        self.estimate.configure(text=f"{n} medições · ~{mins} min" + (f" · {reboots} reinícios" if reboots else ""))

    def _save_opts(self):
        settings.set("autoopt_mode", self._mode_key())
        settings.set("autoopt_reps", int(self.reps.get()))
        settings.set("autoopt_seconds", int(self.secs.get()))
        try:
            settings.set("bench_demo_tick", max(0, int(self.tick.get())))
            settings.set("bench_load_wait", max(10, int(self.loadw.get())))
        except ValueError:
            pass

    # ================================================================ painel ao vivo
    def _build_live(self, parent):
        c = Card(parent, "Execução em tempo real")
        c.grid(row=0, column=1, sticky="nsew", padx=6)
        self.status_lbl = ctk.CTkLabel(c, text="Pronto.", font=T.font(13, "bold"), text_color=T.TEXT,
                                       wraplength=640, justify="left", anchor="w")
        self.status_lbl.pack(anchor="w", padx=14, pady=(6, 2))
        self.prog = ctk.CTkProgressBar(c, progress_color=T.NEON, fg_color=T.TRACK, height=10)
        self.prog.pack(fill="x", padx=14, pady=4)
        self.prog.set(0)
        self.live_chart = tk.Canvas(c, height=200, bg=T.CARD, highlightthickness=0)
        self.live_chart.pack(fill="x", padx=14, pady=6)
        tiles = ctk.CTkFrame(c, fg_color="transparent")
        tiles.pack(fill="x", padx=10, pady=(0, 12))
        self.tiles = {}
        for i, (k, lab) in enumerate((("fps", "FPS (ao vivo)"), ("cpu", "CPU"), ("gpu", "GPU"), ("ct", "Temp. CPU"),
                                      ("gt", "Temp. GPU"), ("ram", "RAM"))):
            f = ctk.CTkFrame(tiles, fg_color=T.CARD_HI, corner_radius=8)
            f.grid(row=0, column=i, sticky="ew", padx=3)
            tiles.grid_columnconfigure(i, weight=1)
            ctk.CTkLabel(f, text=lab, font=T.font(9, "bold"), text_color=T.MUTED).pack(pady=(4, 0))
            v = ctk.CTkLabel(f, text="--", font=T.font(16, "bold", True), text_color=T.TEXT)
            v.pack(pady=(0, 4))
            self.tiles[k] = v

    def _draw_live(self, data):
        c = self.live_chart
        c.delete("all")
        w, h = max(300, c.winfo_width()), 200
        c.create_text(8, 10, anchor="w", text="Frametime ao vivo (ms) — picos = travadas", fill=T.MUTED,
                      font=(T.FAMILY, 9, "bold"))
        fts = (data or {}).get("frametimes") or []
        if len(fts) < 2:
            c.create_text(w / 2, h / 2, text="Aguardando quadros…", fill=T.SUBTLE, font=(T.FAMILY, 11))
            return
        top = max(sorted(fts)[int(len(fts) * 0.98) - 1] * 1.3, 1.0)
        step = w / (len(fts) - 1)
        pts = []
        for i, v in enumerate(fts):
            pts += [i * step, h - 6 - (h - 26) * min(v, top) / top]
        c.create_line(*pts, fill=T.NEON, width=1)
        med = statistics.median(fts)
        y = h - 6 - (h - 26) * min(med, top) / top
        c.create_line(0, y, w, y, fill=T.SUBTLE, dash=(3, 3))
        c.create_text(w - 6, y - 8, anchor="e", text=f"mediana {med:.2f} ms", fill=T.MUTED, font=(T.FAMILY, 8))

    def _poll(self):
        st = self.runner.status
        running = self.runner.running
        self.status_lbl.configure(text=f"[{st.get('step', '')}] {st['text']}" if running else st["text"])
        self.prog.set(st.get("progress", 0))
        live = st.get("live")
        if running and live:
            self._draw_live(live)
            fts = live.get("frametimes") or []
            self.tiles["fps"].configure(text=f"{1000 / statistics.mean(fts[-120:]):.0f}" if fts else "--")
            self.tiles["cpu"].configure(text=f"{live['cpu']:.0f}%" if live.get("cpu") is not None else "--")
            self.tiles["gpu"].configure(text=f"{live['gpu']:.0f}%" if live.get("gpu") is not None else "N/D")
            self.tiles["ct"].configure(text=f"{live['cpu_temp']:.0f}°" if live.get("cpu_temp") else "N/D",
                                       text_color=T.temp_color(live.get("cpu_temp")))
            self.tiles["gt"].configure(text=f"{live['gpu_temp']:.0f}°" if live.get("gpu_temp") else "N/D",
                                       text_color=T.temp_color(live.get("gpu_temp")))
            self.tiles["ram"].configure(text=fmt_bytes(live["ram"]) if live.get("ram") else "--")
        for k in ("bench", "auto", "best", "restore", "analyze"):
            self.btns[k].configure(state="disabled" if running else "normal")
        if running and not self.stop_btn.winfo_ismapped():
            self.stop_btn.pack(fill="x", padx=27, pady=(2, 4), after=self._bar)
        elif not running and self.stop_btn.winfo_ismapped():
            self.stop_btn.pack_forget()
        if self._was_running and not running:
            self._render_results()
            self.app.notify("Auto Optimizer: " + st["text"], "game")
        self._was_running = running
        try:
            while True:
                text, ev, box = self.requests.get_nowait()
                box["ok"] = messagebox.askokcancel("Auto Optimizer · modo manual", text, parent=self)
                ev.set()
        except queue.Empty:
            pass
        self.after(500, self._poll)

    def _ask_from_worker(self, text) -> bool:
        import threading
        ev, box = threading.Event(), {}
        self.requests.put((text, ev, box))
        ev.wait()
        return box.get("ok", False)

    # ================================================================ ações
    def _ready(self) -> bool:
        if not winapi.is_admin():
            ask_admin(self, "O Auto Optimizer (mede eventos de desempenho e altera configurações do sistema)")
            return False
        if not bench.presentmon_path():
            messagebox.showerror("PresentMon", "PresentMon não encontrado. Reinstale o TURBO BOOST PRO ou indique o "
                                 "executável em Competitivo › Benchmark › PresentMon…", parent=self)
            return False
        if self._mode_key() == "demo" and not demo_ready():
            messagebox.showwarning("Demo", "Selecione uma demo (.dem) do CS2 ou use o modo Manual.", parent=self)
            return False
        return True

    def _analyze(self):
        self.hw_label.configure(text="Analisando hardware e configuração…")
        self.tabs.set("Meu PC")

        def done(hw):
            lines = [f"Processador: {hw['cpu']} ({hw['cores']} núcleos / {hw['threads']} threads)",
                     f"Memória: {fmt_bytes(hw['ram'])} · {hw.get('ram_modules', '?')} módulo(s) · "
                     f"{hw.get('ram_speed') or '?'} MT/s",
                     "Placa(s) de vídeo: " + "; ".join(hw.get("gpus") or ["N/D"]),
                     "Armazenamento: " + "; ".join(hw.get("disks") or ["N/D"]),
                     f"Windows: {hw['windows']}", "", "CONFIGURAÇÃO ATUAL (estado A de cada teste):"]
            for k, v in hw["config"].items():
                title = AO.VAR_BY_ID[k].title if k in AO.VAR_BY_ID else "Plano de energia"
                lines.append(f"   • {title}: {v}")
            cs = find_cs2()
            lines += ["", f"CS2: {cs['exe'] if cs else 'não encontrado'}",
                      f"PresentMon: {bench.presentmon_path() or 'não encontrado'}",
                      "Temperaturas: lidas do sensor do Windows ou do LibreHardwareMonitor (se aberto); "
                      "aparecem como N/D quando o PC não expõe sensores."]
            self.hw_label.configure(text="\n".join(lines))
        run_bg(self, AO.hardware_summary, done)

    def _bench(self):
        if not self._ready():
            return
        self._save_opts()
        self.runner.start([], int(self.reps.get()), int(self.secs.get()), self._mode_key(), False)
        self.app.notify("Benchmark da configuração atual iniciado. Não use o PC durante o teste.", "game")

    def _auto(self):
        if not self._ready():
            return
        vids = self._selected_vars()
        if not vids:
            return
        self._save_opts()
        steps = AO.build_steps(vids, int(self.reps.get()), self.reboot_var.get(), self._mode_key())
        mins = AO.estimate_minutes(steps, int(self.secs.get()), self._mode_key())
        reboots = sum(1 for s in steps if s["kind"] == "reboot")
        msg = (f"O teste vai durar cerca de {mins} minutos" + (f" e reiniciar o PC {reboots} vezes" if reboots else "")
               + ".\n\n• Um ponto de restauração e um backup são criados antes.\n• Uma configuração é alterada por vez "
               "e revertida logo após a medição.\n• Se algo falhar, tudo que o teste alterou é revertido.\n• Não use o "
               "PC durante o teste (feche navegadores e downloads).\n\nIniciar?")
        if messagebox.askyesno("OTIMIZAR AUTOMATICAMENTE", msg, parent=self):
            self.runner.start(vids, int(self.reps.get()), int(self.secs.get()), self._mode_key(),
                              self.reboot_var.get())

    def _apply_best(self):
        sess = AO.current_session()
        best = AO.best_config(sess)
        if not best:
            messagebox.showinfo("Melhor configuração", "Nenhum ajuste superou a margem de erro nos testes: a sua "
                                "configuração atual já é a melhor comprovada.", parent=self)
            return
        lines = "\n".join(f"• {b['title']}: {b['from']} → {b['to']}  (1% low {b['gain_1low']:+.1f}%, "
                          f"FPS {b['gain_avg']:+.1f}%)" for b in best)
        if messagebox.askyesno("APLICAR MELHOR CONFIGURAÇÃO", f"Aplicar as alterações comprovadas:\n\n{lines}\n\n"
                               "Todas ficam registradas e podem ser revertidas.", parent=self):
            run_bg(self, lambda: AO.apply_best(sess), lambda msgs: messagebox.showinfo(
                "Aplicado", "\n".join(msgs), parent=self))

    def _restore(self):
        if messagebox.askyesno("RESTAURAR", "Reverter todas as alterações feitas pelo Auto Optimizer (testes e melhor "
                               "configuração aplicada)?", parent=self):
            run_bg(self, AO.restore_all, lambda errs: self.app.notify(
                "Configurações do Auto Optimizer restauradas." if not errs else "; ".join(errs[:3])))

    # ================================================================ resultados
    def _render_results(self):
        for w in self.res_tab.winfo_children():
            w.destroy()
        sess = AO.current_session()
        box = ctk.CTkScrollableFrame(self.res_tab, fg_color=T.PANEL, height=470)
        box.pack(fill="both", expand=True)
        if not sess:
            ctk.CTkLabel(box, text="Nenhum teste executado ainda.", text_color=T.SUBTLE).pack(pady=20)
            self._render_history()
            return
        res = sess.get("results") or AO.analyze_session(sess)
        base = sess["trials"].get("__base__", {}).get("A", [])
        okb = [t for t in base if not t.get("failed")]
        if okb:
            avg = lambda k: statistics.mean(t[k] for t in okb if t.get(k) is not None)  # noqa: E731
            ctk.CTkLabel(box, text=f"LINHA DE BASE ({len(okb)} medições): {avg('fps_avg'):.0f} FPS médio · 1% low "
                         f"{avg('fps_1low'):.0f} · 0,1% low {avg('fps_01low'):.0f} · frametime {avg('ft_avg'):.2f} ms "
                         f"(variação {avg('ft_std'):.2f})", font=T.font(13, "bold"), text_color=T.TEXT).pack(
                anchor="w", padx=8, pady=6)
        heads = ("Variável", "A (atual)", "B (teste)", "FPS médio", "1% low", "0,1% low", "Var. frametime", "Margem",
                 "Resultado")
        grid = ctk.CTkFrame(box, fg_color="transparent")
        grid.pack(fill="x")
        for c, h in enumerate(heads):
            ctk.CTkLabel(grid, text=h, font=T.font(11, "bold"), text_color=T.NEON).grid(row=0, column=c, sticky="w",
                                                                                        padx=6)
        for i, (vid, r) in enumerate(sorted(res.items(), key=lambda kv: -kv[1].get("score", 0)), start=1):
            info = sess["var_info"].get(vid, {})
            m = r.get("metrics", {})

            def cell(k):
                x = m.get(k)
                if not x:
                    return "-"
                return f"{x['pct']:+.1f}%" + ("*" if x["significant"] else "")
            vals = (info.get("title", vid), info.get("a", ""), info.get("b", ""), cell("fps_avg"), cell("fps_1low"),
                    cell("fps_01low"), cell("ft_std"), f"±{m.get('fps_1low', {}).get('margin_pct', 0):.1f}%",
                    r.get("verdict", "").upper())
            col = VERDICT_COLOR.get(r.get("verdict"), T.MUTED)
            for c, v in enumerate(vals):
                ctk.CTkLabel(grid, text=str(v), font=T.font(11, "bold" if c in (0, 8) else "normal"),
                             text_color=col if c >= 3 else T.TEXT, wraplength=230 if c == 0 else 160,
                             justify="left").grid(row=i, column=c, sticky="w", padx=6, pady=2)
        comb = sess.get("combined")
        notes = ["* = diferença acima da margem de erro (estatisticamente relevante). 'IGUAL' = dentro da variação "
                 "natural do FPS: não vale a pena mudar."]
        if comb:
            m = comb.get("metrics", {})
            notes.append(f"COMBINAÇÃO VENCEDORA x início: {comb['verdict'].upper()} (1% low "
                         f"{m.get('fps_1low', {}).get('pct', 0):+.1f}%, FPS {m.get('fps_avg', {}).get('pct', 0):+.1f}%)")
        if sess.get("status") not in ("done",):
            notes.append(f"Estado da sessão: {sess.get('status')} {sess.get('error', '')}")
        best = AO.best_config(sess)
        notes.append("MELHOR CONFIGURAÇÃO: " + (", ".join(f"{b['title']} → {b['to']}" for b in best) if best else
                                               "manter a atual (nenhuma alteração comprovada)"))
        ctk.CTkLabel(box, text="\n".join(notes), font=T.font(12), text_color=T.TEXT, justify="left",
                     wraplength=1000).pack(anchor="w", padx=8, pady=10)
        self.cmp_var.configure(values=[sess["var_info"].get(v, {}).get("title", v) for v in res])
        if res:
            self.cmp_var.set(sess["var_info"].get(next(iter(res)), {}).get("title", ""))
            self._render_compare()
        self._render_history()

    def _build_compare(self):
        bar = ctk.CTkFrame(self.cmp_tab, fg_color="transparent")
        bar.pack(fill="x", pady=4)
        ctk.CTkLabel(bar, text="Variável:", text_color=T.MUTED).pack(side="left")
        self.cmp_var = ctk.CTkComboBox(bar, values=[], width=360, command=lambda v: self._render_compare(),
                                       fg_color=T.CARD_HI, border_color=T.BORDER, button_color=T.NEON_DARK)
        self.cmp_var.pack(side="left", padx=6)
        self.cmp_canvas = tk.Canvas(self.cmp_tab, height=430, bg=T.CARD, highlightthickness=0)
        self.cmp_canvas.pack(fill="both", expand=True, pady=4)

    def _render_compare(self):
        c = self.cmp_canvas
        c.delete("all")
        sess = AO.current_session()
        if not sess:
            return
        vid = next((k for k, v in sess["var_info"].items() if v.get("title") == self.cmp_var.get()), None)
        if not vid:
            return
        trials = sess["trials"].get(vid, {})
        a = [t for t in trials.get("A", []) if not t.get("failed")]
        b = [t for t in trials.get("B", []) if not t.get("failed")]
        info = sess["var_info"][vid]
        c.update_idletasks()
        w = max(600, c.winfo_width())
        metrics = [("fps_avg", "FPS médio"), ("fps_1low", "1% low"), ("fps_01low", "0,1% low"),
                   ("cpu_avg", "CPU %"), ("gpu_avg", "GPU %"), ("cpu_temp_max", "Temp CPU"), ("gpu_temp_max", "Temp GPU"),
                   ("latency_ms", "Latência ms")]
        c.create_text(10, 12, anchor="w", text=f"A = {info['a']}   ×   B = {info['b']}", fill=T.TEXT,
                      font=(T.FAMILY, 11, "bold"))
        bw = (w - 40) / len(metrics)
        for i, (k, lab) in enumerate(metrics):
            va = [t[k] for t in a if t.get(k) is not None]
            vb = [t[k] for t in b if t.get(k) is not None]
            x0 = 20 + i * bw
            c.create_text(x0 + bw / 2, 210, text=lab, fill=T.MUTED, font=(T.FAMILY, 9, "bold"))
            if not va or not vb:
                c.create_text(x0 + bw / 2, 120, text="N/D", fill=T.SUBTLE, font=(T.FAMILY, 10))
                continue
            ma, mb = statistics.mean(va), statistics.mean(vb)
            top = max(ma, mb) * 1.15 or 1
            for j, (val, col) in enumerate(((ma, T.MUTED), (mb, T.NEON))):
                h = 150 * val / top
                x = x0 + bw * 0.2 + j * bw * 0.32
                c.create_rectangle(x, 195 - h, x + bw * 0.28, 195, fill=col, outline="")
                c.create_text(x + bw * 0.14, 188 - h, text=f"{val:.0f}", fill=T.TEXT, font=(T.FAMILY, 8))
            pct = (mb - ma) / ma * 100 if ma else 0
            c.create_text(x0 + bw / 2, 40, text=f"{pct:+.1f}%", fill=T.OK if pct > 0 and k.startswith("fps") else
                          T.TEXT, font=(T.FAMILY, 10, "bold"))
        top_y, h = 235, 180
        c.create_text(10, top_y, anchor="w", text="Frametime (ms): cinza = A · azul = B", fill=T.MUTED,
                      font=(T.FAMILY, 9, "bold"))
        series = [(sum((t.get("series") or [] for t in a), []), T.MUTED), (sum((t.get("series") or [] for t in b), []),
                                                                           T.NEON)]
        allv = [v for s, _ in series for v in s]
        if allv:
            top = max(sorted(allv)[int(len(allv) * 0.99) - 1] * 1.3, 1)
            for s, col in series:
                if len(s) < 2:
                    continue
                step = (w - 20) / (len(s) - 1)
                pts = []
                for k2, v in enumerate(s):
                    pts += [10 + k2 * step, top_y + h - (h - 20) * min(v, top) / top]
                c.create_line(*pts, fill=col, width=1)

    def _render_history(self):
        st = AO.load_state()
        lines = []
        for sess in reversed(st["sessions"]):
            t = time.strftime("%d/%m %H:%M", time.localtime(sess["started"]))
            lines.append(f"===== Sessão {t} · {sess['mode']} · {sess['reps']}×{sess['seconds']} s · status: "
                         f"{sess['status']} =====")
            for ts, text in sess.get("log", [])[-60:]:
                lines.append(f"{time.strftime('%H:%M:%S', time.localtime(ts))}  {text}")
            lines.append("")
        self.hist_box.configure(state="normal")
        self.hist_box.delete("1.0", "end")
        self.hist_box.insert("end", "\n".join(lines) or "Sem histórico.")
        self.hist_box.configure(state="disabled")

    def on_show(self):
        self._refresh_demo()
