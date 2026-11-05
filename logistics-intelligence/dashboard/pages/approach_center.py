"""8. Central de abordagem comercial."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.approach_panel import render_approach
from dashboard.components import table
from database.db import session_scope
from modules.crm.service import alert_lists
from modules.reports.data import leads_df
from services.timeutil import today

FILTERS = ["Todos", "Com e-mail disponível", "Com telefone disponível", "Com WhatsApp disponível",
           "Sem contato identificado", "Ainda sem abordagem", "Aguardando resposta", "Follow-up para hoje/vencido"]


def render() -> None:
    st.title("Central de abordagem comercial")
    st.caption("Todos os textos já estão prontos. Revise, copie ou abra no Outlook/WhatsApp e registre o envio. "
               "Nada é enviado automaticamente.")
    with session_scope() as s:
        al = alert_lists(s)
        counts = {k: len(v) for k, v in al.items()}
    a = st.columns(6)
    labels = [("sem_abordagem", "Sem abordagem"), ("aguardando", "Sem resposta"), ("followups_vencidos", "Follow-ups vencidos"),
              ("responderam", "Responderam"), ("cotacao", "Pediram cotação"), ("reativacao", "Reativação")]
    for col, (k, lbl) in zip(a, labels):
        col.metric(lbl, counts.get(k, 0))
    df = leads_df()
    if df.empty:
        st.info("Sem leads ainda.")
        return
    df = df[~df["Descadastrado"]]
    flt = st.radio("Filtro", FILTERS, horizontal=True, key="ac_f")
    if flt == "Com e-mail disponível":
        df = df[df["tem_email"]]
    elif flt == "Com telefone disponível":
        df = df[df["tem_telefone"]]
    elif flt == "Com WhatsApp disponível":
        df = df[df["tem_whatsapp"]]
    elif flt == "Sem contato identificado":
        df = df[~df["tem_email"] & ~df["tem_telefone"] & ~df["tem_whatsapp"]]
    elif flt == "Ainda sem abordagem":
        df = df[df["Última abordagem"].isna()]
    elif flt == "Aguardando resposta":
        df = df[df["Status"] == "Aguardando resposta"]
    elif flt == "Follow-up para hoje/vencido":
        df = df[pd.to_datetime(df["Próximo follow-up"]).dt.date <= today()]
    st.caption(f"{len(df)} lead(s)")
    table(df.sort_values("Score", ascending=False),
          ["Score", "Empresa", "Contato", "Cargo", "E-mail", "Telefone", "WhatsApp", "Serviço recomendado",
           "Assunto do e-mail", "Última abordagem", "Status", "Próximo follow-up"], height=340)
    opts = df.sort_values("Score", ascending=False)[["lead_id", "Empresa"]].values.tolist()
    pick = st.selectbox("Preparar abordagem para", [None] + opts, key="ac_pick",
                        format_func=lambda o: "Selecione um lead..." if o is None else o[1])
    if pick:
        st.markdown(f"### {pick[1]}")
        render_approach(int(pick[0]), key=f"ac{pick[0]}")
