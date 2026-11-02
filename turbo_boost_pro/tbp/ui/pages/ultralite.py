"""Aba WINDOWS ULTRA LITE: debloat, serviços, Gaming Edition, registro, recursos, comparação e log."""
from __future__ import annotations

import os
import time
import tkinter as tk
from tkinter import messagebox, ttk

import customtkinter as ctk

from ...config import LOG_DIR
from ...core import services, snapshot, system_mods, ultralite as UL, winapi
from ...core.engine import engine
from ...core.tweaks import CATEGORIES, TWEAKS
from ...utils import fmt_bytes
from .. import theme as T
from ..dialogs import MONO, ask_admin
from ..widgets import Card, TweakRow, ghost_button, page_header, primary_button, run_bg
from .gaming import tweak_toggle
from .performance import style_tree

LEVEL_STYLE = {"recomendado": ("RECOMENDADO REMOVER", T.WARN), "opcional": ("OPCIONAL", T.NEON),
               "outro": ("OUTRO APP", T.MUTED)}


def _badge(master, text, color):
    return ctk.CTkLabel(master, text=f" {text} ", font=T.font(9, "bold"), text_color=color,
                        fg_color=T.blend(T.CARD, color, 0.2), corner_radius=6)


def _fmt_metric(unit, v):
    if v is None:
        return "N/D"
    if unit == "bytes":
        return fmt_bytes(v)
    if unit == "ms":
        return f"{v / 1000:.1f} s"
    if unit == "%":
        return f"{v:.1f}%"
    return f"{v:.0f}"


