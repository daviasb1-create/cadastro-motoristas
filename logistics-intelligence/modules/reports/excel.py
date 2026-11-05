"""Exportação Excel com 8 abas."""
from __future__ import annotations

from io import BytesIO

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from modules.reports.data import (contacts_df, followups_df, kpis, leads_df, opportunities_df,
                                  pipeline_events_df, runs_df)
from services.timeutil import now

HIDDEN = ["empresa_id", "lead_id", "id", "categoria", "tem_email", "tem_telefone", "tem_whatsapp"]


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame({"Info": ["Sem registros"]})
    return df.drop(columns=[c for c in HIDDEN if c in df.columns])


def _style(ws) -> None:
    fill = PatternFill("solid", fgColor="0F2A44")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = fill
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for i, col in enumerate(ws.columns, 1):
        width = max((len(str(c.value)) if c.value is not None else 0) for c in list(col)[:200])
        ws.column_dimensions[get_column_letter(i)].width = max(10, min(60, width + 2))
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def performance_df() -> pd.DataFrame:
    k = kpis()
    runs = runs_df(500)
    rows = [
        ("Empresas na base", k["empresas"]), ("Leads qualificados (score ≥ 60)", k["qualificados"]),
        ("Oportunidades urgentes/licitações abertas", k["urgentes"]),
        ("Oportunidades de transferência", k["transferencias"]), ("Oportunidades urbanas", k["urbanas"]),
        ("Leads sem contato", k["sem_contato"]), ("Follow-ups vencidos", k["followups_pendentes"]),
        ("Em negociação", k["negociacao"]), ("Taxa de conversão (%)", round(k["conversao"], 1)),
        ("Potencial mensal informado (R$)", k["potencial_total"]),
        ("Potencial mensal ponderado pelo funil (R$)", round(k["potencial_ponderado"], 2)),
        ("Valor estimado de editais abertos (R$, PNCP)", k["valor_editais"]),
        ("Pesquisas executadas", len(runs)),
        ("Pesquisas com erro", int((runs["Status"] == "erro").sum()) if not runs.empty else 0),
        ("Gerado em", now().strftime("%d/%m/%Y %H:%M")),
    ]
    return pd.DataFrame(rows, columns=["Indicador", "Valor"])


def build_workbook() -> bytes:
    opps = opportunities_df()
    leads = leads_df()
    pipe = leads[["Empresa", "Status", "Score", "Responsável", "Potencial mensal (R$)", "Valor cotação (R$)",
                  "Rotas", "Última abordagem", "Próximo follow-up", "Motivo da perda"]] if not leads.empty else leads
    sheets = {
        "Todos os leads": leads,
        "Prioritárias": opps[opps["Score"] >= 80] if not opps.empty else opps,
        "Transferências": opps[opps["categoria"] == "transferencia"] if not opps.empty else opps,
        "Entregas urbanas": opps[opps["categoria"] == "urbana"] if not opps.empty else opps,
        "Contatos identificados": contacts_df(),
        "Follow-ups": followups_df(),
        "Pipeline comercial": pipe,
        "Desempenho": performance_df(),
    }
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in sheets.items():
            _clean(df).to_excel(xw, sheet_name=name[:31], index=False)
            _style(xw.sheets[name[:31]])
        ev = pipeline_events_df()
        if not ev.empty:
            _clean(ev).to_excel(xw, sheet_name="Histórico do funil", index=False)
            _style(xw.sheets["Histórico do funil"])
    return buf.getvalue()
