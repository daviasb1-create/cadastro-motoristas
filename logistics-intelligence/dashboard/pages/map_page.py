"""7. Mapa de oportunidades."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard.theme import PRIORITY_COLORS
from modules.reports.data import opportunities_df
from services.textutil import strip_accents

CITY_COORDS = {
    "rio de janeiro": (-22.9068, -43.1729), "duque de caxias": (-22.7856, -43.3117), "nova iguacu": (-22.7592, -43.4511),
    "sao goncalo": (-22.8268, -43.0634), "niteroi": (-22.8832, -43.1034), "itaguai": (-22.8636, -43.7798),
    "queimados": (-22.7161, -43.5552), "resende": (-22.4705, -44.4509), "belford roxo": (-22.7640, -43.3994),
    "petropolis": (-22.5050, -43.1786), "volta redonda": (-22.5231, -44.1042), "macae": (-22.3708, -41.7869),
    "sao paulo": (-23.5505, -46.6333), "guarulhos": (-23.4538, -46.5333), "barueri": (-23.5112, -46.8765),
    "osasco": (-23.5329, -46.7917), "cajamar": (-23.3550, -46.8770), "jundiai": (-23.1857, -46.8978),
    "campinas": (-22.9099, -47.0626), "sao bernardo do campo": (-23.6914, -46.5646), "santo andre": (-23.6639, -46.5383),
    "embu das artes": (-23.6489, -46.8522), "sorocaba": (-23.5015, -47.4526), "santos": (-23.9608, -46.3336),
    "sao jose dos campos": (-23.2237, -45.9009), "ribeirao preto": (-21.1704, -47.8103), "louveira": (-23.0864, -46.9506),
    "itupeva": (-23.1530, -47.0578), "extrema": (-22.8550, -46.3178), "joinville": (-26.3045, -48.8487),
    "itajai": (-26.9078, -48.6619), "navegantes": (-26.8943, -48.6546), "jaragua do sul": (-26.4851, -49.0713),
    "blumenau": (-26.9194, -49.0661), "araquari": (-26.3700, -48.7220), "florianopolis": (-27.5954, -48.5480),
    "sao jose": (-27.6136, -48.6366), "itapoa": (-26.1167, -48.6167), "sao francisco do sul": (-26.2433, -48.6381),
    "curitiba": (-25.4284, -49.2733), "belo horizonte": (-19.9167, -43.9345), "vitoria": (-20.3155, -40.3128),
    "serra": (-20.1209, -40.3076), "porto alegre": (-30.0346, -51.2177),
}
OFFLINE_STYLE = {"version": 8, "sources": {},
                 "layers": [{"id": "fundo", "type": "background", "paint": {"background-color": "#111827"}}]}

UF_COORDS = {
    "RJ": (-22.25, -42.66), "SP": (-22.19, -48.79), "SC": (-27.24, -50.21), "PR": (-24.89, -51.55),
    "MG": (-18.10, -44.38), "ES": (-19.19, -40.34), "RS": (-30.03, -53.20), "BA": (-12.58, -41.70),
    "GO": (-15.98, -49.86), "DF": (-15.79, -47.88), "MS": (-20.51, -54.54), "MT": (-12.64, -55.42),
    "PE": (-8.38, -37.86), "CE": (-5.20, -39.53), "PA": (-3.79, -52.48), "AM": (-3.47, -65.10),
}


def render() -> None:
    st.title("Mapa de oportunidades")
    df = opportunities_df()
    if df.empty:
        st.info("Sem oportunidades ainda.")
        return
    df = df[~df["Descadastrado"]]
    pts = []
    for _, r in df.iterrows():
        key = strip_accents(str(r["Cidade"]).lower())
        coord, precision = CITY_COORDS.get(key), "cidade"
        if not coord and r["UF"] in UF_COORDS:
            coord, precision = UF_COORDS[r["UF"]], "estado (aproximado)"
        if coord:
            pts.append({"lat": coord[0], "lon": coord[1], "Local": f"{r['Cidade']}/{r['UF']}", "Empresa": r["Empresa"],
                        "Score": r["Score"], "Prioridade": r["Prioridade"], "Precisão": precision})
    if not pts:
        st.info("Nenhuma oportunidade com localização identificada.")
        return
    p = pd.DataFrame(pts)
    agg = p.groupby(["lat", "lon", "Local", "Precisão"]).agg(
        Oportunidades=("Empresa", "count"), Melhor_score=("Score", "max"),
        Empresas=("Empresa", lambda x: ", ".join(sorted(set(x))[:6]))).reset_index()
    agg["Prioridade"] = pd.cut(agg["Melhor_score"], [-1, 39, 59, 79, 100],
                               labels=["Baixa prioridade", "Oportunidade em observação", "Oportunidade qualificada",
                                       "Oportunidade prioritária"]).astype(str)
    style = st.radio("Fundo do mapa", ["Escuro (precisa de internet)", "Sem fundo (offline)"], horizontal=True)
    fig = px.scatter_map(agg, lat="lat", lon="lon", size="Oportunidades", color="Prioridade",
                         color_discrete_map=PRIORITY_COLORS, size_max=38, zoom=5.2, height=620,
                         center={"lat": -24.3, "lon": -46.3}, map_style="carto-darkmatter" if style.startswith("Escuro") else OFFLINE_STYLE,
                         hover_name="Local", hover_data={"Oportunidades": True, "Melhor_score": True, "Empresas": True,
                                                         "Precisão": True, "lat": False, "lon": False})
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), legend=dict(orientation="h", y=0.02, x=0.01))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Cor = melhor score da localidade. Oportunidades sem cidade conhecida aparecem no centro do estado (aproximado).")
    st.dataframe(agg.drop(columns=["lat", "lon"]).sort_values("Oportunidades", ascending=False),
                 hide_index=True, use_container_width=True)
