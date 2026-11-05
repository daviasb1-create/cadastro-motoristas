"""Painel de abordagem de um lead: e-mail + WhatsApp prontos, com botões de ação."""
from __future__ import annotations

import streamlit as st
from sqlalchemy import select

from config.defaults import FOLLOWUP_STAGES
from dashboard.components import copy_button
from database.db import all_settings, session_scope
from database.models import Lead, Message
from modules.crm import approach, service
from modules.email_generator import outlook
from modules.email_generator.generator import mailto_link, outlook_web_link
from modules.whatsapp_generator.generator import wa_link
from services.textutil import format_phone, sha
from services.timeutil import fmt


def _messages(lead_id: int, stage: str) -> dict[str, dict]:
    with session_scope() as s:
        rows = s.scalars(select(Message).where(Message.lead_id == lead_id, Message.stage == stage)).all()
        return {m.channel: {"id": m.id, "subject": m.subject, "body": m.body, "recipient": m.recipient,
                            "name": m.recipient_name, "role": m.recipient_role, "status": m.status,
                            "by": m.generated_by, "template": m.template_key, "sent_at": m.sent_at,
                            "created": m.created_at} for m in rows}


def _register(lead_id: int, channel: str, msg_id: int | None, stage: str) -> None:
    settings = all_settings()
    with session_scope() as s:
        lead = s.get(Lead, lead_id)
        service.register_contact_made(s, lead, channel, settings, message_id=msg_id, stage=stage,
                                      author=settings.get("comercial", {}).get("nome") or "usuário")
    st.success("Contato registrado. Follow-ups agendados conforme Configurações.")
    st.rerun()


