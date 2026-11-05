"""10. Configurações."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import select

from config import settings as cfg
from config.defaults import UFS
from database.db import all_settings, session_scope, set_setting
from database.models import Source, Template
from modules.alerts import email_alert, telegram
from modules.email_generator import outlook
from modules.search.registry import SOURCE_CLASSES


def _lines(text: str) -> list[str]:
    return [x.strip() for x in text.splitlines() if x.strip()]


def render() -> None:
    st.title("Configurações")
    s = all_settings()
    tabs = st.tabs(["Empresa e comercial", "Regiões e rotas", "Segmentos e veículos", "Score e alertas",
                    "Agenda e limites", "Pesquisa", "Fontes", "Modelos de mensagem", "Credenciais"])

    with tabs[0]:
        e, c = s["empresa"], s["comercial"]
        with st.form("f_emp"):
            st.markdown("**Dados institucionais**")
            a1, a2 = st.columns(2)
            e["nome"] = a1.text_input("Nome da empresa", e.get("nome", ""))
            e["site"] = a2.text_input("Site", e.get("site", ""))
            a3, a4, a5 = st.columns(3)
            e["telefone"] = a3.text_input("Telefone institucional", e.get("telefone", ""))
            e["email"] = a4.text_input("E-mail institucional", e.get("email", ""))
            e["cidade_base"] = a5.text_input("Cidade base", e.get("cidade_base", ""))
            e["apresentacao_curta"] = st.text_area("Apresentação curta (usada nos e-mails)", e.get("apresentacao_curta", ""), height=80)
            e["diferenciais"] = st.text_area("Diferenciais (usados nos e-mails)", e.get("diferenciais", ""), height=80)
            st.markdown("**Responsável comercial e assinatura**")
            b1, b2 = st.columns(2)
            c["nome"] = b1.text_input("Nome", c.get("nome", ""))
            c["cargo"] = b2.text_input("Cargo", c.get("cargo", ""))
            b3, b4 = st.columns(2)
            c["telefone"] = b3.text_input("Telefone/WhatsApp", c.get("telefone", ""))
            c["email"] = b4.text_input("E-mail", c.get("email", ""))
            c["assinatura"] = st.text_area("Assinatura (variáveis: {nome} {cargo} {empresa} {telefone} {email} {site})",
                                           c.get("assinatura", ""), height=110)
            if st.form_submit_button("Salvar", type="primary"):
                set_setting("empresa", e)
                set_setting("comercial", c)
                st.success("Salvo. Novas mensagens usarão estes dados (use 'Gerar/regenerar' para atualizar as existentes).")

    with tabs[1]:
        r = s["regioes"]
        with st.form("f_reg"):
            r["estados"] = st.multiselect("Estados atendidos", UFS, r.get("estados", []))
            r["estados_conexao"] = st.multiselect("Estados com conexão operacional", UFS, r.get("estados_conexao", []))
            r["cidades_prioritarias"] = _lines(st.text_area("Cidades prioritárias (uma por linha)",
                                                            "\n".join(r.get("cidades_prioritarias", [])), height=200))
            st.markdown("**Rotas de transferência**")
            routes = st.data_editor(pd.DataFrame(s["rotas"]), num_rows="dynamic", use_container_width=True,
                                    column_config={"origem": st.column_config.SelectboxColumn("Origem", options=UFS),
                                                   "destino": st.column_config.SelectboxColumn("Destino", options=UFS),
                                                   "ativa": st.column_config.CheckboxColumn("Ativa"),
                                                   "obs": st.column_config.TextColumn("Observação")})
            if st.form_submit_button("Salvar", type="primary"):
                set_setting("regioes", r)
                set_setting("rotas", [x for x in routes.fillna("").to_dict("records") if x.get("origem") and x.get("destino")])
                st.success("Salvo.")

    with tabs[2]:
        with st.form("f_seg"):
            segs = _lines(st.text_area("Segmentos de interesse (um por linha)", "\n".join(s["segmentos"]), height=260))
            veh = _lines(st.text_area("Tipos de veículo (um por linha)", "\n".join(s["veiculos"]), height=160))
            if st.form_submit_button("Salvar", type="primary"):
                set_setting("segmentos", segs)
                set_setting("veiculos", veh)
                st.success("Salvo.")

    with tabs[3]:
        sc, al = s["score"], s["alertas"]
        with st.form("f_score"):
            sc["minimo_alerta"] = st.slider("Score mínimo para alerta", 0, 100, int(sc.get("minimo_alerta", 60)), 5)
            sc["minimo_abordagem"] = st.slider("Score mínimo para gerar abordagem automática", 0, 100,
                                               int(sc.get("minimo_abordagem", 40)), 5)
            al["telegram"] = st.checkbox("Alertas por Telegram", al.get("telegram", True))
            al["email"] = st.checkbox("Alertas por e-mail (SMTP)", al.get("email", False))
            al["niveis"] = st.multiselect("Níveis que geram alerta", ["CRITICO", "ALTO", "NORMAL"], al.get("niveis", []))
            al["max_por_execucao"] = st.number_input("Máximo de alertas por execução", 1, 100, int(al.get("max_por_execucao", 15)))
            fu = s["followup"]
            st.markdown("**Prazos de follow-up (dias após o 1º contato)**")
            f1, f2, f3, f4, f5 = st.columns(5)
            d = fu.get("dias", [3, 5, 7]) + [3, 5, 7][len(fu.get("dias", [])):]
            rv = fu.get("reativacao", [15, 30]) + [15, 30][len(fu.get("reativacao", [])):]
            fu["dias"] = [f1.number_input("Follow-up 1", 1, 60, int(d[0])), f2.number_input("Follow-up 2", 1, 60, int(d[1])),
                          f3.number_input("Follow-up 3", 1, 90, int(d[2]))]
            fu["reativacao"] = [f4.number_input("Reativação 1", 1, 180, int(rv[0])), f5.number_input("Reativação 2", 1, 365, int(rv[1]))]
            if st.form_submit_button("Salvar", type="primary"):
                set_setting("score", sc)
                set_setting("alertas", al)
                set_setting("followup", fu)
                st.success("Salvo.")
        t1, t2 = st.columns(2)
        if t1.button("Enviar alerta de teste no Telegram", disabled=not telegram.configured()):
            try:
                telegram.send("✅ Teste do LOGISTICS INTELLIGENCE: alertas configurados.")
                st.success("Mensagem enviada.")
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))
        if t2.button("Enviar e-mail de teste", disabled=not email_alert.configured()):
            try:
                email_alert.send("Teste LOGISTICS INTELLIGENCE", "Alertas por e-mail configurados.")
                st.success("E-mail enviado.")
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))

    with tabs[4]:
        ag, lim = s["agenda"], s["limites"]
        with st.form("f_ag"):
            ag["pesquisas"] = _lines(st.text_area("Horários das pesquisas completas (HH:MM, um por linha)",
                                                  "\n".join(ag.get("pesquisas", [])), height=100))
            ag["monitor_urgente"] = _lines(st.text_area("Horários do monitor de urgentes", "\n".join(ag.get("monitor_urgente", [])), height=80))
            ag["max_tentativas"] = st.number_input("Tentativas em caso de falha", 1, 5, int(ag.get("max_tentativas", 3)))
            st.caption("Fuso: America/Sao_Paulo. O agendador local lê estes horários ao iniciar. No GitHub Actions, "
                       "os horários ficam no arquivo .github/workflows/radar-diario.yml.")
            st.markdown("**Controle de consumo**")
            l1, l2 = st.columns(2)
            lim["max_chamadas_ia_por_execucao"] = l1.number_input("Chamadas de IA por execução", 0, 200, int(lim.get("max_chamadas_ia_por_execucao", 20)))
            lim["max_buscas_web_ia_por_execucao"] = l2.number_input("Buscas web da IA por execução", 0, 50, int(lim.get("max_buscas_web_ia_por_execucao", 8)))
            l3, l4 = st.columns(2)
            lim["max_enriquecimentos_por_execucao"] = l3.number_input("Empresas enriquecidas por execução", 0, 200, int(lim.get("max_enriquecimentos_por_execucao", 15)))
            lim["itens_por_lote_ia"] = l4.number_input("Resultados por chamada de IA", 1, 20, int(lim.get("itens_por_lote_ia", 8)))
            if st.form_submit_button("Salvar", type="primary"):
                import re
                bad = [h for h in ag["pesquisas"] + ag["monitor_urgente"] if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", h)]
                if bad:
                    st.error("Horários inválidos: " + ", ".join(bad))
                else:
                    set_setting("agenda", ag)
                    set_setting("limites", lim)
                    st.success("Salvo. Reinicie o agendador local para aplicar novos horários.")

    with tabs[5]:
        p = s["pesquisa"]
        with st.form("f_pq"):
            p["termos_demanda"] = _lines(st.text_area("Termos de demanda explícita", "\n".join(p["termos_demanda"]), height=140))
            p["termos_expansao"] = _lines(st.text_area("Termos de expansão (notícias)", "\n".join(p["termos_expansao"]), height=140))
            p["termos_vagas"] = _lines(st.text_area("Termos de vagas (indicador de expansão)", "\n".join(p["termos_vagas"]), height=110))
            p["termos_licitacao"] = _lines(st.text_area("Palavras-chave de licitações (PNCP)", "\n".join(p["termos_licitacao"]), height=110))
            if st.form_submit_button("Salvar", type="primary"):
                set_setting("pesquisa", p)
                st.success("Salvo.")

    with tabs[6]:
        st.caption("Ative/desative fontes e defina o limite diário de chamadas. Novas fontes podem ser adicionadas em "
                   "modules/search (veja docs/ARQUITETURA.md).")
        with session_scope() as ss:
            rows = [{"key": x.key, "Fonte": x.name, "Ativa": x.enabled, "Limite diário": x.daily_limit,
                     "Credencial": "OK" if not SOURCE_CLASSES[x.key]().missing_credentials() else
                     "falta " + ", ".join(SOURCE_CLASSES[x.key]().missing_credentials()),
                     "Descrição": SOURCE_CLASSES[x.key].description, "feeds": "\n".join((x.config or {}).get("feeds", []))}
                    for x in ss.scalars(select(Source)) if x.key in SOURCE_CLASSES]
        edited = st.data_editor(pd.DataFrame(rows).drop(columns=["feeds"]), hide_index=True, use_container_width=True,
                                disabled=["key", "Fonte", "Credencial", "Descrição"], key="src_ed")
        feeds = st.text_area("Feeds RSS personalizados (um por linha; ative a fonte 'Feeds RSS personalizados')",
                             next((r["feeds"] for r in rows if r["key"] == "rss_custom"), ""), height=100)
        if st.button("Salvar fontes", type="primary"):
            with session_scope() as ss:
                for _, r in edited.iterrows():
                    src = ss.scalar(select(Source).where(Source.key == r["key"]))
                    src.enabled = bool(r["Ativa"])
                    src.daily_limit = int(r["Limite diário"])
                    if src.key == "rss_custom":
                        src.config = {**(src.config or {}), "feeds": _lines(feeds)}
            st.success("Fontes atualizadas.")

    with tabs[7]:
        st.caption("Variáveis disponíveis: {saudacao} {empresa} {servico} {contexto} {rota} {regioes} {remetente_empresa} "
                   "{apresentacao} {diferenciais} {remetente_nome} {assinatura}. WhatsApp: {saudacao_curta} {quem_fala} "
                   "{servico_curto} {contexto_curto}. A IA escolhe o modelo e adapta o texto sem inventar fatos.")
        with session_scope() as ss:
            tpls = [(t.key, t.name, t.channel, t.subject, t.body) for t in ss.scalars(select(Template).order_by(Template.id))]
        pick = st.selectbox("Modelo", tpls, format_func=lambda t: f"{t[1]} ({t[2]})")
        if pick:
            with st.form(f"tpl_{pick[0]}"):
                subj = st.text_input("Assunto", pick[3] or "", disabled=pick[2] == "whatsapp")
                body = st.text_area("Texto", pick[4], height=300)
                if st.form_submit_button("Salvar modelo", type="primary"):
                    try:
                        from modules.email_generator.generator import _SafeDict
                        body.format_map(_SafeDict())
                        subj.format_map(_SafeDict())
                    except (ValueError, IndexError) as exc:
                        st.error(f"Modelo inválido (verifique as chaves {{ }}): {exc}")
                    else:
                        with session_scope() as ss:
                            t = ss.scalar(select(Template).where(Template.key == pick[0]))
                            t.subject, t.body = subj, body
                        st.success("Modelo salvo.")

    with tabs[8]:
        st.caption("As credenciais ficam no arquivo .env desta pasta (nunca no banco). Os valores aparecem mascarados. "
                   "No GitHub Actions, cadastre-as em Settings > Secrets and variables > Actions.")
        st.dataframe(pd.DataFrame([{"Variável": k, "Uso": v, "Situação": cfg.mask(cfg.env(k))}
                                   for k, v in cfg.CREDENTIALS.items()]), hide_index=True, use_container_width=True)
        st.caption(f"Modelo da Claude em uso: {cfg.anthropic_model()} · Outlook Graph: "
                   f"{'configurado' if outlook.configured() else 'não configurado (use copiar/abrir no Outlook Web)'}")
        with st.form("f_cred", clear_on_submit=True):
            key = st.selectbox("Variável", list(cfg.CREDENTIALS) + ["ANTHROPIC_MODEL"])
            val = st.text_input("Novo valor", type="password")
            if st.form_submit_button("Gravar no .env"):
                try:
                    cfg.write_env_value(key, val.strip())
                    st.success(f"{key} gravada. Reinicie o app se a fonte não reconhecer a nova chave.")
                except ValueError as exc:
                    st.error(str(exc))
