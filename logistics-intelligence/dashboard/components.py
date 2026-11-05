"""Componentes reutilizáveis da interface."""
from __future__ import annotations

import html
import json

import streamlit as st
import streamlit.components.v1 as components

from dashboard.theme import PRIORITY_COLORS


def kpi(label: str, value, hint: str = "") -> None:
    st.markdown(f'<div class="li-card"><div class="lbl">{html.escape(label)}</div>'
                f'<div class="val">{html.escape(str(value))}</div>'
                f'<div class="hint">{html.escape(hint)}</div></div>', unsafe_allow_html=True)


def kpi_row(items: list[tuple]) -> None:
    cols = st.columns(len(items))
    for col, item in zip(cols, items):
        with col:
            kpi(*item)


def priority_pill(label: str, score: int | None = None) -> str:
    color = PRIORITY_COLORS.get(label, "#6b7280")
    s = f" · {score}" if score is not None else ""
    return (f'<span class="li-pill" style="border-color:{color}"><span style="color:{color}">●</span> '
            f'{html.escape(label)}{s}</span>')


def copy_button(label: str, text: str | None, key: str, height: int = 40) -> None:
    """Botão que copia o texto para a área de transferência (com fallback)."""
    if not text:
        st.button(label, key=f"dis_{key}", disabled=True, use_container_width=True)
        return
    payload = json.dumps(text).replace("</", "<\\/")
    components.html(f"""
<button id="b" style="width:100%;padding:7px 10px;border-radius:8px;border:1px solid #2b3a52;background:#16233a;
color:#e8ecf2;font:600 13px sans-serif;cursor:pointer">{html.escape(label)}</button>
<script>
const t = {payload};
const b = document.getElementById('b');
b.onclick = async () => {{
  let ok = false;
  try {{ await navigator.clipboard.writeText(t); ok = true; }} catch (e) {{}}
  if (!ok) {{
    const ta = document.createElement('textarea'); ta.value = t; document.body.appendChild(ta);
    ta.select(); try {{ ok = document.execCommand('copy'); }} catch (e) {{}} ta.remove();
  }}
  b.innerText = ok ? '✓ Copiado' : 'Selecione e copie manualmente';
  setTimeout(() => b.innerText = {json.dumps(label)}, 2000);
}};
</script>""", height=height)


def message_box(text: str) -> None:
    st.markdown(f'<div class="li-msg">{html.escape(text)}</div>', unsafe_allow_html=True)


def open_lead_selector(df, key: str, label: str = "Abrir lead no CRM") -> None:
    """Seleciona uma empresa da tabela e navega para a ficha do lead."""
    if df is None or df.empty or "empresa_id" not in df.columns:
        return
    options = df.drop_duplicates("empresa_id")[["empresa_id", "Empresa"]].values.tolist()
    choice = st.selectbox(label, [None] + options, key=key,
                          format_func=lambda o: "Selecione..." if o is None else o[1])
    if choice and st.button("Abrir ficha", key=f"btn_{key}"):
        go_to_lead(company_id=int(choice[0]))


def go_to_lead(company_id: int | None = None, lead_id: int | None = None) -> None:
    from database.db import session_scope
    from database.models import Company, Lead

    with session_scope() as s:
        if lead_id is None and company_id is not None:
            c = s.get(Company, company_id)
            lead_id = c.lead.id if c and c.lead else None
        if lead_id is None:
            st.warning("Esta empresa ainda não possui lead.")
            return
    st.session_state["lead_id"] = lead_id
    st.session_state["nav_target"] = "5. Banco de leads"
    st.rerun()


def table(df, cols: list[str], height: int = 420) -> None:
    show = [c for c in cols if c in df.columns]
    df = df.copy()
    for c in ("Link da fonte", "Site"):
        if c in df.columns:
            df[c] = df[c].where(df[c] != "Não identificado", None)
    cfg = {}
    if "Link da fonte" in show:
        cfg["Link da fonte"] = st.column_config.LinkColumn("Link da fonte", display_text="abrir")
    if "Site" in show:
        cfg["Site"] = st.column_config.LinkColumn("Site")
    if "Score" in show:
        cfg["Score"] = st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d")
    st.dataframe(df[show], use_container_width=True, hide_index=True, height=min(height, 35 * (len(df) + 1) + 3),
                 column_config=cfg)
