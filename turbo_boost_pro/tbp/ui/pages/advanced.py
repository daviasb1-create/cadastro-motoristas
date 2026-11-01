"""Otimização avançada do Windows: registro, responsividade, visual, energia, rede/DNS, SSD/HDD e
segundo plano."""
from __future__ import annotations

from tkinter import messagebox

import customtkinter as ctk

from ...config import settings
from ...core import network, power, storage, winapi
from ...core.engine import engine
from ...core.tweaks import by_category
from ...utils import fmt_bytes
from .. import theme as T
from ..dialogs import ask_admin
from ..widgets import Card, TweakRow, ghost_button, page_header, primary_button, run_bg
from .gaming import tweak_toggle

TABS = [("responsividade", "Responsividade"), ("visual", "Efeitos visuais"), ("energia", "Energia e CPU"),
        ("rede", "Rede e DNS"), ("armazenamento", "SSD / HDD"), ("segundo_plano", "Segundo plano")]


class AdvancedPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color=T.BG)
        self.app = app
        self.rows: dict[str, tuple] = {}
        page_header(self, "Otimização Avançada do Windows", "Ajustes seguros e reversíveis. O valor atual e o novo "
                    "de cada chave de registro são exibidos antes de aplicar.").pack(anchor="w", padx=24,
                                                                                        pady=(20, 6))
        tabs = ctk.CTkTabview(self, fg_color=T.PANEL, segmented_button_selected_color=T.NEON_DARK,
                              segmented_button_selected_hover_color=T.NEON_DIM, segmented_button_fg_color=T.CARD,
                              segmented_button_unselected_color=T.CARD, text_color=T.TEXT)
        tabs.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        for cat, label in TABS:
            frame = ctk.CTkScrollableFrame(tabs.add(label), fg_color=T.PANEL)
            frame.pack(fill="both", expand=True)
            tw = by_category(cat)
            if tw:
                bar = ctk.CTkFrame(frame, fg_color="transparent")
                bar.pack(fill="x", pady=(2, 6))
                primary_button(bar, "Aplicar todos desta aba", lambda ids=[t.id for t in tw if t.risk == "Baixo"]:
                               self.app.plan_and_run("Otimizações avançadas", lambda: engine.plan_tweaks(ids),
                                                     after=lambda r: self.refresh()), width=200).pack(side="right")
            extra = getattr(self, f"_extra_{cat}", None)
            if extra:
                extra(frame)
            for t in tw:
                row = TweakRow(frame, t.title, t.description, tweak_toggle(app, t, self.refresh),
                               admin=t.requires_admin(), reboot=t.reboot, note=t.note, risk=t.risk,
                               benefit=t.benefit)
                row.pack(fill="x", pady=4, padx=2)
                self.rows[t.id] = (t, row)
        self.refresh()

    def on_show(self):
        self.refresh()

    def refresh(self):
        run_bg(self, lambda: {tid: t.status() for tid, (t, _r) in self.rows.items()},
               lambda st: [self.rows[k][1].set_state(v == "aplicado") for k, v in st.items()])

    # ---------------------------------------------------------------- extras por aba
    def _extra_responsividade(self, f):
        c = Card(f, "Explorer")
        c.pack(fill="x", pady=4, padx=2)
        r = ctk.CTkFrame(c, fg_color="transparent")
        r.pack(fill="x", padx=14, pady=10)
        ctk.CTkLabel(r, text="Alguns ajustes visuais/de interface só aparecem após reiniciar o Explorer.",
                     text_color=T.MUTED).pack(side="left")
        ghost_button(r, "Reiniciar Explorer", winapi.restart_explorer, width=160).pack(side="right")

    def _extra_energia(self, f):
        c = Card(f, "Plano de energia")
        c.pack(fill="x", pady=4, padx=2)
        self.plan_label = ctk.CTkLabel(c, text="Carregando…", font=T.font(14, "bold"), text_color=T.TEXT)
        self.plan_label.pack(anchor="w", padx=14, pady=(6, 2))
        r = ctk.CTkFrame(c, fg_color="transparent")
        r.pack(fill="x", padx=14, pady=(4, 12))
        primary_button(r, "Ativar plano TURBO", lambda: self.app.plan_and_run(
            "Plano de energia TURBO", lambda: engine._power_action(), after=lambda _r: self._load_plan()),
            width=180).pack(side="left")
        ghost_button(r, "Restaurar plano anterior", lambda: run_bg(
            self, lambda: power.set_balanced(engine.journal), lambda m: (self.app.notify(m), self._load_plan())),
            width=200).pack(side="left", padx=8)
        self.plans_combo = ctk.CTkComboBox(r, values=[], width=240, fg_color=T.CARD_HI, border_color=T.BORDER,
                                           button_color=T.NEON_DARK, command=self._choose_plan)
        self.plans_combo.pack(side="right")
        ctk.CTkLabel(r, text="Trocar para:", text_color=T.MUTED).pack(side="right", padx=6)
        self._load_plan()

    def _load_plan(self):
        def done(r):
            active, plans = r
            self._plans = {p["name"]: p["guid"] for p in plans}
            self.plan_label.configure(text=f"Ativo: {active['name'] if active else '?'}")
            self.plans_combo.configure(values=list(self._plans))
            if active:
                self.plans_combo.set(active["name"])
        run_bg(self, lambda: (power.active_plan(), power.list_plans()), done)

    def _choose_plan(self, name):
        guid = self._plans.get(name)
        if guid:
            power.set_plan(guid)
            self._load_plan()
            self.app.notify(f"Plano de energia: {name}")

    def _extra_rede(self, f):
        c = Card(f, "DNS")
        c.pack(fill="x", pady=4, padx=2)
        r = ctk.CTkFrame(c, fg_color="transparent")
        r.pack(fill="x", padx=14, pady=8)
        self.dns_combo = ctk.CTkComboBox(r, values=[v[0] for v in network.DNS_PROVIDERS.values()], width=240,
                                         fg_color=T.CARD_HI, border_color=T.BORDER, button_color=T.NEON_DARK)
        self.dns_combo.set(network.DNS_PROVIDERS[settings.get("preferred_dns")][0])
        self.dns_combo.pack(side="left")
        primary_button(r, "Aplicar DNS", self._apply_dns, width=120).pack(side="left", padx=6)
        ghost_button(r, "Restaurar DNS original", self._restore_dns, width=190).pack(side="left", padx=6)
        ghost_button(r, "Limpar cache DNS", lambda: self.app.notify(
            "Cache DNS limpo." if network.flush_dns() else "Falha ao limpar cache DNS."), width=150).pack(
            side="left", padx=6)
        r2 = ctk.CTkFrame(c, fg_color="transparent")
        r2.pack(fill="x", padx=14, pady=(0, 6))
        ghost_button(r2, "⏱ Testar DNS mais rápido", self._bench, width=200).pack(side="left")
        ghost_button(r2, "📶 Testar ping", self._ping, width=140).pack(side="left", padx=6)
        self.dns_result = ctk.CTkLabel(c, text="", font=("Consolas", 12), text_color=T.MUTED, justify="left")
        self.dns_result.pack(anchor="w", padx=16, pady=(0, 12))

    def _apply_dns(self):
        if not winapi.is_admin():
            ask_admin(self, "Alterar o DNS exige administrador.")
            return
        key = next(k for k, v in network.DNS_PROVIDERS.items() if v[0] == self.dns_combo.get())
        settings.set("preferred_dns", key)
        if messagebox.askyesno("DNS", f"Alterar o DNS de todos os adaptadores ativos para "
                               f"{network.DNS_PROVIDERS[key][0]} ({', '.join(network.DNS_PROVIDERS[key][1])})?\n"
                               "O DNS atual será salvo para restauração.", parent=self):
            run_bg(self, lambda: network.set_dns(key, engine.journal)[1], self.app.notify)

    def _restore_dns(self):
        run_bg(self, lambda: network.restore_dns(engine.journal),
               lambda errs: self.app.notify("DNS original restaurado." if not errs else "; ".join(errs)))

    def _bench(self):
        self.dns_result.configure(text="Testando 5 domínios em cada servidor…")

        def done(res):
            lines = []
            for i, r in enumerate(res):
                ms = f"{r['ms']:.0f} ms" if r["ms"] is not None else "sem resposta"
                lines.append(f"{'★' if i == 0 else ' '} {r['name']:<34} {r['server']:<16} {ms}")
            self.dns_result.configure(text="\n".join(lines), text_color=T.TEXT)
            best = next((r for r in res if r["key"] in network.DNS_PROVIDERS), None)
            if best:
                self.dns_combo.set(network.DNS_PROVIDERS[best["key"]][0])
        run_bg(self, network.benchmark_dns, done)

    def _ping(self):
        self.dns_result.configure(text="Medindo ping…")
        def done(r):
            lines = [f"Ping {name}: {ms:.0f} ms" if ms else f"Ping {name}: sem resposta"
                     for name, ms in zip(("Cloudflare (1.1.1.1)", "Google (8.8.8.8)"), r)]
            self.dns_result.configure(text="\n".join(lines), text_color=T.TEXT)
        run_bg(self, lambda: (network.ping("1.1.1.1"), network.ping("8.8.8.8")), done)

    def _extra_armazenamento(self, f):
        self.storage_card = Card(f, "Unidades")
        self.storage_card.pack(fill="x", pady=4, padx=2)
        self.storage_box = ctk.CTkFrame(self.storage_card, fg_color="transparent")
        self.storage_box.pack(fill="x", padx=14, pady=8)
        ctk.CTkLabel(self.storage_box, text="Carregando…", text_color=T.MUTED).pack(anchor="w")
        c2 = Card(f, "Ajustes do sistema de arquivos (revertíveis)")
        c2.pack(fill="x", pady=4, padx=2)
        r = ctk.CTkFrame(c2, fg_color="transparent")
        r.pack(fill="x", padx=14, pady=10)
        self.trim_label = ctk.CTkLabel(r, text="TRIM: verificando…", text_color=T.TEXT, font=T.font(13, "bold"))
        self.trim_label.pack(side="left")
        ghost_button(r, "Ativar TRIM", lambda: self._fs(storage.enable_trim), width=120).pack(side="right", padx=4)
        ghost_button(r, "Desativar 'último acesso' NTFS", lambda: self._fs(storage.set_last_access_off),
                     width=230).pack(side="right", padx=4)
        ctk.CTkLabel(c2, text="'Último acesso' desativado reduz escritas no disco a cada arquivo lido (útil em HDD e "
                     "para durabilidade do SSD).", text_color=T.MUTED, font=T.font(11), wraplength=860,
                     justify="left").pack(anchor="w", padx=14, pady=(0, 10))
        run_bg(self, lambda: (storage.list_volumes(), storage.trim_enabled()), self._render_storage)

    def _render_storage(self, r):
        vols, trim = r
        self.trim_label.configure(text=f"TRIM: {'ativado ✔' if trim else 'desativado' if trim is False else '?'}",
                                  text_color=T.OK if trim else T.WARN)
        for w in self.storage_box.winfo_children():
            w.destroy()
        for v in vols:
            row = ctk.CTkFrame(self.storage_box, fg_color=T.CARD_HI, corner_radius=8)
            row.pack(fill="x", pady=2)
            col = T.OK if v["kind"] == "SSD" else T.WARN
            used = 1 - (v["free"] / v["size"]) if v["size"] else 0
            ctk.CTkLabel(row, text=f"{v['letter']}:  {v['kind']}  ·  {v['model'] or ''}", text_color=col,
                         font=T.font(13, "bold")).pack(side="left", padx=10, pady=6)
            ctk.CTkLabel(row, text=f"{fmt_bytes(v['free'])} livres de {fmt_bytes(v['size'])} ({used:.0%} usado)",
                         text_color=T.MUTED).pack(side="left", padx=10)
            label = "Executar TRIM" if v["kind"] == "SSD" else "Desfragmentar" if v["kind"] == "HDD" else "Otimizar"
            ghost_button(row, label, lambda v=v: self._optimize(v), width=130, height=28).pack(side="right", padx=8)
        if not vols:
            ctk.CTkLabel(self.storage_box, text="Nenhuma unidade detectada (requer Windows).",
                         text_color=T.SUBTLE).pack(anchor="w")

    def _optimize(self, v):
        if not winapi.is_admin():
            ask_admin(self, "Otimizar unidades exige administrador.")
            return
        self.app.notify(f"Otimizando unidade {v['letter']}: em segundo plano…")
        run_bg(self, lambda: storage.optimize_volume(v["letter"], v["kind"]), self.app.notify)

    def _fs(self, fn):
        if not winapi.is_admin():
            ask_admin(self, "Este ajuste exige administrador.")
            return
        run_bg(self, lambda: fn(engine.journal), lambda m: (self.app.notify(m), run_bg(
            self, lambda: (storage.list_volumes(), storage.trim_enabled()), self._render_storage)))
