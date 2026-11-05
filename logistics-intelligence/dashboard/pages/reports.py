"""9. Relatórios."""
from __future__ import annotations

import html
import re

import streamlit as st

from database.db import all_settings
from modules.alerts.dispatcher import send_daily_summary
from modules.reports.daily import build_daily_report, save_daily_report
from modules.reports.excel import build_workbook, performance_df
from services.timeutil import now


def render() -> None:
    st.title("Relatórios")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Exportação Excel** (8 abas: leads, prioritárias, transferências, entregas urbanas, "
                    "contatos, follow-ups, pipeline e desempenho)")
        if st.button("Gerar planilha"):
            st.session_state["xlsx"] = build_workbook()
        if st.session_state.get("xlsx"):
            st.download_button("⬇ Baixar Excel", st.session_state["xlsx"],
                               file_name=f"logistics_intelligence_{now():%Y%m%d_%H%M}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with c2:
        st.markdown("**Indicadores de desempenho**")
        st.dataframe(performance_df(), hide_index=True, use_container_width=True)
    st.divider()
    st.markdown("**Relatório diário**")
    text = build_daily_report()
    plain = re.sub(r"<[^>]+>", "", html.unescape(text))
    st.text(plain)
    b1, b2 = st.columns(2)
    with b1:
        if st.button("Salvar relatório em arquivo"):
            st.success(f"Salvo em {save_daily_report(text)}")
    with b2:
        if st.button("Enviar relatório para Telegram/e-mail"):
            errs = send_daily_summary(text, all_settings())
            st.error("; ".join(errs)) if errs else st.success("Enviado (para os canais configurados).")
