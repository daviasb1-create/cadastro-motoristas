"""5. Banco de leads + ficha completa do lead (CRM)."""
from __future__ import annotations

from datetime import datetime, time

import pandas as pd
import streamlit as st
from sqlalchemy import select

from config.defaults import CRM_STATUSES, OPPORTUNITY_CATEGORIES, UFS
from dashboard.approach_panel import render_approach
from dashboard.components import priority_pill, table
from database.db import all_settings, session_scope
from database.models import Company, Lead, Opportunity
from modules.crm import service
from modules.reports.data import leads_df
from services.textutil import format_cnpj, format_phone
from services.timeutil import fmt

LIST_COLS = ["Score", "Prioridade", "Empresa", "Status", "UF", "Cidade", "Segmento", "Contato", "E-mail",
             "Telefone", "WhatsApp", "Serviço recomendado", "Última abordagem", "Próximo follow-up", "Responsável"]


def render() -> None:
    st.title("Banco de leads")
    df = leads_df()
    lead_id = st.session_state.get("lead_id")
    if df.empty:
        st.info("Nenhum lead ainda. Execute uma pesquisa ou cadastre manualmente abaixo.")
    else:
        c1, c2, c3, c4 = st.columns([2, 1, 1, 2])
        with c1:
            sts = st.multiselect("Status", CRM_STATUSES, key="ld_st")
        with c2:
            ufs = st.multiselect("UF", sorted(u for u in df["UF"].unique() if u != "Não identificado"), key="ld_uf")
        with c3:
            ms = st.slider("Score mínimo", 0, 100, 0, 5, key="ld_sc")
        with c4:
            txt = st.text_input("Buscar empresa", key="ld_txt")
        canal = st.radio("Contato", ["Todos", "Com e-mail", "Com telefone", "Com WhatsApp", "Sem contato"],
                         horizontal=True, key="ld_canal")
        show_optout = st.toggle("Incluir descadastrados (LGPD)", value=False, key="ld_opt")
        f = df.copy()
        if not show_optout:
            f = f[~f["Descadastrado"]]
        if sts:
            f = f[f["Status"].isin(sts)]
        if ufs:
            f = f[f["UF"].isin(ufs)]
        f = f[f["Score"] >= ms]
        if txt:
            f = f[f["Empresa"].str.lower().str.contains(txt.lower(), regex=False)]
        if canal == "Com e-mail":
            f = f[f["tem_email"]]
        elif canal == "Com telefone":
            f = f[f["tem_telefone"]]
        elif canal == "Com WhatsApp":
            f = f[f["tem_whatsapp"]]
        elif canal == "Sem contato":
            f = f[~f["tem_email"] & ~f["tem_telefone"] & ~f["tem_whatsapp"]]
        st.caption(f"{len(f)} lead(s)")
        table(f.sort_values("Score", ascending=False), LIST_COLS, height=360)
        opts = f.sort_values("Score", ascending=False)[["lead_id", "Empresa"]].values.tolist()
        ids = [o[0] for o in opts]
        idx = ids.index(lead_id) + 1 if lead_id in ids else 0
        choice = st.selectbox("Abrir ficha do lead", [None] + opts, index=idx if idx < len(opts) + 1 else 0,
                              format_func=lambda o: "Selecione..." if o is None else o[1], key="ld_pick")
        if choice:
            lead_id = int(choice[0])
            st.session_state["lead_id"] = lead_id
    with st.expander("➕ Cadastrar lead manualmente"):
        _manual_form()
    if lead_id:
        st.divider()
        render_lead(int(lead_id))


