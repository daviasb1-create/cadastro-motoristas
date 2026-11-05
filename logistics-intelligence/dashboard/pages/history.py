"""11. Histórico de pesquisas, logs, fontes e consumo de APIs."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import select

from dashboard.runner import start_manual_run
from database.db import session_scope
from database.models import ApiUsage, ExecutionLog, Source
from modules.reports.data import runs_df
from services.timeutil import fmt
from services.usage import estimated_cost_usd


def render() -> None:
    st.title("Histórico de pesquisas")
    c1, c2, c3 = st.columns([1, 1, 3])
    if c1.button("▶ Executar agora", type="primary"):
        start_manual_run("completa")
        st.success("Pesquisa iniciada em segundo plano.")
    if c2.button("↻ Atualizar"):
        st.rerun()
    runs = runs_df()
    if runs.empty:
        st.info("Nenhuma execução registrada.")
    else:
        st.dataframe(runs, hide_index=True, use_container_width=True, height=300)
        pick = st.selectbox("Ver logs da execução", runs["id"].tolist(),
                            format_func=lambda i: f"#{i} · {fmt(runs.loc[runs['id'] == i, 'Início'].iloc[0])}")
        with session_scope() as s:
            logs = [(l.created_at, l.level, l.component, l.message) for l in
                    s.scalars(select(ExecutionLog).where(ExecutionLog.run_id == pick).order_by(ExecutionLog.id))]
        st.dataframe(pd.DataFrame(logs, columns=["Data", "Nível", "Componente", "Mensagem"]),
                     hide_index=True, use_container_width=True)
    st.markdown('<div class="li-section">Situação das fontes</div>', unsafe_allow_html=True)
    with session_scope() as s:
        src = [{"Fonte": x.name, "Ativa": x.enabled, "Último status": x.last_status or "nunca executada",
                "Última execução": fmt(x.last_run_at), "Falhas seguidas": x.consecutive_failures,
                "Limite diário": x.daily_limit, "Último erro": x.last_error or ""} for x in s.scalars(select(Source))]
        use = [(u.day, u.source_key, u.calls, u.input_tokens, u.output_tokens, u.web_searches)
               for u in s.scalars(select(ApiUsage).order_by(ApiUsage.day.desc()).limit(300))]
    st.dataframe(pd.DataFrame(src), hide_index=True, use_container_width=True)
    st.markdown('<div class="li-section">Consumo de APIs</div>', unsafe_allow_html=True)
    if use:
        u = pd.DataFrame(use, columns=["Dia", "Fonte", "Chamadas", "Tokens entrada", "Tokens saída", "Buscas web"])
        u["Custo estimado (US$)"] = [round(estimated_cost_usd(a, b, c), 4) if f == "claude" else 0.0
                                     for f, a, b, c in zip(u["Fonte"], u["Tokens entrada"], u["Tokens saída"], u["Buscas web"])]
        st.dataframe(u, hide_index=True, use_container_width=True)
        st.caption("Custo da Claude estimado com preços de referência (Opus 5.5: US$ 4/MTok entrada, US$ 20/MTok saída, "
                   "US$ 10 por mil buscas). Confira a fatura real no console da Anthropic.")
    else:
        st.caption("Sem consumo registrado.")
