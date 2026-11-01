"""Componentes visuais: medidores animados, gráficos, botão TURBO, cartões e linhas de opção."""
from __future__ import annotations

import math
import threading
import tkinter as tk

import customtkinter as ctk

from . import theme as T


def run_bg(widget, fn, on_done=None, on_error=None):
    """Executa fn em thread e entrega o resultado na thread da interface."""
    box = {}

    def worker():
        try:
            box["result"] = fn()
        except Exception as e:  # noqa: BLE001
            box["error"] = e

    th = threading.Thread(target=worker, daemon=True)
    th.start()

    def poll():
        if th.is_alive():
            widget.after(80, poll)
            return
        if "error" in box:
            if on_error:
                on_error(box["error"])
            else:
                from tkinter import messagebox
                messagebox.showerror("TURBO BOOST PRO", f"Erro: {box['error']}")
        elif on_done:
            on_done(box.get("result"))
    widget.after(80, poll)


class Card(ctk.CTkFrame):
    def __init__(self, master, title: str = "", **kw):
        kw.setdefault("fg_color", T.CARD)
        kw.setdefault("corner_radius", 14)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", T.BORDER)
        super().__init__(master, **kw)
        if title:
            ctk.CTkLabel(self, text=title.upper(), font=T.font(11, "bold", tech=True),
                         text_color=T.MUTED).pack(anchor="w", padx=16, pady=(12, 0))


class Gauge(tk.Canvas):
    """Medidor circular de 270° com animação suave e brilho neon."""

    def __init__(self, master, label: str, size: int = 150, unit: str = "%", maxv: float = 100, **kw):
        bg = kw.pop("bg", T.CARD)
        super().__init__(master, width=size, height=size, bg=bg, highlightthickness=0, **kw)
        self.size, self.label, self.unit, self.maxv = size, label, unit, maxv
        self.value = 0.0
        self.target = 0.0
        self.sub = ""
        self.color_fn = T.level_color
        self._na = False
        self._draw()
        self._animate()

    def set(self, value, sub: str = ""):
        self._na = value is None
        self.target = 0.0 if value is None else max(0.0, min(self.maxv, float(value)))
        self.sub = sub

    def _animate(self):
        diff = self.target - self.value
        if abs(diff) > 0.05:
            self.value += diff * 0.18
            self._draw()
        elif self.value != self.target:
            self.value = self.target
            self._draw()
        self.after(30, self._animate)

    def _draw(self):
        self.delete("all")
        s = self.size
        pad = s * 0.1
        w = max(6, s * 0.075)
        box = (pad, pad, s - pad, s - pad)
        pct = self.value / self.maxv * 100
        color = T.SUBTLE if self._na else self.color_fn(pct if self.unit == "%" else self.value)
        self.create_arc(*box, start=225, extent=-270, style="arc", outline=T.TRACK, width=w)
        # marcas
        cx = cy = s / 2
        r1, r2 = s / 2 - pad - w, s / 2 - pad - w - s * 0.035
        for i in range(0, 11):
            a = math.radians(225 - 27 * i)
            self.create_line(cx + r1 * math.cos(a), cy - r1 * math.sin(a), cx + r2 * math.cos(a),
                             cy - r2 * math.sin(a), fill=T.BORDER, width=1)
        ext = -270 * (self.value / self.maxv)
        if abs(ext) > 0.5:
            self.create_arc(*box, start=225, extent=ext, style="arc", outline=T.blend(T.CARD, color, 0.25),
                            width=w + s * 0.06)  # brilho
            self.create_arc(*box, start=225, extent=ext, style="arc", outline=color, width=w)
        txt = "--" if self._na else (f"{self.value:.0f}" + ("" if self.unit == "%" else ""))
        self.create_text(cx, cy - s * 0.04, text=txt, fill=T.TEXT, font=(T.FAMILY_TECH, int(s * 0.2), "bold"))
        self.create_text(cx, cy + s * 0.12, text=self.unit if not self._na else "", fill=T.MUTED,
                         font=(T.FAMILY, int(s * 0.07)))
        self.create_text(cx, s - pad * 0.9, text=self.label, fill=color if not self._na else T.MUTED,
                         font=(T.FAMILY_TECH, int(s * 0.085), "bold"))


