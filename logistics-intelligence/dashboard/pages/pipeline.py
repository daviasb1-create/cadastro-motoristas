"""6. Pipeline comercial (visão por etapas)."""
from __future__ import annotations

import html

import streamlit as st

from config.defaults import CRM_STATUSES, STAGE_PROBABILITY
from dashboard.components import go_to_lead
from database.db import session_scope
from database.models import Lead
from modules.crm import service
from modules.reports.data import leads_df


def render() -> None:
    st.title("Pipeline comercial")
    df = leads_df()
    if df.empty:
        st.info("Sem leads ainda.")
        return
    df = df[~df["Descadastrado"]]
    hide = st.multiselect("Ocultar etapas", CRM_STATUSES, default=["Perdido"], key="pp_hide")
    stages = [s for s in CRM_STATUSES if s not in hide]
    pot = df["Potencial mensal (R$)"].fillna(0)
    st.caption(f"Potencial mensal informado no funil: R$ {pot.sum():,.0f}".replace(",", ".") +
               f" · ponderado: R$ {(pot * df['Status'].map(STAGE_PROBABILITY).fillna(0)).sum():,.0f}".replace(",", "."))
    for row_start in range(0, len(stages), 4):
        cols = st.columns(4)
        for col, stage in zip(cols, stages[row_start: row_start + 4]):
            sub = df[df["Status"] == stage].sort_values("Score", ascending=False)
            with col:
                st.markdown(f"**{stage}** · {len(sub)}")
                for _, r in sub.head(12).iterrows():
                    p = r["Potencial mensal (R$)"]
                    st.markdown(
                        f"<div class='li-card' style='margin-bottom:6px;padding:8px 10px'>"
                        f"<div style='font-weight:600'>{html.escape(r['Empresa'])}</div>"
                        f"<div class='hint'>Score {r['Score']} · {html.escape(str(r['UF']))}"
                        f"{' · R$ ' + format(p, ',.0f').replace(',', '.') if p == p and p else ''}</div></div>",
                        unsafe_allow_html=True)
                if len(sub) > 12:
                    st.caption(f"+{len(sub) - 12} lead(s)")
    st.divider()
    st.markdown("**Mover lead de etapa**")
    c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
    opts = df.sort_values("Empresa")[["lead_id", "Empresa", "Status"]].values.tolist()
    pick = c1.selectbox("Lead", opts, format_func=lambda o: f"{o[1]} ({o[2]})", key="pp_lead")
    new = c2.selectbox("Nova etapa", CRM_STATUSES, key="pp_new")
    reason = c3.text_input("Motivo (se Perdido)", key="pp_reason")
    with c4:
        st.write("")
        if st.button("Mover", type="primary", use_container_width=True):
            if new == "Perdido" and not reason:
                st.error("Informe o motivo da perda.")
            else:
                with session_scope() as s:
                    service.change_status(s, s.get(Lead, int(pick[0])), new, loss_reason=reason or None)
                st.rerun()
    if pick and st.button("Abrir ficha do lead selecionado"):
        go_to_lead(lead_id=int(pick[0]))
