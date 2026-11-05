"""Identidade visual (tema escuro) e padrões de gráficos."""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

SURFACE = "#111827"
BG = "#0b1220"
TEXT = "#e8ecf2"
TEXT_2 = "#a9b4c4"
GRID = "#1f2a3a"
# Paleta categórica (ordem fixa), validada para fundo #111827: contraste e daltonismo OK
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9"]
SEQ = "#3987e5"  # magnitude: tom único
# Cores de estado (reservadas para prioridade; sempre acompanhadas de rótulo)
PRIORITY_COLORS = {
    "Oportunidade prioritária": "#e66767",
    "Oportunidade qualificada": "#c98500",
    "Oportunidade em observação": "#3987e5",
    "Baixa prioridade": "#6b7280",
}

CSS = f"""
<style>
.block-container {{padding-top: 1.6rem; max-width: 1500px;}}
section[data-testid="stSidebar"] {{background: #0a101c; border-right: 1px solid {GRID};}}
.li-brand {{font-weight: 800; letter-spacing: .08em; font-size: 1.05rem; color: {TEXT};}}
.li-sub {{color: {TEXT_2}; font-size: .78rem; letter-spacing: .12em; text-transform: uppercase;}}
.li-card {{background: {SURFACE}; border: 1px solid {GRID}; border-radius: 10px; padding: 14px 16px; height: 100%;}}
.li-card .lbl {{color: {TEXT_2}; font-size: .74rem; text-transform: uppercase; letter-spacing: .06em;}}
.li-card .val {{color: {TEXT}; font-size: 1.65rem; font-weight: 700; line-height: 1.2; margin-top: 4px;}}
.li-card .hint {{color: {TEXT_2}; font-size: .74rem; margin-top: 2px;}}
.li-pill {{display:inline-block; padding: 2px 10px; border-radius: 999px; font-size: .75rem; font-weight: 600;
          border: 1px solid {GRID}; color: {TEXT};}}
.li-section {{color: {TEXT_2}; font-size: .8rem; text-transform: uppercase; letter-spacing: .08em; margin: 8px 0 4px;}}
.li-msg {{background: #0d1626; border: 1px solid {GRID}; border-radius: 8px; padding: 12px 14px;
         white-space: pre-wrap; font-size: .92rem; color: {TEXT};}}
div[data-testid="stMetricValue"] {{font-size: 1.5rem;}}
</style>
"""


def plotly_template() -> None:
    t = go.layout.Template()
    t.layout = go.Layout(
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, font=dict(color=TEXT, size=12),
        colorway=SERIES, margin=dict(l=10, r=10, t=40, b=10),
        xaxis=dict(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID, tickfont=dict(color=TEXT_2)),
        yaxis=dict(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID, tickfont=dict(color=TEXT_2)),
        hoverlabel=dict(bgcolor="#0d1626", bordercolor=GRID, font=dict(color=TEXT)),
        legend=dict(orientation="h", y=-0.15, font=dict(color=TEXT_2)),
        bargap=0.45,
    )
    pio.templates["li_dark"] = t
    pio.templates.default = "li_dark"