class Sparkline(tk.Canvas):
    def __init__(self, master, height=120, series=None, **kw):
        super().__init__(master, height=height, bg=kw.pop("bg", T.CARD), highlightthickness=0, **kw)
        self.series = series or []  # [(nome, cor)]
        self.data: dict[str, list[float]] = {}
        self.bind("<Configure>", lambda e: self.redraw())

    def update_data(self, data: dict[str, list[float]]):
        self.data = data
        self.redraw()

    def redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10:
            return
        for i in range(1, 4):
            y = h * i / 4
            self.create_line(0, y, w, y, fill=T.TRACK, dash=(2, 4))
        for name, color in self.series:
            vals = self.data.get(name) or []
            if len(vals) < 2:
                continue
            step = w / (len(vals) - 1)
            pts = []
            for i, v in enumerate(vals):
                pts += [i * step, h - 4 - (h - 8) * max(0, min(100, v)) / 100]
            poly = [0, h] + pts + [w, h]
            self.create_polygon(*poly, fill=T.blend(T.CARD, color, 0.12), outline="")
            self.create_line(*pts, fill=color, width=2, smooth=True)
        x = 8
        for name, color in self.series:
            vals = self.data.get(name) or [0]
            txt = f"● {name} {vals[-1]:.0f}%"
            self.create_text(x, 10, text=txt, anchor="w", fill=color, font=(T.FAMILY, 9, "bold"))
            x += 92


class TurboButton(tk.Canvas):
    """Botão principal circular com anel pulsante animado."""

    def __init__(self, master, command, size=210, **kw):
        super().__init__(master, width=size, height=size, bg=kw.pop("bg", T.CARD), highlightthickness=0, **kw)
        self.size, self.command = size, command
        self.active = False
        self.busy = False
        self.hover = False
        self.phase = 0.0
        self.bind("<Button-1>", lambda e: (not self.busy) and self.command())
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.configure(cursor="hand2")
        self._tick()

    def _set_hover(self, v):
        self.hover = v

    def set_state(self, active: bool, busy: bool = False):
        self.active, self.busy = active, busy

    def _tick(self):
        self.phase = (self.phase + (0.09 if self.active or self.busy else 0.04)) % (2 * math.pi)
        self._draw()
        self.after(33, self._tick)

    def _draw(self):
        self.delete("all")
        s = self.size
        c = s / 2
        base = T.NEON if not self.active else T.OK
        pulse = (math.sin(self.phase) + 1) / 2
        for i in range(4):  # anéis de brilho
            r = c - 6 - i * 4 + pulse * 3
            col = T.blend(T.CARD, base, 0.08 + 0.1 * (3 - i) / 3 * (0.6 + pulse * 0.4))
            self.create_oval(c - r, c - r, c + r, c + r, outline=col, width=3)
        r = c - 24
        fill = T.blend(T.CARD, base, 0.18 if self.hover else 0.1)
        self.create_oval(c - r, c - r, c + r, c + r, fill=fill, outline=base, width=3)
        # arco giratório
        start = math.degrees(self.phase * (2 if self.busy else 1))
        self.create_arc(c - r - 9, c - r - 9, c + r + 9, c + r + 9, start=start, extent=70, style="arc",
                        outline=base, width=3)
        self.create_arc(c - r - 9, c - r - 9, c + r + 9, c + r + 9, start=start + 180, extent=70, style="arc",
                        outline=base, width=3)
        self.create_text(c, c - 26, text="⚡", fill=base, font=(T.FAMILY, int(s * 0.13)))
        label = "AGUARDE" if self.busy else ("TURBO ON" if self.active else "TURBO MODE")
        self.create_text(c, c + 14, text=label, fill=T.TEXT, font=(T.FAMILY_TECH, int(s * 0.085), "bold"))
        sub = "processando…" if self.busy else ("clique para desativar" if self.active else "clique para ativar")
        self.create_text(c, c + 38, text=sub, fill=T.MUTED, font=(T.FAMILY, int(s * 0.048)))


