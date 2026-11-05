"""1. Visão geral."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import select

from dashboard.components import kpi_row
from dashboard.runner import start_manual_run
from dashboard.theme import PRIORITY_COLORS, SEQ
from database.db import session_scope
from database.models import SearchRun, Source
from modules.reports.data import kpis, leads_df, opportunities_df
from services.timeutil import fmt


def _brl(v: float) -> str:
    return "R$ " + f"{v:,.0f}".replace(",", ".")


def _bar(df: pd.DataFrame, x: str, y: str, title: str, horizontal: bool = False, color=None, keep_order: bool = False):
    if df.empty:
        st.caption(f"{title}: sem dados ainda.")
        return
    if horizontal:
        fig = px.bar(df, x=y, y=x, orientation="h", title=title, text=y)
        if keep_order:
            fig.update_yaxes(categoryorder="array", categoryarray=list(df[x])[::-1], title=None)
        else:
            fig.update_yaxes(categoryorder="total ascending", title=None)
        fig.update_xaxes(title=None)
    else:
        fig = px.bar(df, x=x, y=y, title=title, text=y)
        fig.update_xaxes(title=None)
        fig.update_yaxes(title=None)
    fig.update_traces(marker_color=color or SEQ, marker_line_width=0, textposition="outside",
                      cliponaxis=False, hovertemplate="%{label}: %{value}<extra></extra>")
    fig.update_layout(height=320, showlegend=False)
    st.plotly_chart(fig, use_container_width=True)


def render() -> None:
    st.title("Visão geral")
    with session_scope() as s:
        last = s.scalar(select(SearchRun).order_by(SearchRun.started_at.desc()))
        sources = list(s.scalars(select(Source)))
        last_info = (last.status, last.started_at, last.finished_at, last.new_opportunities) if last else None
        src_info = [(x.name, x.enabled, x.last_status, x.last_error) for x in sources]
    c1, c2, c3 = st.columns([3, 1, 1])
    with c1:
        if last_info:
            st.caption(f"Última pesquisa: **{fmt(last_info[1])}** | status **{last_info[0]}** | "
                       f"{last_info[3]} nova(s) oportunidade(s)")
        else:
            st.caption("Nenhuma pesquisa executada ainda. Clique em **Executar pesquisa agora**.")
        down = [n for n, en, stt, _ in src_info if en and stt in ("indisponivel", "erro")]
        nocred = [n for n, en, stt, _ in src_info if en and stt == "sem_credencial"]
        if down:
            st.warning("Fontes indisponíveis na última execução: " + ", ".join(down))
        if nocred:
            st.info("Fontes aguardando credencial: " + ", ".join(nocred) + " (veja Configurações > Credenciais)")
    with c2:
        if st.button("▶ Executar pesquisa agora", type="primary", use_container_width=True):
            start_manual_run("completa")
            st.success("Pesquisa iniciada em segundo plano. Acompanhe em Histórico de pesquisas.")
    with c3:
        if st.button("⚡ Só urgentes", use_container_width=True):
            start_manual_run("urgente")
            st.success("Monitor de urgentes iniciado.")

    k = kpis()
    kpi_row([("Empresas identificadas", k["empresas"], "base ativa"),
             ("Novos leads hoje", k["novos_hoje"], ""),
             ("Leads qualificados", k["qualificados"], "score ≥ 60"),
             ("Oportunidades urgentes", k["urgentes"], "inclui licitações abertas")])
    st.write("")
    kpi_row([("Transferências", k["transferencias"], "RJ · SP · SC"),
             ("Entrega urbana", k["urbanas"], "last mile / B2B"),
             ("Leads sem contato", k["sem_contato"], "pesquisar responsável"),
             ("Follow-ups vencidos", k["followups_pendentes"], "mensagens já prontas")])
    st.write("")
    kpi_row([("Em negociação", k["negociacao"], "inclui cotação enviada e teste"),
             ("Taxa de conversão", f"{k['conversao']:.1f}%", "fechados ÷ abordados"),
             ("Potencial mensal ponderado", _brl(k["potencial_ponderado"]), f"informado: {_brl(k['potencial_total'])}"),
             ("Valor de editais abertos", _brl(k["valor_editais"]), "estimativa oficial PNCP")])
    st.caption("O potencial de faturamento usa apenas valores informados por você no CRM, ponderados pela etapa do funil. "
               "O sistema não estima faturamento sem base.")

    leads = leads_df()
    opps = opportunities_df()
    if leads.empty:
        st.info("Ainda não há dados. Execute a primeira pesquisa.")
        return
    active = leads[~leads["Descadastrado"]]
    col1, col2 = st.columns(2)
    with col1:
        d = active[active["UF"] != "Não identificado"].groupby("UF").size().reset_index(name="Empresas")
        _bar(d.sort_values("Empresas", ascending=False), "UF", "Empresas", "Empresas por estado")
    with col2:
        d = active[active["Segmento"] != "Não identificado"].groupby("Segmento").size().reset_index(name="Empresas")
        _bar(d.sort_values("Empresas", ascending=False).head(10), "Segmento", "Empresas", "Empresas por segmento (top 10)", horizontal=True)
    col3, col4 = st.columns(2)
    with col3:
        order = list(PRIORITY_COLORS)
        d = active.groupby("Prioridade").size().reindex(order, fill_value=0).reset_index(name="Leads")
        fig = px.bar(d, x="Prioridade", y="Leads", title="Leads por prioridade", text="Leads",
                     color="Prioridade", color_discrete_map=PRIORITY_COLORS)
        fig.update_traces(marker_line_width=0, textposition="outside", cliponaxis=False,
                          hovertemplate="%{x}: %{y}<extra></extra>")
        fig.update_layout(height=320, showlegend=False)
        fig.update_xaxes(title=None)
        fig.update_yaxes(title=None)
        st.plotly_chart(fig, use_container_width=True)
    with col4:
        if not opps.empty:
            d = opps.groupby("Fonte").size().reset_index(name="Oportunidades")
            _bar(d.sort_values("Oportunidades", ascending=False), "Fonte", "Oportunidades", "Oportunidades por fonte", horizontal=True)
    if not opps.empty:
        col5, col6 = st.columns(2)
        ts = opps.assign(d=pd.to_datetime(opps["Encontrado em"]))
        with col5:
            w = ts.set_index("d").resample("W-MON", label="left", closed="left").size().reset_index(name="Oportunidades")
            w["Semana"] = w["d"].dt.strftime("%d/%m")
            fig = px.line(w, x="Semana", y="Oportunidades", title="Evolução semanal (oportunidades encontradas)", markers=True)
            fig.update_traces(line=dict(width=2, color=SEQ), marker=dict(size=8),
                              hovertemplate="Semana de %{x}: %{y}<extra></extra>")
            fig.update_layout(height=300)
            fig.update_xaxes(title=None)
            fig.update_yaxes(title=None, rangemode="tozero")
            st.plotly_chart(fig, use_container_width=True)
        with col6:
            m = ts.set_index("d").resample("MS").size().reset_index(name="Oportunidades")
            m["Mês"] = m["d"].dt.strftime("%m/%Y")
            _bar(m, "Mês", "Oportunidades", "Evolução mensal")
    st.markdown('<div class="li-section">Funil comercial</div>', unsafe_allow_html=True)
    from config.defaults import CRM_STATUSES
    f = active.groupby("Status").size().reindex(CRM_STATUSES, fill_value=0).reset_index(name="Leads")
    _bar(f, "Status", "Leads", "Leads por etapa", horizontal=True, keep_order=True)
