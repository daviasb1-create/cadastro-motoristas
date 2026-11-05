"""2. Radar de empresas · 3. Radar de transferências · 4. Oportunidades urgentes."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import select

from config.defaults import OPPORTUNITY_CATEGORIES
from dashboard.components import open_lead_selector, table
from database.db import session_scope
from database.models import Route
from modules.reports.data import opportunities_df
from services.timeutil import now

BASE_COLS = ["Score", "Prioridade", "Empresa", "Categoria", "Cidade", "UF", "Segmento", "Título",
             "Evidência", "Próxima ação", "Fonte", "Link da fonte", "Encontrado em"]


def _filters(df: pd.DataFrame, key: str, with_category: bool = True) -> pd.DataFrame:
    c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
    with c1:
        ufs = sorted(u for u in df["UF"].unique() if u != "Não identificado")
        sel_uf = st.multiselect("UF", ufs, key=f"{key}_uf")
    with c2:
        min_score = st.slider("Score mínimo", 0, 100, 0, 5, key=f"{key}_score")
    with c3:
        period = st.selectbox("Período", ["Tudo", "Hoje", "7 dias", "30 dias"], key=f"{key}_per")
    with c4:
        text = st.text_input("Buscar (empresa, título, segmento)", key=f"{key}_txt")
    if with_category:
        cats = st.multiselect("Categoria", list(OPPORTUNITY_CATEGORIES.values()), key=f"{key}_cat")
        if cats:
            df = df[df["Categoria"].isin(cats)]
    if sel_uf:
        df = df[df["UF"].isin(sel_uf)]
    df = df[df["Score"] >= min_score]
    if period != "Tudo":
        days = {"Hoje": 0, "7 dias": 7, "30 dias": 30}[period]
        start = pd.Timestamp(now().date()) - pd.Timedelta(days=days)
        df = df[pd.to_datetime(df["Encontrado em"]) >= start]
    if text:
        t = text.lower()
        df = df[df["Empresa"].str.lower().str.contains(t, regex=False) | df["Título"].str.lower().str.contains(t, regex=False)
                | df["Segmento"].str.lower().str.contains(t, regex=False)]
    return df


def _score_detail(df: pd.DataFrame, key: str) -> None:
    if df.empty:
        return
    with st.expander("Ver por que cada oportunidade recebeu o score"):
        from database.models import Opportunity
        opts = df[["id", "Empresa", "Título"]].values.tolist()
        choice = st.selectbox("Oportunidade", opts, key=f"{key}_sd", format_func=lambda o: f"{o[1]}: {o[2][:80]}")
        if choice:
            with session_scope() as s:
                o = s.get(Opportunity, int(choice[0]))
                parts = o.score_breakdown or []
                st.markdown(f"**Score {o.score}/100 · {o.priority}** · extração: {o.extraction_method}")
            st.dataframe(pd.DataFrame(parts).rename(columns={"criterio": "Critério", "pontos": "Pontos", "max": "Máximo",
                                                             "justificativa": "Justificativa"}),
                         hide_index=True, use_container_width=True)


def render_companies() -> None:
    st.title("Radar de empresas")
    st.caption("Todas as empresas e oportunidades detectadas, com evidência e link da fonte.")
    df = opportunities_df()
    if df.empty:
        st.info("Sem oportunidades ainda. Execute uma pesquisa na Visão geral.")
        return
    df = df[~df["Descadastrado"]]
    df = _filters(df, "rad")
    st.caption(f"{len(df)} oportunidade(s)")
    table(df.sort_values(["Score", "Encontrado em"], ascending=False), BASE_COLS)
    _score_detail(df, "rad")
    open_lead_selector(df, "rad_open")


def render_transfers() -> None:
    st.title("Radar de transferências")
    st.caption("Empresas com movimentação entre estados, filiais e CDs (RJ ↔ SP ↔ Joinville e conexões).")
    df = opportunities_df()
    if df.empty:
        st.info("Sem oportunidades ainda.")
        return
    df = df[~df["Descadastrado"]]
    df = df[(df["categoria"] == "transferencia") | ((df["Origem"] != "Não identificado") & (df["Destino"] != "Não identificado"))]
    df = _filters(df, "trf", with_category=False)
    with session_scope() as s:
        routes = [(r.origin, r.destination, r.matches_served_route) for r in s.scalars(select(Route))]
    if routes:
        rd = pd.DataFrame(routes, columns=["Origem", "Destino", "Rota atendida"])
        agg = rd.groupby(["Origem", "Destino", "Rota atendida"]).size().reset_index(name="Ocorrências")
        st.markdown('<div class="li-section">Rotas detectadas</div>', unsafe_allow_html=True)
        st.dataframe(agg.sort_values("Ocorrências", ascending=False), hide_index=True, use_container_width=True)
    st.caption(f"{len(df)} oportunidade(s) de transferência")
    table(df.sort_values("Score", ascending=False),
          ["Score", "Empresa", "Origem", "Destino", "Frequência", "Veículos", "Volume", "UF", "Título", "Evidência",
           "Próxima ação", "Link da fonte", "Encontrado em"])
    _score_detail(df, "trf")
    open_lead_selector(df, "trf_open")


def render_urgent() -> None:
    st.title("Oportunidades urgentes")
    st.caption("Demandas explícitas (cotações, busca por transportadora) e licitações com prazo aberto.")
    df = opportunities_df()
    if df.empty:
        st.info("Sem oportunidades ainda.")
        return
    df = df[~df["Descadastrado"]]
    df = df[df["categoria"].isin(["urgente", "licitacao"]) | (df["Nível de demanda"] == "explicita")]
    show_closed = st.toggle("Mostrar prazos encerrados", value=False)
    if not show_closed:
        df = df[df["Prazo"].isna() | (pd.to_datetime(df["Prazo"]) >= pd.Timestamp(now()))]
    df = _filters(df, "urg")
    df = df.assign(_p=pd.to_datetime(df["Prazo"])).sort_values(["_p", "Score"], ascending=[True, False], na_position="last")
    st.caption(f"{len(df)} oportunidade(s)")
    table(df, ["Prazo", "Score", "Empresa", "Categoria", "Cidade", "UF", "Título", "Valor estimado (edital)",
               "Próxima ação", "Link da fonte", "Publicado em"])
    _score_detail(df, "urg")
    open_lead_selector(df, "urg_open")
