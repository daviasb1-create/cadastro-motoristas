"""Consulta de CNPJ em base pública (BrasilAPI, dados abertos da Receita Federal)."""
from __future__ import annotations

from services import http
from services.textutil import only_digits, valid_cnpj

BRASILAPI = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"


def lookup_cnpj(cnpj: str) -> dict | None:
    d = only_digits(cnpj)
    if not valid_cnpj(d):
        return None
    try:
        resp = http.get(BRASILAPI.format(cnpj=d), timeout=25)
    except http.SourceUnavailable:
        return None
    if resp.status_code != 200:
        return None
    return parse_brasilapi(resp.json())


def parse_brasilapi(data: dict) -> dict:
    addr_parts = [data.get("descricao_tipo_de_logradouro"), data.get("logradouro"), data.get("numero"),
                  data.get("complemento"), data.get("bairro")]
    address = ", ".join(str(p).strip() for p in addr_parts if p and str(p).strip())
    cep = data.get("cep")
    if cep:
        address += f", CEP {cep}"
    phone = only_digits(data.get("ddd_telefone_1") or "")
    return {
        "cnpj": only_digits(data.get("cnpj")),
        "razao_social": data.get("razao_social"),
        "nome_fantasia": data.get("nome_fantasia") or None,
        "cnae": f"{data.get('cnae_fiscal', '')} {data.get('cnae_fiscal_descricao', '')}".strip() or None,
        "situacao": data.get("descricao_situacao_cadastral"),
        "cidade": (data.get("municipio") or "").title() or None,
        "uf": data.get("uf"),
        "endereco": address or None,
        "telefone": phone if len(phone) >= 10 else None,
        "porte": data.get("porte"),
    }