class StatTile(ctk.CTkFrame):
    def __init__(self, master, title: str, icon: str = "", **kw):
        super().__init__(master, fg_color=T.CARD, corner_radius=14, border_width=1, border_color=T.BORDER, **kw)
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(10, 0))
        ctk.CTkLabel(top, text=f"{icon}  {title.upper()}", font=T.font(10, "bold", True),
                     text_color=T.MUTED).pack(side="left")
        self.value = ctk.CTkLabel(self, text="--", font=T.font(24, "bold", True), text_color=T.TEXT)
        self.value.pack(anchor="w", padx=14)
        self.sub = ctk.CTkLabel(self, text="", font=T.font(11), text_color=T.MUTED)
        self.sub.pack(anchor="w", padx=14, pady=(0, 10))

    def set(self, value: str, sub: str = "", color: str | None = None):
        self.value.configure(text=value, text_color=color or T.TEXT)
        self.sub.configure(text=sub)


class TweakRow(ctk.CTkFrame):
    """Linha com título, descrição, selos (admin/reinício/risco) e um switch."""

    def __init__(self, master, title, description, on_toggle, state=False, admin=False, reboot=False,
                 note="", risk="Baixo", benefit=""):
        super().__init__(master, fg_color=T.CARD, corner_radius=12, border_width=1, border_color=T.BORDER)
        self.on_toggle = on_toggle
        self.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="w", padx=14, pady=(10, 0))
        ctk.CTkLabel(head, text=title, font=T.font(14, "bold"), text_color=T.TEXT).pack(side="left")
        for txt, col, show in (("ADMIN", T.WARN, admin), ("REINÍCIO", T.BLUE, reboot),
                               (f"RISCO {risk.upper()}", T.BAD, risk != "Baixo")):
            if show:
                ctk.CTkLabel(head, text=f" {txt} ", font=T.font(9, "bold"), fg_color=T.blend(T.CARD, col, 0.25),
                             text_color=col, corner_radius=6).pack(side="left", padx=(8, 0))
        desc = description + (f"  ▸ {benefit}" if benefit else "")
        ctk.CTkLabel(self, text=desc, font=T.font(12), text_color=T.MUTED, justify="left", anchor="w",
                     wraplength=760).grid(row=1, column=0, sticky="w", padx=14, pady=(2, 0 if note else 10))
        if note:
            ctk.CTkLabel(self, text="ⓘ " + note, font=T.font(11), text_color=T.WARN, justify="left",
                         anchor="w", wraplength=760).grid(row=2, column=0, sticky="w", padx=14, pady=(2, 10))
        self.var = ctk.BooleanVar(value=state)
        self.switch = ctk.CTkSwitch(self, text="", variable=self.var, command=self._changed,
                                    progress_color=T.NEON, button_color=T.TEXT, fg_color=T.TRACK, width=50)
        self.switch.grid(row=0, column=1, rowspan=3, padx=14)

    def _changed(self):
        self.on_toggle(self.var.get(), self)

    def set_state(self, v: bool):
        self.var.set(v)


def primary_button(master, text, command, width=180, **kw):
    return ctk.CTkButton(master, text=text, command=command, width=width, height=kw.pop("height", 38),
                         fg_color=kw.pop("fg_color", T.NEON), hover_color=kw.pop("hover_color", "#33ddff"),
                         text_color=kw.pop("text_color", "#001018"), font=T.font(13, "bold", True),
                         corner_radius=10, **kw)


def ghost_button(master, text, command, width=160, **kw):
    return ctk.CTkButton(master, text=text, command=command, width=width, height=kw.pop("height", 36),
                         fg_color="transparent", border_width=1, border_color=kw.pop("border_color", T.NEON_DIM),
                         hover_color=T.CARD_HI, text_color=kw.pop("text_color", T.NEON), font=T.font(12, "bold"),
                         corner_radius=10, **kw)


def page_header(master, title, subtitle=""):
    f = ctk.CTkFrame(master, fg_color="transparent")
    ctk.CTkLabel(f, text=title, font=T.font(26, "bold", True), text_color=T.TEXT).pack(anchor="w")
    if subtitle:
        ctk.CTkLabel(f, text=subtitle, font=T.font(13), text_color=T.MUTED, justify="left",
                     wraplength=900).pack(anchor="w")
    return f
