"""LOGISTICS INTELLIGENCE · Radar Comercial de Transportes

Execute:  streamlit run app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="Logistics Intelligence", page_icon="🚚", layout="wide",
                   initial_sidebar_state="expanded")

from config.settings import APP_NAME, APP_SUBTITLE  # noqa: E402
from dashboard.theme import CSS, plotly_template  # noqa: E402
from database.db import init_db  # noqa: E402


@st.cache_resource
def _boot() -> bool:
    init_db()
    plotly_template()
    return True


_boot()
plotly_template()
st.markdown(CSS, unsafe_allow_html=True)

from dashboard.pages import (approach_center, history, leads, map_page, overview, pipeline,  # noqa: E402
                             radar, reports, settings_page)

PAGES = {
    "1. Visão geral": overview.render,
    "2. Radar de empresas": radar.render_companies,
    "3. Radar de transferências": radar.render_transfers,
    "4. Oportunidades urgentes": radar.render_urgent,
    "5. Banco de leads": leads.render,
    "6. Pipeline comercial": pipeline.render,
    "7. Mapa de oportunidades": map_page.render,
    "8. Central de abordagem": approach_center.render,
    "9. Relatórios": reports.render,
    "10. Configurações": settings_page.render,
    "11. Histórico de pesquisas": history.render,
}

if "nav_target" in st.session_state:
    st.session_state["nav"] = st.session_state.pop("nav_target")

with st.sidebar:
    st.markdown(f'<div class="li-brand">🚚 {APP_NAME}</div><div class="li-sub">{APP_SUBTITLE}</div>',
                unsafe_allow_html=True)
    st.write("")
    page = st.radio("Menu", list(PAGES), key="nav", label_visibility="collapsed")
    st.divider()
    st.caption("Nenhuma mensagem é enviada automaticamente. Revise, copie e envie.")

try:
    PAGES[page]()
except Exception as exc:  # noqa: BLE001
    from services.logger import get_logger, redact
    get_logger("ui").exception("Erro na página %s", page)
    st.error(f"Ocorreu um erro nesta tela: {redact(str(exc))}. Detalhes em logs/logistics_intelligence.log.")
