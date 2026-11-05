"""Relatório diário (texto) com resumo executivo e ações sugeridas."""
from __future__ import annotations

import html

import pandas as pd

from config import settings as cfg
from modules.reports.data import followups_df, kpis, leads_df, messages_count_today, opportunities_df
from services.timeutil import now, today


def build_daily_report() -> str:
    t = today()
    opps = opportunities_df(days=1)
    if not opps.empty:
        opps = opps[pd.to_datetime(opps["Encontrado em"]).dt.date == t]
    leads = leads_df()
    k = kpis()
    fu = followups_df()
    e = html.escape
    lines = [f"<b>📊 Relatório diário: {t:%d/%m/%Y}</b>", ""]
    n_new = len(opps)
    urg = opps[opps["categoria"].isin(["urgente", "licitacao"])] if n_new else opps
    qual = opps[opps["Score"] >= 60] if n_new else opps
    lines += [
        "<b>Resumo executivo</b>",
        f"• Novas oportunidades hoje: {n_new}",
        f"• Empresas novas hoje: {k['novos_hoje']} | Base total: {k['empresas']}",
        f"• Urgentes/licitações hoje: {len(urg)}",
        f"• Qualificadas hoje (score ≥ 60): {len(qual)}",
        f"• Mensagens geradas hoje: {messages_count_today()}",
        f"• Follow-ups vencidos: {k['followups_pendentes']}",
        f"• Em negociação: {k['negociacao']}",
    ]
    if not leads.empty:
        with_contact = leads[(leads["tem_email"] | leads["tem_telefone"]) & (pd.to_datetime(leads["Criado em"]).dt.date == t)]
        lines.append(f"• Empresas novas com contato identificado: {len(with_contact)}")
    if n_new:
        routes = opps[(opps["Origem"] != "Não identificado") & (opps["Destino"] != "Não identificado")]
        if len(routes):
            lines += ["", "<b>Rotas e operações detectadas</b>"]
            for _, r in routes.head(8).iterrows():
                lines.append(f"• {e(r['Empresa'])}: {e(r['Origem'])} → {e(r['Destino'])}")
        lines += ["", "<b>Top oportunidades do dia</b>"]
        for _, r in opps.sort_values("Score", ascending=False).head(8).iterrows():
            lines.append(f"• [{r['Score']}] {e(r['Empresa'])} ({e(str(r['UF']))}): {e(r['Título'][:120])}")
    lines += ["", "<b>Ações sugeridas para hoje</b>"]
    actions = []
    if len(urg):
        actions.append(f"Responder primeiro às {len(urg)} oportunidade(s) urgente(s)/licitação(ões).")
    if not leads.empty:
        ready = leads[(leads["Última abordagem"].isna()) & (leads["tem_email"] | leads["tem_whatsapp"]) &
                      (leads["Score"] >= 60) & (~leads["Descadastrado"])]
        if len(ready):
            actions.append(f"Enviar abordagem para {len(ready)} lead(s) qualificado(s) com contato e sem abordagem.")
        nocontact = leads[(~leads["tem_email"]) & (~leads["tem_telefone"]) & (leads["Score"] >= 60)]
        if len(nocontact):
            actions.append(f"Pesquisar contato de {len(nocontact)} lead(s) qualificado(s) sem canal identificado.")
    if k["followups_pendentes"]:
        actions.append(f"Executar {k['followups_pendentes']} follow-up(s) vencido(s) (mensagens já preparadas).")
    if not actions:
        actions.append("Sem pendências críticas. Revisar o Radar de empresas e qualificar novos leads.")
    lines += [f"{i}. {a}" for i, a in enumerate(actions, 1)]
    lines += ["", f"<i>Gerado em {now():%d/%m/%Y %H:%M} pelo LOGISTICS INTELLIGENCE</i>"]
    return "\n".join(lines)


def save_daily_report(text: str) -> str:
    import re

    path = cfg.REPORTS_DIR / f"relatorio_{today():%Y-%m-%d}.txt"
    path.write_text(re.sub(r"<[^>]+>", "", html.unescape(text)), encoding="utf-8")
    return str(path)