class UltraLitePage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color=T.BG)
        self.app = app
        self._loaded: set[str] = set()
        style_tree()
        page_header(self, "WINDOWS ULTRA LITE", "Transforma o Windows 11 em um sistema enxuto e focado em jogos, sem "
                    "formatar. Cada mudança é exibida antes, tem backup e pode ser desfeita.").pack(
            anchor="w", padx=24, pady=(20, 6))
        self.tabs = ctk.CTkTabview(self, fg_color=T.PANEL, segmented_button_selected_color=T.NEON_DARK,
                                   segmented_button_selected_hover_color=T.NEON_DIM, segmented_button_fg_color=T.CARD,
                                   segmented_button_unselected_color=T.CARD, text_color=T.TEXT,
                                   command=self._tab_changed)
        self.tabs.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        self.builders = {"Visão geral": self._build_overview, "Gaming Edition": self._build_gaming,
                         "Debloat": self._build_debloat, "Serviços": self._build_services,
                         "Registro": self._build_registry, "Recursos e tarefas": self._build_features,
                         "Comparação": self._build_compare, "Log": self._build_log}
        self.frames = {name: self.tabs.add(name) for name in self.builders}
        self._tab_changed()

    def _tab_changed(self):
        name = self.tabs.get()
        if name not in self._loaded:
            self._loaded.add(name)
            self.builders[name](self.frames[name])
        refresh = getattr(self, f"_refresh_{name.split()[0].lower()}", None)
        if refresh:
            refresh()

    def on_show(self):
        self._tab_changed()

    def _need_admin(self, what="Esta ação") -> bool:
        if winapi.is_admin():
            return False
        ask_admin(self, f"{what} altera configurações do sistema e exige administrador.")
        return True

    def _run_plan(self, title, builder, after=None, subtitle=""):
        self.app.notify("Analisando o sistema para montar o plano… (pode levar até 1 minuto)")
        self.app.plan_and_run(title, builder, after=lambda r: (self._refresh_all(), after and after(r)),
                              subtitle=subtitle)

    def _refresh_all(self):
        for name in list(self._loaded):
            fn = getattr(self, f"_refresh_{name.split()[0].lower()}", None)
            if fn and name == self.tabs.get():
                fn()

    # ================================================================ VISÃO GERAL
    def _build_overview(self, tab):
        f = ctk.CTkScrollableFrame(tab, fg_color=T.PANEL)
        f.pack(fill="both", expand=True)
        self.compat = Card(f, "Compatibilidade")
        self.compat.pack(fill="x", pady=4)
        self.compat_label = ctk.CTkLabel(self.compat, text="Verificando…", font=T.font(13), text_color=T.TEXT,
                                         justify="left", anchor="w", wraplength=980)
        self.compat_label.pack(anchor="w", padx=16, pady=(4, 12))
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x", pady=4)
        row.grid_columnconfigure((0, 1, 2), weight=1, uniform="o")
        self.cards = {}
        specs = [
            (UL.ULTRA_GID, "⚡ WINDOWS ULTRA LITE", "Remove apps dispensáveis, coloca serviços em Manual (perfil "
             "Avançado), desativa tarefas de telemetria, recursos opcionais e apps de inicialização, reduz efeitos "
             "visuais e uso de RAM em idle.", lambda: self._run_plan("WINDOWS ULTRA LITE", UL.plan_ultra_lite,
                                                                    subtitle="Revise cada item. Itens de risco médio "
                                                                    "e apps opcionais vêm desmarcados.")),
            (UL.GAMING_GID, "🎮 GAMING EDITION", "Plano de energia TURBO, Game Mode, MMCSS, HAGS, prioridade de "
             "primeiro plano, mouse/teclado sem atraso, efeitos visuais mínimos, timer 0,5 ms, boost automático "
             "de jogos e otimizações do CS2.", lambda: self._run_plan("WINDOWS GAMING EDITION",
                                                                        UL.plan_gaming_edition)),
        ]
        for i, (gid, title, desc, apply_fn) in enumerate(specs):
            c = Card(row)
            c.grid(row=0, column=i, sticky="nsew", padx=4)
            ctk.CTkLabel(c, text=title, font=T.font(16, "bold", True), text_color=T.NEON).pack(anchor="w", padx=16,
                                                                                               pady=(14, 2))
            st = ctk.CTkLabel(c, text="", font=T.font(12, "bold"))
            st.pack(anchor="w", padx=16)
            ctk.CTkLabel(c, text=desc, font=T.font(12), text_color=T.MUTED, wraplength=290, justify="left").pack(
                anchor="w", padx=16, pady=6)
            btn = primary_button(c, "", lambda g=gid, a=apply_fn: self._toggle_profile(g, a), width=200, height=44)
            btn.pack(padx=16, pady=(4, 16), anchor="w")
            self.cards[gid] = (st, btn)
        rc = Card(row)
        rc.grid(row=0, column=2, sticky="nsew", padx=4)
        ctk.CTkLabel(rc, text="↺ RESTAURAR ORIGINAL", font=T.font(16, "bold", True),
                     text_color=T.BAD).pack(anchor="w", padx=16, pady=(14, 2))
        ctk.CTkLabel(rc, text="Desfaz absolutamente tudo: reinstala apps removidos, reativa recursos e tarefas, "
                     "restaura serviços, registro, energia, DNS e inicialização. Também é possível usar o ponto de "
                     "restauração criado antes das alterações.", font=T.font(12), text_color=T.MUTED,
                     wraplength=290, justify="left").pack(anchor="w", padx=16, pady=6)
        ctk.CTkButton(rc, text="RESTAURAR WINDOWS", command=self._restore_original, width=200, height=44,
                      fg_color=T.BAD, hover_color="#ff6680", text_color="#fff", font=T.font(14, "bold", True),
                      corner_radius=10).pack(padx=16, pady=(4, 16), anchor="w")
        self.ov_compare = Card(f, "Último resultado medido")
        self.ov_compare.pack(fill="x", pady=4)
        self.ov_compare_label = ctk.CTkLabel(self.ov_compare, text="", font=(MONO, 12), text_color=T.TEXT,
                                             justify="left", anchor="w")
        self.ov_compare_label.pack(anchor="w", padx=16, pady=(4, 12))
        run_bg(self, UL.compat_summary, self._render_compat)

    def _render_compat(self, c):
        col = {"ok": T.OK, "aviso": T.WARN, "bloqueado": T.BAD}[c["level"]]
        txt = f"● {c['label']} · {c['edition'] or ''} · {'Administrador' if c['admin'] else 'Usuário padrão'}"
        if c["warnings"]:
            txt += "\n" + "\n".join("⚠ " + w for w in c["warnings"])
        elif c["level"] == "ok":
            txt += "\n✔ Totalmente compatível."
        self.compat_label.configure(text=txt, text_color=col if c["level"] != "ok" else T.TEXT)

    def _refresh_visão(self):
        for gid, (st, btn) in self.cards.items():
            on = UL.is_active(gid)
            if on:
                since = engine.journal.group(gid)["meta"].get("since", time.time())
                st.configure(text=f"● ATIVO desde {time.strftime('%d/%m %H:%M', time.localtime(since))}",
                             text_color=T.OK)
                btn.configure(text="DESATIVAR", fg_color=T.CARD_HI, text_color=T.WARN, hover_color=T.BORDER)
            else:
                st.configure(text="○ Inativo", text_color=T.MUTED)
                btn.configure(text="APLICAR", fg_color=T.NEON, text_color="#001018", hover_color="#33ddff")
        snaps = snapshot.load()
        before = next((s for s in reversed(snaps) if s["label"].startswith("Antes")), None)
        after = next((s for s in reversed(snaps) if s["label"].startswith("Depois")), None)
        if before and after and after["time"] > before["time"]:
            lines = [f"{before['label']}  →  {after['label']}"]
            for r in snapshot.compare(before, after):
                if r["key"] in ("ram_used", "processes", "services_running", "cpu_idle"):
                    mark = "▼" if r["better"] else ("▲" if r["better"] is False else "=")
                    lines.append(f"{r['label']:<34} {_fmt_metric(r['unit'], r['a']):>10} → "
                                 f"{_fmt_metric(r['unit'], r['b']):>10}  {mark}")
            lines.append("Medição feita logo após aplicar. Reinicie e use 'Comparação › Medir agora' para o "
                         "resultado definitivo (inclui tempo de boot).")
            self.ov_compare_label.configure(text="\n".join(lines))
        else:
            self.ov_compare_label.configure(text="Nenhuma comparação ainda. Aplique um perfil para medir.")

    def _toggle_profile(self, gid, apply_fn):
        if UL.is_active(gid):
            if not messagebox.askyesno(UL.PROFILE_TITLES[gid], f"Desativar o {UL.PROFILE_TITLES[gid]} e restaurar "
                                       "tudo que ele alterou?", parent=self):
                return
            run_bg(self, lambda: UL.deactivate(gid), lambda errs: (
                self._refresh_visão(), self.app.refresh_mode_label(),
                errs and messagebox.showwarning("Desativar", "Avisos:\n" + "\n".join(errs[:15]), parent=self)))
            return
        if not winapi.is_admin() and not messagebox.askyesno(
                "Administrador", "Sem administrador, serviços, recursos, tarefas e itens do sistema serão ignorados. "
                "Continuar mesmo assim? (Recomendado: 'Não' e reabrir como administrador.)", parent=self):
            ask_admin(self, "O WINDOWS ULTRA LITE altera serviços, recursos e políticas do sistema.")
            return
        apply_fn()

    def _restore_original(self):
        if not messagebox.askyesno("RESTAURAR WINDOWS ORIGINAL", "Desfazer TODAS as modificações do TURBO BOOST PRO "
                                   "(incluindo reinstalar apps removidos e reativar recursos)?\n\nPode levar alguns "
                                   "minutos.", parent=self):
            return
        self.app.notify("Restaurando o Windows original… aguarde.")

        def done(errs):
            self._refresh_all()
            self.app.refresh_mode_label()
            if errs:
                messagebox.showwarning("Restauração", "Restauração concluída com avisos:\n\n" + "\n".join(errs[:20]) +
                                       "\n\nSe algo não voltou, use o ponto de restauração do Windows (aba "
                                       "Segurança).", parent=self)
            else:
                messagebox.showinfo("Restauração", "Windows restaurado ao estado original.\nReinicie o computador "
                                    "para concluir.", parent=self)
        run_bg(self, UL.restore_windows_original, done)

    # ================================================================ GAMING EDITION
    def _build_gaming(self, tab):
        f = ctk.CTkScrollableFrame(tab, fg_color=T.PANEL)
        f.pack(fill="both", expand=True)
        top = Card(f)
        top.pack(fill="x", pady=4)
        r = ctk.CTkFrame(top, fg_color="transparent")
        r.pack(fill="x", padx=16, pady=14)
        ctk.CTkLabel(r, text="🎮 WINDOWS GAMING EDITION", font=T.font(20, "bold", True), text_color=T.NEON).pack(
            side="left")
        self.ge_status = ctk.CTkLabel(r, text="", font=T.font(13, "bold"))
        self.ge_status.pack(side="left", padx=16)
        self.ge_btn = primary_button(r, "", lambda: self._toggle_profile(UL.GAMING_GID, lambda: self._run_plan(
            "WINDOWS GAMING EDITION", UL.plan_gaming_edition)), width=200, height=42)
        self.ge_btn.pack(side="right")
        inc = Card(f, "O que o perfil aplica")
        inc.pack(fill="x", pady=4)
        items = [t.title for t in TWEAKS if t.gamer] + [
            "Plano de energia TURBO BOOST PRO (CPU sem economia, núcleos sem estacionamento)",
            "Serviços de telemetria e atualizadores em Manual (perfil Conservador)",
            "Timer de 0,5 ms + boost automático ao abrir jogos", "CS2: prioridade Alta e GPU dedicada (se instalado)"]
        ctk.CTkLabel(inc, text="\n".join("• " + i for i in items), font=T.font(12), text_color=T.TEXT,
                     justify="left").pack(anchor="w", padx=16, pady=(4, 12))
        cs = Card(f, "Counter-Strike 2")
        cs.pack(fill="x", pady=4)
        self.cs_status = ctk.CTkLabel(cs, text="Procurando CS2…", font=T.font(13), text_color=T.TEXT, justify="left")
        self.cs_status.pack(anchor="w", padx=16, pady=4)
        b = ctk.CTkFrame(cs, fg_color="transparent")
        b.pack(fill="x", padx=16, pady=4)
        primary_button(b, "Aplicar otimizações CS2", lambda: self._cs2(False), width=210).pack(side="left")
        ghost_button(b, "Aplicar + autoexec.cfg", lambda: self._cs2(True), width=190).pack(side="left", padx=8)
        ghost_button(b, "Reverter CS2", self._cs2_revert, width=130, border_color=T.BAD, text_color=T.BAD).pack(
            side="left")
        lo = ctk.CTkFrame(cs, fg_color="transparent")
        lo.pack(fill="x", padx=16, pady=(8, 2))
        ctk.CTkLabel(lo, text="Opções de inicialização (Steam › CS2 › Propriedades):", text_color=T.MUTED).pack(
            side="left")
        e = ctk.CTkEntry(lo, width=300, fg_color=T.CARD_HI, border_color=T.BORDER, font=(MONO, 12))
        e.insert(0, system_mods.CS2_LAUNCH_OPTIONS)
        e.pack(side="left", padx=8)
        ghost_button(lo, "Copiar", lambda: (self.clipboard_clear(), self.clipboard_append(
            system_mods.CS2_LAUNCH_OPTIONS), self.app.notify("Opções copiadas.")), width=80, height=28).pack(
            side="left")
        ctk.CTkLabel(cs, text="Configurações de vídeo recomendadas (competitivo):", font=T.font(12, "bold"),
                     text_color=T.NEON).pack(anchor="w", padx=16, pady=(10, 0))
        ctk.CTkLabel(cs, text="\n".join("• " + t for t in system_mods.CS2_VIDEO_TIPS), font=T.font(12),
                     text_color=T.TEXT, justify="left").pack(anchor="w", padx=16, pady=(2, 14))

    def _refresh_gaming(self):
        on = UL.is_active(UL.GAMING_GID)
        self.ge_status.configure(text="● ATIVO" if on else "○ Inativo", text_color=T.OK if on else T.MUTED)
        self.ge_btn.configure(text="DESATIVAR PERFIL" if on else "ATIVAR PERFIL",
                              fg_color=T.CARD_HI if on else T.NEON, text_color=T.WARN if on else "#001018")

        def done(st):
            if not st["found"]:
                self.cs_status.configure(text="CS2 não encontrado nas bibliotecas da Steam.", text_color=T.MUTED)
                return
            ok = lambda v: "✔" if v else "✘"  # noqa: E731
            self.cs_status.configure(text=f"{st['exe']}\n{ok(st['priority'])} Prioridade Alta (CPU/E-S)   "
                                     f"{ok(st['gpu'])} GPU de alto desempenho   {ok(st['autoexec'])} autoexec.cfg",
                                     text_color=T.TEXT)
        run_bg(self, system_mods.cs2_status, done)

    def _cs2(self, autoexec):
        if self._need_admin("A prioridade permanente do CS2"):
            return
        self.app.plan_and_run("Otimizações do CS2", lambda: UL.plan_cs2(autoexec) or [],
                              after=lambda r: self._refresh_gaming())

    def _cs2_revert(self):
        run_bg(self, lambda: engine.journal.revert_group("game:cs2"),
               lambda errs: (self.app.notify("CS2 restaurado." if not errs else "; ".join(errs)),
                             self._refresh_gaming()))

    # ================================================================ DEBLOAT
    def _build_debloat(self, tab):
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", pady=4)
        self.db_info = ctk.CTkLabel(bar, text="", font=T.font(13, "bold"), text_color=T.TEXT)
        self.db_info.pack(side="left")
        primary_button(bar, "Remover selecionados", self._debloat_remove, width=190).pack(side="right")
        ghost_button(bar, "Atualizar lista", self._refresh_debloat, width=130).pack(side="right", padx=6)
        ctk.CTkLabel(tab, text="Remoção apenas para o seu usuário: a cópia do sistema é mantida e o app pode ser "
                     "reinstalado a qualquer momento (botão abaixo ou RESTAURAR). Store, Xbox Identity/Gaming "
                     "Services, codecs, calculadora, bloco de notas e drivers nunca aparecem aqui.",
                     text_color=T.MUTED, font=T.font(11), wraplength=1000, justify="left").pack(anchor="w")
        self.db_box = ctk.CTkScrollableFrame(tab, fg_color=T.PANEL)
        self.db_box.pack(fill="both", expand=True, pady=4)
        self.db_removed = ctk.CTkFrame(tab, fg_color="transparent")
        self.db_removed.pack(fill="x")
        self.db_vars = []

    def _refresh_debloat(self):
        self.db_info.configure(text="Lendo apps instalados…")
        run_bg(self, system_mods.list_apps, self._render_debloat)
        self._render_removed()

    def _render_debloat(self, apps):
        for w in self.db_box.winfo_children():
            w.destroy()
        self.db_vars = []
        rec = sum(1 for a in apps if a["level"] == "recomendado")
        self.db_info.configure(text=f"{len(apps)} apps removíveis encontrados · {rec} recomendados")
        for a in apps:
            row = ctk.CTkFrame(self.db_box, fg_color=T.CARD, corner_radius=8)
            row.pack(fill="x", pady=2, padx=2)
            v = ctk.BooleanVar(value=a["level"] == "recomendado")
            self.db_vars.append((v, a))
            ctk.CTkCheckBox(row, text="", variable=v, width=24, fg_color=T.NEON, border_color=T.NEON_DIM).pack(
                side="left", padx=8, pady=6)
            ctk.CTkLabel(row, text=a["label"], font=T.font(13, "bold"), text_color=T.TEXT).pack(side="left")
            txt, col = LEVEL_STYLE[a["level"]]
            _badge(row, txt, col).pack(side="left", padx=8)
            ctk.CTkLabel(row, text=f"{a['desc']}  ·  {a['name']}", font=T.font(11), text_color=T.MUTED).pack(
                side="left", padx=4)
        if not apps:
            ctk.CTkLabel(self.db_box, text="Nenhum app removível encontrado (ou não é Windows).",
                         text_color=T.SUBTLE).pack(pady=20)

    def _render_removed(self):
        for w in self.db_removed.winfo_children():
            w.destroy()
        removed = engine.journal.groups("appx:")
        if not removed:
            return
        ctk.CTkLabel(self.db_removed, text=f"REMOVIDOS PELO TURBO BOOST PRO ({len(removed)})",
                     font=T.font(11, "bold", True), text_color=T.NEON).pack(anchor="w", pady=(6, 2))
        line = ctk.CTkFrame(self.db_removed, fg_color="transparent")
        line.pack(fill="x")
        for gid, g in list(removed.items())[:12]:
            ghost_button(line, "↺ " + g["title"].replace("App removido: ", ""), lambda gid=gid: self._reinstall(gid),
                         width=10, height=26).pack(side="left", padx=2, pady=2)

    def _reinstall(self, gid):
        self.app.notify("Reinstalando app…")
        run_bg(self, lambda: engine.journal.revert_group(gid),
               lambda errs: (self.app.notify("App reinstalado." if not errs else "; ".join(errs)),
                             self._refresh_debloat()))

    def _debloat_remove(self):
        sel = [a for v, a in self.db_vars if v.get()]
        if sel:
            self.app.plan_and_run("Remover apps selecionados", lambda: UL.plan_debloat(sel),
                                  after=lambda r: self._refresh_debloat())

    # ================================================================ SERVIÇOS
    def _build_services(self, tab):
        prof = ctk.CTkFrame(tab, fg_color="transparent")
        prof.pack(fill="x", pady=4)
        prof.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="p")
        for i, (key, title, col) in enumerate((("conservador", "CONSERVADOR", T.OK), ("avancado", "AVANÇADO", T.NEON),
                                               ("extremo", "EXTREMO", T.WARN))):
            c = Card(prof)
            c.grid(row=0, column=i, sticky="nsew", padx=3)
            ctk.CTkLabel(c, text=title, font=T.font(15, "bold", True), text_color=col).pack(anchor="w", padx=12,
                                                                                            pady=(10, 0))
            ctk.CTkLabel(c, text=services.PROFILE_NOTES[key], font=T.font(11), text_color=T.MUTED, wraplength=250,
                         justify="left").pack(anchor="w", padx=12, pady=4)
            ghost_button(c, f"Aplicar {title.lower()}", lambda k=key: self._svc_profile(k), width=170,
                         border_color=col, text_color=col).pack(anchor="w", padx=12, pady=(0, 10))
        c = Card(prof)
        c.grid(row=0, column=3, sticky="nsew", padx=3)
        ctk.CTkLabel(c, text="ORIGINAL", font=T.font(15, "bold", True), text_color=T.TEXT).pack(anchor="w", padx=12,
                                                                                               pady=(10, 0))
        ctk.CTkLabel(c, text="Restaura o tipo de inicialização original de todos os serviços alterados.",
                     font=T.font(11), text_color=T.MUTED, wraplength=250, justify="left").pack(anchor="w", padx=12,
                                                                                              pady=4)
        ghost_button(c, "Restaurar serviços", self._svc_restore, width=170).pack(anchor="w", padx=12, pady=(0, 10))
        frame = tk.Frame(tab, bg=T.CARD)
        frame.pack(fill="both", expand=True, pady=6)
        cols = ("svc", "purpose", "state", "start", "mem", "c", "a", "e")
        self.svc_tree = ttk.Treeview(frame, columns=cols, show="headings", style="TBP.Treeview")
        for col, label, w in (("svc", "Serviço", 220), ("purpose", "Finalidade", 380), ("state", "Estado", 90),
                              ("start", "Inicialização", 130), ("mem", "RAM do processo", 120),
                              ("c", "Conservador", 95), ("a", "Avançado", 90), ("e", "Extremo", 90)):
            self.svc_tree.heading(col, text=label)
            self.svc_tree.column(col, width=w, anchor="w" if col in ("svc", "purpose") else "center")
        self.svc_tree.tag_configure("changed", foreground=T.NEON)
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.svc_tree.yview)
        self.svc_tree.configure(yscrollcommand=sb.set)
        self.svc_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        ctk.CTkLabel(tab, text="Protegidos e nunca alterados: Defender, Firewall, Windows Update, BITS, Store, áudio, "
                     "Bluetooth, rede (DHCP/DNS/Wi-Fi), Plug and Play, energia e serviços do núcleo. "
                     "Azul = alterado pelo TURBO BOOST PRO.", text_color=T.MUTED, font=T.font(11), wraplength=1000,
                     justify="left").pack(anchor="w")

    def _refresh_serviços(self):
        def done(rows):
            self.svc_tree.delete(*self.svc_tree.get_children())
            lab = {None: "-", "demand": "Manual", "disabled": "Desativado"}
            for s in rows:
                mem = fmt_bytes(s["mem"]) + (" (compart.)" if s["shared"] else "") if s["mem"] else "-"
                tag = ("changed",) if engine.journal.has_group(f"service:{s['name']}") else ()
                self.svc_tree.insert("", "end", values=(f"{s['label']} ({s['name']})", s["desc"][:90],
                                                        "Executando" if s["status"] == "running" else "Parado",
                                                        s["start_label"], mem, *[lab[p] for p in s["profiles"]]),
                                     tags=tag)
        run_bg(self, services.detailed_status, done)

    def _svc_profile(self, profile):
        if self._need_admin("Alterar serviços"):
            return
        self.app.plan_and_run(f"Serviços: perfil {profile}", lambda: UL.plan_service_profile(profile),
                              after=lambda r: self._refresh_serviços(),
                              subtitle=services.PROFILE_NOTES[profile])

    def _svc_restore(self):
        if self._need_admin("Restaurar serviços"):
            return
        run_bg(self, lambda: engine.journal.revert_all("service:"),
               lambda errs: (self.app.notify("Serviços restaurados." if not errs else "; ".join(errs[:3])),
                             self._refresh_serviços()))

    # ================================================================ REGISTRO
    def _build_registry(self, tab):
        f = ctk.CTkScrollableFrame(tab, fg_color=T.PANEL)
        f.pack(fill="both", expand=True)
        ctk.CTkLabel(f, text="Cada ajuste mostra a chave, o valor atual → novo e o efeito. Ligar = aplicar com "
                     "backup automático; desligar = restaurar o valor original.", text_color=T.MUTED,
                     font=T.font(12), wraplength=1000, justify="left").pack(anchor="w", pady=4)
        self.reg_rows = {}
        for cat, label in CATEGORIES.items():
            tw = [t for t in TWEAKS if t.category == cat]
            if not tw:
                continue
            ctk.CTkLabel(f, text=label.upper(), font=T.font(12, "bold", True), text_color=T.NEON).pack(
                anchor="w", pady=(12, 2))
            for t in tw:
                row = TweakRow(f, t.title, t.description, tweak_toggle(self.app, t, self._refresh_registro),
                               admin=t.requires_admin(), reboot=t.reboot, note=t.note, risk=t.risk,
                               benefit=t.benefit)
                row.pack(fill="x", pady=3, padx=2)
                keys = ctk.CTkLabel(row, text="", font=(MONO, 10), text_color=T.SUBTLE, justify="left", anchor="w",
                                    wraplength=900)
                keys.grid(row=3, column=0, sticky="w", padx=14, pady=(0, 8))
                self.reg_rows[t.id] = (t, row, keys)

    def _refresh_registro(self):
        def load():
            return {tid: (t.status(), "\n".join(c.describe() for c in t.get_changes()))
                    for tid, (t, _r, _k) in self.reg_rows.items()}

        def done(st):
            for tid, (status, keys) in st.items():
                _t, row, lab = self.reg_rows[tid]
                row.set_state(status == "aplicado")
                lab.configure(text=keys or "(não se aplica a este PC)")
        run_bg(self, load, done)

    # ================================================================ RECURSOS E TAREFAS
    def _build_features(self, tab):
        cols = ctk.CTkFrame(tab, fg_color="transparent")
        cols.pack(fill="both", expand=True)
        cols.grid_columnconfigure((0, 1), weight=1, uniform="f")
        cols.grid_rowconfigure(1, weight=1)
        for i, (title, cmd) in enumerate((("RECURSOS OPCIONAIS", self._features_apply),
                                          ("TAREFAS AGENDADAS DE TELEMETRIA", self._tasks_apply))):
            h = ctk.CTkFrame(cols, fg_color="transparent")
            h.grid(row=0, column=i, sticky="ew", padx=4)
            ctk.CTkLabel(h, text=title, font=T.font(12, "bold", True), text_color=T.NEON).pack(side="left")
            primary_button(h, "Desativar selecionados", cmd, width=180, height=30).pack(side="right")
        self.feat_box = ctk.CTkScrollableFrame(cols, fg_color=T.PANEL)
        self.feat_box.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        self.task_box = ctk.CTkScrollableFrame(cols, fg_color=T.PANEL)
        self.task_box.grid(row=1, column=1, sticky="nsew", padx=4, pady=4)
        ctk.CTkLabel(tab, text="Recursos são desativados sem apagar os arquivos (reativação offline). Reative "
                     "individualmente na aba Segurança ou com RESTAURAR WINDOWS ORIGINAL.", text_color=T.MUTED,
                     font=T.font(11)).pack(anchor="w")
        self.feat_vars, self.task_vars = [], []

    def _refresh_recursos(self):
        for box in (self.feat_box, self.task_box):
            for w in box.winfo_children():
                w.destroy()
            ctk.CTkLabel(box, text="Carregando (pode levar 30 s)…", text_color=T.MUTED).pack(pady=10)
        run_bg(self, lambda: (system_mods.list_features(), system_mods.list_tasks()), self._render_features)

    def _render_features(self, data):
        feats, tasks = data
        self.feat_vars, self.task_vars = [], []
        for box, items, store, key in ((self.feat_box, feats, self.feat_vars, "label"),
                                       (self.task_box, tasks, self.task_vars, "name")):
            for w in box.winfo_children():
                w.destroy()
            if not items:
                ctk.CTkLabel(box, text="Nada encontrado (requer Windows/administrador).", text_color=T.SUBTLE).pack(
                    pady=10)
            for it in items:
                row = ctk.CTkFrame(box, fg_color=T.CARD, corner_radius=8)
                row.pack(fill="x", pady=2)
                on = it["enabled"]
                v = ctk.BooleanVar(value=on and it.get("level", "recomendado") == "recomendado")
                cb = ctk.CTkCheckBox(row, text=it[key], variable=v, font=T.font(12, "bold"), text_color=T.TEXT,
                                     fg_color=T.NEON, border_color=T.NEON_DIM)
                cb.pack(anchor="w", padx=8, pady=(6, 0))
                if not on:
                    cb.configure(state="disabled", text=it[key] + "  (já desativado)")
                ctk.CTkLabel(row, text=it["desc"], font=T.font(11), text_color=T.MUTED, wraplength=440,
                             justify="left").pack(anchor="w", padx=36, pady=(0, 6))
                if on:
                    store.append((v, it))

    def _features_apply(self):
        sel = [it for v, it in self.feat_vars if v.get()]
        if sel and not self._need_admin("Desativar recursos"):
            self.app.plan_and_run("Desativar recursos opcionais", lambda: UL.plan_features(sel),
                                  after=lambda r: self._refresh_recursos())

    def _tasks_apply(self):
        sel = [it for v, it in self.task_vars if v.get()]
        if sel and not self._need_admin("Desativar tarefas"):
            self.app.plan_and_run("Desativar tarefas agendadas", lambda: UL.plan_tasks(sel),
                                  after=lambda r: self._refresh_recursos())

    # ================================================================ COMPARAÇÃO
    def _build_compare(self, tab):
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", pady=4)
        primary_button(bar, "📊 Medir agora", self._measure, width=150).pack(side="left")
        ctk.CTkLabel(bar, text="  Comparar:", text_color=T.MUTED).pack(side="left")
        self.cmp_a = ctk.CTkComboBox(bar, values=[], width=300, command=lambda v: self._render_compare(),
                                     fg_color=T.CARD_HI, border_color=T.BORDER, button_color=T.NEON_DARK)
        self.cmp_a.pack(side="left", padx=6)
        ctk.CTkLabel(bar, text="→", text_color=T.NEON, font=T.font(16, "bold")).pack(side="left")
        self.cmp_b = ctk.CTkComboBox(bar, values=[], width=300, command=lambda v: self._render_compare(),
                                     fg_color=T.CARD_HI, border_color=T.BORDER, button_color=T.NEON_DARK)
        self.cmp_b.pack(side="left", padx=6)
        ghost_button(bar, "Limpar histórico", lambda: (snapshot.clear(), self._refresh_comparação()), width=130,
                     border_color=T.BAD, text_color=T.BAD).pack(side="right")
        self.cmp_card = Card(tab)
        self.cmp_card.pack(fill="both", expand=True, pady=6)
        self.cmp_rows = ctk.CTkFrame(self.cmp_card, fg_color="transparent")
        self.cmp_rows.pack(fill="both", expand=True, padx=16, pady=12)
        ctk.CTkLabel(tab, text="Para medir o ganho real: meça antes, aplique, REINICIE, espere 2 minutos e meça de "
                     "novo. Medições do mesmo boot não mostram o tempo de inicialização nem o efeito de serviços "
                     "que só deixam de iniciar após reiniciar.", text_color=T.MUTED, font=T.font(11),
                     wraplength=1000, justify="left").pack(anchor="w")

    def _snap_label(self, s):
        return f"{time.strftime('%d/%m %H:%M', time.localtime(s['time']))} · {s['label']} #{s['id'] % 10000}"

    def _refresh_comparação(self):
        self.snaps = snapshot.load()
        labels = [self._snap_label(s) for s in self.snaps]
        self.cmp_a.configure(values=labels)
        self.cmp_b.configure(values=labels)
        if len(labels) >= 2:
            before = next((i for i in range(len(self.snaps) - 1, -1, -1) if self.snaps[i]["label"].startswith("Antes")),
                          len(labels) - 2)
            self.cmp_a.set(labels[before])
            self.cmp_b.set(labels[-1])
        else:
            self.cmp_a.set(labels[0] if labels else "")
            self.cmp_b.set("")
        self._render_compare()

    def _render_compare(self):
        for w in self.cmp_rows.winfo_children():
            w.destroy()
        idx = {self._snap_label(s): s for s in getattr(self, "snaps", [])}
        a, b = idx.get(self.cmp_a.get()), idx.get(self.cmp_b.get())
        if not (a and b):
            ctk.CTkLabel(self.cmp_rows, text="Faça pelo menos duas medições para comparar.", text_color=T.MUTED,
                         font=T.font(13)).pack(pady=20)
            return
        heads = ("Métrica", "Antes", "Depois", "Diferença", "")
        for c, h in enumerate(heads):
            ctk.CTkLabel(self.cmp_rows, text=h, font=T.font(12, "bold"), text_color=T.NEON).grid(
                row=0, column=c, sticky="w", padx=10, pady=4)
        wins = 0
        for i, r in enumerate(snapshot.compare(a, b), start=1):
            col = T.OK if r["better"] else (T.BAD if r["better"] is False else T.MUTED)
            if r["better"]:
                wins += 1
            if r["delta"] is None:
                diff = "-"
            else:
                sign = "+" if r["delta"] > 0 else ""
                d = _fmt_metric(r["unit"], abs(r["delta"]))
                diff = f"{sign if r['delta'] > 0 else '-'}{d}" if r["delta"] else "="
                if r["pct"] is not None and r["delta"]:
                    diff += f"  ({r['pct']:+.0f}%)"
            verdict = "melhor" if r["better"] else ("pior" if r["better"] is False else "")
            for c, val in enumerate((r["label"], _fmt_metric(r["unit"], r["a"]), _fmt_metric(r["unit"], r["b"]),
                                     diff, verdict)):
                ctk.CTkLabel(self.cmp_rows, text=val, font=T.font(13, "bold" if c == 0 else "normal"),
                             text_color=col if c >= 3 else T.TEXT).grid(row=i, column=c, sticky="w", padx=10, pady=3)
        note = f"{wins} métrica(s) melhoraram."
        if snapshot.same_boot(a, b):
            note += "  ⚠ Mesmo boot: reinicie e meça de novo para o resultado definitivo."
        ctk.CTkLabel(self.cmp_rows, text=note, font=T.font(12, "bold"), text_color=T.WARN if snapshot.same_boot(a, b)
                     else T.OK).grid(row=20, column=0, columnspan=5, sticky="w", padx=10, pady=(14, 0))

    def _measure(self):
        self.app.notify("Medindo por 8 segundos… evite usar o PC durante a medição.")
        run_bg(self, lambda: snapshot.capture("Medição manual", journal=engine.journal),
               lambda s: (self._refresh_comparação(), self.app.notify("Medição registrada.")))

    # ================================================================ LOG
    def _build_log(self, tab):
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", pady=4)
        ctk.CTkLabel(bar, text="Registro de todas as operações (atualiza automaticamente)", text_color=T.MUTED).pack(
            side="left")
        ghost_button(bar, "Abrir pasta de logs", lambda: os.startfile(LOG_DIR) if os.name == "nt" else None,
                     width=160).pack(side="right")
        self.log_box = ctk.CTkTextbox(tab, fg_color=T.CARD, text_color=T.TEXT, font=(MONO, 11), wrap="none")
        self.log_box.pack(fill="both", expand=True, pady=4)
        self._log_job = None

    def _refresh_log(self):
        path = LOG_DIR / "turbo_boost_pro.log"
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-400:]
        except OSError:
            lines = ["(log vazio)"]
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.insert("end", "".join(lines))
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        if self._log_job:
            self.after_cancel(self._log_job)
        if self.app.current == "ultralite" and self.tabs.get() == "Log":
            self._log_job = self.after(2000, self._refresh_log)