def render_approach(lead_id: int, key: str = "ap") -> None:
    with session_scope() as s:
        lead = s.get(Lead, lead_id)
        if lead is None:
            st.warning("Lead não encontrado.")
            return
        company = lead.company
        opted_out = company.opt_out
        approved = lead.campaign_approved
        stages_available = ["primeiro_contato"] + [f.stage for f in sorted(lead.followups, key=lambda f: f.due_date)]
        fu_status = {f.stage: (f.status, f.due_date) for f in lead.followups}
        channels = service.contact_channels(company)
        contacts = [(c.name, c.role, c.email, c.phone, c.whatsapp, c.source_name, c.source_url) for c in company.contacts]
        templates = {t: v["name"] for t, v in approach.load_templates(s).items() if v["channel"] == "email"}
    if opted_out:
        st.error("Empresa descadastrada (LGPD). Abordagens bloqueadas.")
        return

    stage = st.selectbox(
        "Etapa da abordagem", stages_available, key=f"{key}_stage",
        format_func=lambda x: FOLLOWUP_STAGES.get(x, {}).get("label", x) + (
            f" (vence {fmt(fu_status[x][1])}, {fu_status[x][0]})" if x in fu_status else ""))
    msgs = _messages(lead_id, stage)

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        tkey = st.selectbox("Modelo", [None] + list(templates), key=f"{key}_tpl",
                            format_func=lambda k: "Escolha automática da IA/regra" if k is None else templates[k])
    with c2:
        use_ai = st.toggle("Personalizar com IA", value=True, key=f"{key}_ai",
                           help="Usa a Claude API se configurada; sem chave, usa o modelo preenchido.")
    with c3:
        if st.button("↻ Gerar/regenerar", key=f"{key}_gen", use_container_width=True):
            with session_scope() as s:
                lead = s.get(Lead, lead_id)
                created = approach.generate_for_lead(s, lead, all_settings(), stage=stage, use_ai=use_ai,
                                                     force=True, template_key=tkey)
            st.toast(f"{len(created)} mensagem(ns) atualizada(s)" if created else "Nada mudou (texto idêntico ou já enviado).")
            st.rerun()

    approved_now = st.checkbox("Revisei e aprovo esta abordagem comercial (nenhuma mensagem é enviada automaticamente)",
                               value=approved, key=f"{key}_appr")
    if approved_now != approved:
        with session_scope() as s:
            l = s.get(Lead, lead_id)
            l.campaign_approved = approved_now
            service.add_history(s, l, "sistema", "Abordagem aprovada pelo usuário" if approved_now else "Aprovação removida")
        st.rerun()

    if contacts:
        with st.expander(f"Contatos encontrados ({len(contacts)})", expanded=False):
            for name, role, email, phone, wa, src, url in contacts:
                st.markdown(f"- **{name or 'Contato institucional'}** · {role or 'cargo não identificado'} · "
                            f"{email or ''} {format_phone(phone) if phone else ''} "
                            f"{'WhatsApp ' + format_phone(wa) if wa else ''} · fonte: [{src or 'n/i'}]({url or '#'})")
    else:
        st.warning("Nenhum contato identificado. O texto está pronto, mas é preciso encontrar o responsável "
                   "(site oficial, LinkedIn da empresa ou telefone da recepção).")

    # ------------------------------------------------------------------ e-mail
    st.markdown('<div class="li-section">E-mail comercial</div>', unsafe_allow_html=True)
    em = msgs.get("email")
    if not em:
        st.info("Ainda não há e-mail para esta etapa. Clique em Gerar.")
    else:
        to_options = list(dict.fromkeys(([em["recipient"]] if em["recipient"] else []) + channels["email"]))
        to = st.selectbox("Destinatário", to_options or ["(sem e-mail identificado)"], key=f"{key}_to")
        to = to if to_options else None
        st.caption(f"Nome: {em['name'] or 'Não identificado'} · Cargo: {em['role'] or 'Não identificado'} · "
                   f"gerado por: {'IA' if em['by'] == 'ia' else 'modelo'} · status: {em['status']}"
                   + (f" em {fmt(em['sent_at'])}" if em["sent_at"] else ""))
        subject = st.text_input("Assunto", em["subject"] or "", key=f"{key}_subj_{em['id']}")
        body = st.text_area("Mensagem", em["body"], height=300, key=f"{key}_body_{em['id']}")
        if (subject != (em["subject"] or "") or body != em["body"]) and st.button("💾 Salvar edição", key=f"{key}_save"):
            with session_scope() as s:
                m = s.get(Message, em["id"])
                m.subject, m.body, m.content_hash = subject, body, sha("email", subject, body)
            st.toast("Edição salva.")
        b1, b2, b3, b4 = st.columns(4)
        with b1:
            copy_button("Copiar e-mail", to, key=f"{key}_ce")
        with b2:
            copy_button("Copiar assunto", subject, key=f"{key}_cs")
        with b3:
            copy_button("Copiar mensagem completa", body, key=f"{key}_cb")
        with b4:
            st.link_button("Abrir no Outlook", outlook_web_link(to, subject, body), use_container_width=True)
        b5, b6, b7 = st.columns(3)
        with b5:
            st.link_button("Abrir no app de e-mail (mailto)", mailto_link(to, subject, body), use_container_width=True)
        with b6:
            if outlook.configured():
                if st.button("Criar rascunho no Outlook (Graph)", key=f"{key}_draft", disabled=not (to and approved_now),
                             use_container_width=True):
                    try:
                        link = outlook.create_draft(to, subject, body)
                        with session_scope() as s:
                            s.get(Message, em["id"]).outlook_draft_id = link[:500]
                        st.success("Rascunho criado na sua caixa do Outlook (não enviado).")
                    except Exception as exc:  # noqa: BLE001
                        st.error(str(exc))
            else:
                st.button("Rascunho via Graph (não configurado)", disabled=True, key=f"{key}_nd", use_container_width=True)
        with b7:
            if st.button("✔ Registrar e-mail enviado", key=f"{key}_reg_e", disabled=not approved_now or em["status"] == "enviado",
                         use_container_width=True, help="Marque após enviar pelo Outlook."):
                _register(lead_id, "email", em["id"], stage)

    # ------------------------------------------------------------------ WhatsApp
    st.markdown('<div class="li-section">WhatsApp</div>', unsafe_allow_html=True)
    wa = msgs.get("whatsapp")
    if not wa:
        st.caption("Sem WhatsApp/celular corporativo identificado para esta empresa."
                   if not channels["whatsapp"] else "Clique em Gerar para criar a mensagem.")
    else:
        wbody = st.text_area("Mensagem WhatsApp", wa["body"], height=110, key=f"{key}_wa_{wa['id']}")
        w1, w2, w3, w4 = st.columns(4)
        with w1:
            copy_button("Copiar mensagem WhatsApp", wbody, key=f"{key}_cw")
        with w2:
            link = wa_link(wa["recipient"], wbody)
            if link:
                st.link_button("Abrir conversa no WhatsApp", link, use_container_width=True)
        with w3:
            copy_button("Copiar telefone", format_phone(wa["recipient"]), key=f"{key}_cp")
        with w4:
            if st.button("✔ Registrar contato realizado", key=f"{key}_reg_w",
                         disabled=not approved_now or wa["status"] == "enviado", use_container_width=True):
                _register(lead_id, "whatsapp", wa["id"], stage)
    if not approved_now:
        st.caption("Para registrar envios ou criar rascunhos no Outlook, marque a aprovação acima.")
