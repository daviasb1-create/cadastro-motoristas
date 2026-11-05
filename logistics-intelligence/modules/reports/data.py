"""Consultas em formato de tabela (pandas) usadas pelo painel e pelos relatórios."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from config.defaults import OPPORTUNITY_CATEGORIES, STAGE_PROBABILITY
from database.db import session_scope
from database.models import (Company, FollowUp, Lead, Message, Opportunity, PipelineEvent, SearchRun)
from modules.crm.service import best_contact, contact_channels
from services.textutil import NAO_IDENTIFICADO, format_cnpj, format_phone
from services.timeutil import now, today

NI = NAO_IDENTIFICADO


def _v(x):
    return x if x not in (None, "") else NI


def opportunities_df(days: int | None = None) -> pd.DataFrame:
    with session_scope() as s:
        q = select(Opportunity).options(selectinload(Opportunity.company))
        if days:
            q = q.where(Opportunity.found_at >= now() - timedelta(days=days))
        rows = []
        for o in s.scalars(q.order_by(Opportunity.found_at.desc())):
            c = o.company
            rows.append({
                "id": o.id, "empresa_id": c.id, "Empresa": c.name, "CNPJ": format_cnpj(c.cnpj) if c.cnpj else NI,
                "Segmento": _v(c.segment), "Cidade": _v(c.city), "UF": _v(c.state),
                "Categoria": OPPORTUNITY_CATEGORIES.get(o.category, o.category), "categoria": o.category,
                "Título": o.title, "Descrição": _v(o.description), "Serviço": _v(o.service_type),
                "Origem": _v(o.origin), "Destino": _v(o.destination), "Frequência": _v(o.frequency),
                "Veículos": _v(o.vehicle_types), "Volume": _v(o.volume), "Evidência": _v(o.evidence),
                "Nível de demanda": _v(o.demand_level), "Score": o.score, "Prioridade": o.priority,
                "Próxima ação": _v(o.next_action), "Fonte": o.source_name, "Link da fonte": _v(o.source_url),
                "Publicado em": o.published_at, "Prazo": o.deadline, "Encontrado em": o.found_at,
                "Método": o.extraction_method, "Valor estimado (edital)": o.estimated_value,
                "Site": _v(c.website), "Descadastrado": c.opt_out,
            })
    return pd.DataFrame(rows)


def leads_df() -> pd.DataFrame:
    with session_scope() as s:
        rows = []
        q = select(Lead).options(selectinload(Lead.company).selectinload(Company.contacts),
                                 selectinload(Lead.messages), selectinload(Lead.followups))
        for l in s.scalars(q):
            c = l.company
            ct = best_contact(c)
            ch = contact_channels(c)
            pend = sorted(f.due_date for f in l.followups if f.status == "pendente")
            email_msg = next((m for m in l.messages if m.channel == "email" and m.stage == "primeiro_contato"), None)
            wa_msg = next((m for m in l.messages if m.channel == "whatsapp" and m.stage == "primeiro_contato"), None)
            rows.append({
                "lead_id": l.id, "empresa_id": c.id, "Empresa": c.name,
                "CNPJ": format_cnpj(c.cnpj) if c.cnpj else NI, "Segmento": _v(c.segment),
                "Cidade": _v(c.city), "UF": _v(c.state), "Endereço": _v(c.address), "Site": _v(c.website),
                "LinkedIn": _v(c.linkedin_url), "Status": l.status, "Score": l.score, "Prioridade": l.priority,
                "Serviço recomendado": _v(l.recommended_service), "Responsável": _v(l.owner),
                "Contato": _v(ct.name if ct else None), "Cargo": _v(ct.role if ct else None),
                "E-mail": ch["email"][0] if ch["email"] else NI,
                "Telefone": format_phone(ch["phone"][0]) if ch["phone"] else NI,
                "WhatsApp": format_phone(ch["whatsapp"][0]) if ch["whatsapp"] else NI,
                "tem_email": bool(ch["email"]), "tem_telefone": bool(ch["phone"]), "tem_whatsapp": bool(ch["whatsapp"]),
                "Assunto do e-mail": email_msg.subject if email_msg else NI,
                "E-mail gerado": email_msg.body if email_msg else NI,
                "WhatsApp gerado": wa_msg.body if wa_msg else NI,
                "Última abordagem": l.last_approach_at, "Próximo follow-up": pend[0] if pend else None,
                "Potencial mensal (R$)": l.monthly_potential, "Valor cotação (R$)": l.quote_value,
                "Rotas": _v(l.routes), "Motivo da perda": _v(l.loss_reason), "Respondeu": l.responded,
                "Criado em": l.created_at, "Atualizado em": l.updated_at, "Descadastrado": c.opt_out,
            })
    return pd.DataFrame(rows)


def contacts_df() -> pd.DataFrame:
    with session_scope() as s:
        rows = []
        for c in s.scalars(select(Company).options(selectinload(Company.contacts))):
            if c.opt_out:
                continue
            for ct in c.contacts:
                rows.append({"Empresa": c.name, "Nome": _v(ct.name), "Cargo": _v(ct.role),
                             "Setor": _v(ct.department), "E-mail": _v(ct.email),
                             "Telefone": format_phone(ct.phone) if ct.phone else NI,
                             "WhatsApp": format_phone(ct.whatsapp) if ct.whatsapp else NI,
                             "LinkedIn": _v(ct.linkedin_url), "Fonte": _v(ct.source_name),
                             "Link da fonte": _v(ct.source_url), "Coletado em": ct.created_at})
    return pd.DataFrame(rows)


def followups_df() -> pd.DataFrame:
    with session_scope() as s:
        rows = []
        for f in s.scalars(select(FollowUp).options(selectinload(FollowUp.lead).selectinload(Lead.company))
                           .order_by(FollowUp.due_date)):
            rows.append({"lead_id": f.lead_id, "Empresa": f.lead.company.name, "Etapa": f.stage,
                         "Vencimento": f.due_date, "Situação": f.status,
                         "Vencido": f.status == "pendente" and f.due_date <= today(),
                         "Status do lead": f.lead.status})
    return pd.DataFrame(rows)


def pipeline_events_df() -> pd.DataFrame:
    with session_scope() as s:
        rows = [{"lead_id": e.lead_id, "De": e.from_status, "Para": e.to_status, "Por": e.changed_by,
                 "Data": e.created_at} for e in s.scalars(select(PipelineEvent))]
    return pd.DataFrame(rows)


def runs_df(limit: int = 200) -> pd.DataFrame:
    with session_scope() as s:
        rows = [{"id": r.id, "Início": r.started_at, "Fim": r.finished_at, "Modo": r.mode, "Origem": r.trigger,
                 "Status": r.status, "Tentativa": r.attempt, "Resultados": r.results_found,
                 "Relevantes": r.results_relevant, "Novas empresas": r.new_companies,
                 "Novas oportunidades": r.new_opportunities, "Mensagens": r.messages_generated,
                 "Alertas": r.alerts_sent, "Erros": r.errors}
                for r in s.scalars(select(SearchRun).order_by(SearchRun.started_at.desc()).limit(limit))]
    return pd.DataFrame(rows)


def kpis() -> dict:
    leads = leads_df()
    opps = opportunities_df()
    t = today()
    out = {
        "empresas": 0, "novos_hoje": 0, "qualificados": 0, "urgentes": 0, "transferencias": 0,
        "urbanas": 0, "sem_contato": 0, "followups_pendentes": 0, "negociacao": 0,
        "conversao": 0.0, "potencial_ponderado": 0.0, "potencial_total": 0.0, "valor_editais": 0.0,
    }
    if not leads.empty:
        active = leads[~leads["Descadastrado"]]
        out["empresas"] = len(active)
        out["novos_hoje"] = int((pd.to_datetime(active["Criado em"]).dt.date == t).sum())
        out["qualificados"] = int((active["Score"] >= 60).sum())
        out["sem_contato"] = int((~active["tem_email"] & ~active["tem_telefone"] & ~active["tem_whatsapp"]).sum())
        out["negociacao"] = int(active["Status"].isin(["Em negociação", "Cotação enviada", "Teste operacional"]).sum())
        contacted = active[active["Última abordagem"].notna()]
        closed = int((active["Status"] == "Contrato fechado").sum())
        out["conversao"] = (closed / len(contacted) * 100) if len(contacted) else 0.0
        pot = active["Potencial mensal (R$)"].fillna(0)
        out["potencial_total"] = float(pot[active["Status"] != "Perdido"].sum())
        out["potencial_ponderado"] = float((pot * active["Status"].map(STAGE_PROBABILITY).fillna(0)).sum())
    if not opps.empty:
        live = opps[~opps["Descadastrado"]]
        open_deadline = live["Prazo"].isna() | (pd.to_datetime(live["Prazo"]) >= pd.Timestamp(now()))
        out["urgentes"] = int((live["categoria"].isin(["urgente", "licitacao"]) & open_deadline).sum())
        out["transferencias"] = int((live["categoria"] == "transferencia").sum())
        out["urbanas"] = int((live["categoria"] == "urbana").sum())
        out["valor_editais"] = float(live.loc[live["categoria"] == "licitacao", "Valor estimado (edital)"].fillna(0).sum())
    fu = followups_df()
    if not fu.empty:
        out["followups_pendentes"] = int(((fu["Situação"] == "pendente") & fu["Vencido"]).sum())
    return out


def messages_count_today() -> int:
    with session_scope() as s:
        start = now().replace(hour=0, minute=0, second=0)
        return len(list(s.scalars(select(Message.id).where(Message.created_at >= start))))