def _manual_form() -> None:
    with st.form("manual_lead", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Empresa *")
        site = c2.text_input("Site")
        cnpj = c3.text_input("CNPJ")
        c4, c5, c6 = st.columns(3)
        city = c4.text_input("Cidade")
        uf = c5.selectbox("UF", [""] + UFS)
        seg = c6.text_input("Segmento")
        c7, c8, c9 = st.columns(3)
        cname = c7.text_input("Contato")
        email = c8.text_input("E-mail corporativo")
        phone = c9.text_input("Telefone/WhatsApp")
        desc = st.text_area("Oportunidade / observação", height=80)
        cat = st.selectbox("Categoria", list(OPPORTUNITY_CATEGORIES), format_func=lambda k: OPPORTUNITY_CATEGORIES[k])
        source = st.text_input("Fonte (de onde veio a informação)", value="Cadastro manual")
        if st.form_submit_button("Salvar lead") and name:
            from modules.scheduler.pipeline import score_opportunity
            from services.textutil import sha
            from services.timeutil import now
            settings = all_settings()
            with session_scope() as s:
                comp, _ = service.upsert_company(s, name=name, cnpj=cnpj or None, website=site or None, segment=seg or None,
                                                 city=city or None, state=uf or None, source=source)
                service.add_contact(s, comp, name=cname or None, email=email or None, phone=phone or None,
                                    source_name=source, source_url=None)
                opp = Opportunity(company=comp, fingerprint=sha("manual", name, desc, str(now())),
                                  title=desc[:200] or f"Cadastro manual: {name}", category=cat, description=desc,
                                  evidence=desc, demand_level="perfil" if not desc else "indicio", source_name=source,
                                  extraction_method="manual", found_at=now(), raw={"kind": "manual"})
                s.add(opp)
                s.flush()
                score_opportunity(opp, comp, settings)
                lead, _ = service.ensure_lead(s, comp)
                service.add_history(s, lead, "descoberta", f"Lead cadastrado manualmente ({source})")
                service.refresh_lead(s, lead)
                st.session_state["lead_id"] = lead.id
            st.success("Lead salvo.")
            st.rerun()


def render_lead(lead_id: int) -> None:
    settings = all_settings()
    with session_scope() as s:
        lead = s.get(Lead, lead_id)
        if lead is None:
            st.warning("Lead não encontrado.")
            return
        c = lead.company
        st.markdown(f"## {c.name}")
        st.markdown(priority_pill(lead.priority, lead.score) + f"&nbsp; <span class='li-pill'>{lead.status}</span>"
                    + ("&nbsp; <span class='li-pill' style='border-color:#e66767'>Descadastrado (LGPD)</span>" if c.opt_out else ""),
                    unsafe_allow_html=True)
        info = {
            "Razão social": c.legal_name, "CNPJ": format_cnpj(c.cnpj) if c.cnpj else None, "Segmento": c.segment,
            "CNAE": c.cnae, "Cidade/UF": f"{c.city or 'Não identificado'}/{c.state or '--'}", "Endereço": c.address,
            "Site": c.website, "LinkedIn": c.linkedin_url, "Serviço recomendado": lead.recommended_service,
            "Rotas": lead.routes, "Criado em": fmt(lead.created_at), "Última abordagem": fmt(lead.last_approach_at),
            "Próximo contato": fmt(lead.next_contact_at),
        }
        sources = c.field_sources or {}
        opps = [(o.id, o.title, o.category, o.score, o.evidence, o.source_name, o.source_url, o.found_at, o.deadline,
                 o.next_action, o.score_breakdown, o.origin, o.destination, o.extraction_method)
                for o in sorted(c.opportunities, key=lambda o: -o.score)]
        history = [(h.created_at, h.kind, h.channel, h.content, h.author) for h in lead.history]
        contacts = [(ct.id, ct.name, ct.role, ct.email, ct.phone, ct.whatsapp, ct.source_name, ct.source_url) for ct in c.contacts]
        crm = dict(status=lead.status, owner=lead.owner, pot=lead.monthly_potential, quote=lead.quote_value,
                   routes=lead.routes, loss=lead.loss_reason, nxt=lead.next_contact_at)
        company_id = c.id

    t1, t2, t3, t4, t5, t6 = st.tabs(["Resumo", "Abordagem comercial", "CRM", "Contatos", "Oportunidades", "Histórico"])
    with t1:
        rows = [{"Campo": k, "Valor": v or "Não identificado",
                 "Fonte": sources.get({"CNPJ": "cnpj", "Segmento": "segment", "Site": "website", "Endereço": "address",
                                       "Razão social": "legal_name", "CNAE": "cnae"}.get(k, ""), "")} for k, v in info.items()]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        if opps:
            o = opps[0]
            st.markdown(f"**Melhor oportunidade:** {o[1]}")
            st.markdown(f"**Evidência:** {o[4] or 'Não identificado'}")
            st.markdown(f"**Próxima ação recomendada:** {o[9] or 'Não identificado'}")
            if o[6]:
                st.markdown(f"[Abrir fonte]({o[6]}) · {o[5]} · encontrado em {fmt(o[7])}")
            st.dataframe(pd.DataFrame(o[10] or []).rename(columns={"criterio": "Critério", "pontos": "Pontos", "max": "Máx.",
                                                                   "justificativa": "Justificativa"}),
                         hide_index=True, use_container_width=True)
    with t2:
        render_approach(lead_id, key=f"lead{lead_id}")
    with t3:
        _crm_tab(lead_id, crm, settings, company_id)
    with t4:
        if contacts:
            st.dataframe(pd.DataFrame([{"Nome": n or "Não identificado", "Cargo": r or "Não identificado",
                                        "E-mail": e or "", "Telefone": format_phone(p) if p else "",
                                        "WhatsApp": format_phone(w) if w else "", "Fonte": sn or "", "Link": su or ""}
                                       for _, n, r, e, p, w, sn, su in contacts]),
                         hide_index=True, use_container_width=True,
                         column_config={"Link": st.column_config.LinkColumn("Link")})
        else:
            st.info("Nenhum contato identificado ainda.")
        with st.form(f"ct_{lead_id}", clear_on_submit=True):
            st.markdown("Adicionar contato (somente dados corporativos de fonte legítima)")
            a1, a2, a3 = st.columns(3)
            n = a1.text_input("Nome")
            r = a2.text_input("Cargo")
            e = a3.text_input("E-mail corporativo")
            a4, a5, a6 = st.columns(3)
            p = a4.text_input("Telefone")
            w = a5.text_input("WhatsApp comercial")
            src = a6.text_input("Fonte *", placeholder="ex.: site oficial, cartão de visita, ligação")
            src_url = st.text_input("Link da fonte (opcional)")
            if st.form_submit_button("Adicionar contato"):
                if not src:
                    st.error("Informe a fonte do dado (LGPD).")
                else:
                    with session_scope() as s:
                        comp = s.get(Company, company_id)
                        service.add_contact(s, comp, name=n or None, role=r or None, email=e or None, phone=p or None,
                                            whatsapp=w or None, source_name=src, source_url=src_url or None)
                        service.refresh_lead(s, comp.lead)
                        from modules.crm import approach
                        approach.generate_for_lead(s, comp.lead, settings, force=True, use_ai=False)
                    st.success("Contato adicionado e abordagem atualizada.")
                    st.rerun()
    with t5:
        for o in opps:
            with st.expander(f"[{o[3]}] {o[1][:120]}"):
                st.markdown(f"Categoria: **{OPPORTUNITY_CATEGORIES.get(o[2], o[2])}** · extração: {o[13]} · "
                            f"rota: {o[11] or 'n/i'} → {o[12] or 'n/i'} · prazo: {fmt(o[8])}")
                st.markdown(f"Evidência: {o[4] or 'Não identificado'}")
                if o[6]:
                    st.markdown(f"[Fonte: {o[5]}]({o[6]})")
    with t6:
        if history:
            st.dataframe(pd.DataFrame([{"Data": fmt(d), "Tipo": k, "Canal": ch or "", "Registro": txt, "Por": a or ""}
                                       for d, k, ch, txt, a in history]), hide_index=True, use_container_width=True)


def _crm_tab(lead_id: int, crm: dict, settings: dict, company_id: int) -> None:
    author = settings.get("comercial", {}).get("nome") or "usuário"
    with st.form(f"crm_{lead_id}"):
        c1, c2 = st.columns(2)
        status = c1.selectbox("Status", CRM_STATUSES, index=CRM_STATUSES.index(crm["status"]))
        owner = c2.text_input("Responsável comercial", crm["owner"] or settings.get("comercial", {}).get("nome", ""))
        c3, c4 = st.columns(2)
        pot = c3.number_input("Potencial de faturamento mensal (R$)", min_value=0.0, value=float(crm["pot"] or 0), step=500.0)
        quote = c4.number_input("Valor da cotação (R$)", min_value=0.0, value=float(crm["quote"] or 0), step=100.0)
        routes = st.text_input("Rotas", crm["routes"] or "")
        c5, c6 = st.columns(2)
        nxt_date = c5.date_input("Próximo contato", value=crm["nxt"].date() if crm["nxt"] else None, format="DD/MM/YYYY")
        loss = c6.text_input("Motivo de perda (se Perdido)", crm["loss"] or "")
        note = st.text_area("Nota / registro de conversa", height=80)
        kind = st.radio("Tipo do registro", ["nota", "conversa"], horizontal=True)
        if st.form_submit_button("Salvar CRM", type="primary"):
            with session_scope() as s:
                lead = s.get(Lead, lead_id)
                if status != lead.status:
                    if status == "Perdido" and not loss:
                        st.error("Informe o motivo da perda.")
                        return
                    service.change_status(s, lead, status, author=author, loss_reason=loss or None)
                lead.owner = owner or None
                lead.monthly_potential = pot or None
                lead.quote_value = quote or None
                lead.routes = routes or None
                lead.next_contact_at = datetime.combine(nxt_date, time(9, 0)) if nxt_date else None
                if note.strip():
                    service.add_history(s, lead, kind, note.strip(), author=author)
            st.success("CRM atualizado.")
            st.rerun()
    c1, c2, c3 = st.columns(3)
    with c1:
        resp = st.text_input("Resumo da resposta da empresa", key=f"resp_{lead_id}")
        if st.button("📩 Empresa respondeu", key=f"respb_{lead_id}", disabled=not resp):
            with session_scope() as s:
                service.register_response(s, s.get(Lead, lead_id), resp, author=author)
            st.rerun()
    with c2:
        if st.button("📅 Agendar follow-ups agora", key=f"fu_{lead_id}"):
            with session_scope() as s:
                service.schedule_followups(s, s.get(Lead, lead_id), settings)
            st.success("Follow-ups agendados.")
    with c3:
        reason = st.text_input("Motivo do descadastro", key=f"optr_{lead_id}")
        if st.button("🚫 Descadastrar (LGPD)", key=f"opt_{lead_id}", disabled=not reason):
            with session_scope() as s:
                service.opt_out(s, s.get(Company, company_id), reason, author=author)
            st.warning("Empresa descadastrada: abordagens e follow-ups bloqueados.")
            st.rerun()
