"""PNCP: Portal Nacional de Contratações Públicas (API pública oficial, sem chave).

Busca contratações com propostas abertas nas UFs atendidas e filtra objetos de
transporte, frete, logística e distribuição.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from modules.search.base import BaseSource, RawResult, SearchContext
from services import http
from services.textutil import clean_text, strip_accents
from services.timeutil import now

API = "https://pncp.gov.br/api/consulta/v1/contratacoes/proposta"
# 6 = Pregão eletrônico, 8 = Dispensa de licitação, 4 = Concorrência eletrônica
MODALIDADES = (6, 8, 4)

NEGATIVE = ("transporte escolar", "passagem", "passagens aereas", "transporte de pacientes",
            "ambulancia", "transporte de passageiros", "fretamento de onibus", "locacao de veiculos com motorista para transporte de servidores",
            "vale-transporte", "vale transporte", "transporte publico")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "")[:19])
    except ValueError:
        return None


def is_cargo_object(text: str, keywords: list[str]) -> bool:
    t = strip_accents((text or "").lower())
    if any(n in t for n in NEGATIVE):
        return False
    kws = [strip_accents(k.lower()) for k in keywords]
    cargo_ctx = any(k in t for k in ("carga", "mercadoria", "material", "bens", "mudanca", "frete",
                                       "distribuicao", "logistic", "entrega", "remessa", "mobiliario",
                                       "equipamento", "insumo", "medicamento", "generos"))
    return any(k in t for k in kws) and cargo_ctx


def parse_pncp(data: dict, keywords: list[str], key: str, name: str) -> list[RawResult]:
    out = []
    for it in data.get("data") or []:
        obj = it.get("objetoCompra") or ""
        if not is_cargo_object(obj, keywords):
            continue
        org = it.get("orgaoEntidade") or {}
        uni = it.get("unidadeOrgao") or {}
        cnpj, ano, seq = org.get("cnpj"), it.get("anoCompra"), it.get("sequencialCompra")
        link = f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{seq}" if cnpj and ano and seq else (it.get("linkSistemaOrigem") or "")
        out.append(RawResult(
            source_key=key, source_name=name,
            title=clean_text(f"{it.get('modalidadeNome', 'Contratação')}: {obj}", 400),
            url=link, snippet=clean_text(obj, 1500),
            published_at=_parse_dt(it.get("dataPublicacaoPncp") or it.get("dataInclusao")),
            kind="licitacao", query="PNCP",
            extra={
                "orgao": org.get("razaoSocial"), "orgao_cnpj": cnpj, "uf": uni.get("ufSigla"),
                "municipio": uni.get("municipioNome"), "unidade": uni.get("nomeUnidade"),
                "abertura": it.get("dataAberturaProposta"), "encerramento": it.get("dataEncerramentoProposta"),
                "valor_estimado": it.get("valorTotalEstimado"), "numero_controle": it.get("numeroControlePNCP"),
                "link_origem": it.get("linkSistemaOrigem"),
            },
        ))
    return out


class PNCPSource(BaseSource):
    key = "pncp"
    name = "PNCP: Licitações públicas"
    description = "Contratações públicas com proposta aberta (transporte, frete, distribuição). Gratuito."

    def search(self, ctx: SearchContext) -> list[RawResult]:
        keywords = ctx.settings.get("pesquisa", {}).get("termos_licitacao", ["transporte", "frete"])
        ufs = ctx.settings.get("regioes", {}).get("estados", ["RJ", "SP", "SC"])
        data_final = (now() + timedelta(days=60)).strftime("%Y%m%d")
        results: list[RawResult] = []
        max_pages = int(self.config.get("paginas_por_uf", 3))
        calls_left = self.budget(len(ufs) * len(MODALIDADES) * max_pages)
        for uf in ufs:
            for mod in MODALIDADES:
                for page in range(1, max_pages + 1):
                    if calls_left <= 0:
                        return results
                    params = {"dataFinal": data_final, "codigoModalidadeContratacao": mod, "uf": uf,
                              "pagina": page, "tamanhoPagina": 50}
                    resp = http.get(API, params=params, timeout=40)
                    self.track()
                    calls_left -= 1
                    if resp.status_code == 204:
                        break
                    if resp.status_code != 200:
                        raise http.SourceUnavailable(f"PNCP HTTP {resp.status_code}")
                    data = resp.json()
                    results.extend(parse_pncp(data, keywords, self.key, self.name))
                    if not data.get("paginasRestantes"):
                        break
        return results
