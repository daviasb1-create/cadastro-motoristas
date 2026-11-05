"""Transforma resultados brutos de pesquisa em oportunidades estruturadas.

Dois motores:
- IA (Claude, saída em JSON Schema), quando ANTHROPIC_API_KEY existe;
- Heurística por palavras-chave, quando não existe (qualidade menor, declarada).

Regra central: nenhum dado sai do nada. Contatos, CNPJ e nomes só são aceitos
quando aparecem literalmente no texto da fonte.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from modules.ai import claude
from modules.search.base import RawResult
from services.textutil import (NAO_IDENTIFICADO, detect_city, detect_route, detect_ufs, domain_of, find_emails,
                               find_phones, is_company_domain, normalize_name, only_digits,
                               strip_accents)

CATEGORIAS = ["empresa", "transferencia", "urgente", "urbana", "licitacao"]
FREQUENCIAS = ["eventual", "diaria", "semanal", "recorrente", "nao_identificada"]
NIVEIS = ["explicita", "forte", "indicio", "perfil"]


@dataclass
class Extracted:
    raw: RawResult
    company_name: str
    company_website: str | None = None
    segment: str | None = None
    city: str | None = None
    state: str | None = None
    category: str = "empresa"
    service_type: str | None = None
    origin: str | None = None
    destination: str | None = None
    frequency: str = "nao_identificada"
    vehicle_types: str | None = None
    volume: str | None = None
    demand_level: str = "perfil"
    deadline: datetime | None = None
    evidence: str = ""
    summary: str = ""
    next_action: str | None = None
    contacts: list[dict] = field(default_factory=list)
    cnpj: str | None = None
    method: str = "heuristica"


# --------------------------------------------------------------------------- relevância

LOGISTICS_SIGNALS = [
    "frete", "transportadora", "transporte de carga", "transporte rodoviario", "logistic",
    "centro de distribuicao", "centro logistico", " cd ", "armazem", "galpao", "expedicao",
    "distribuicao", "last mile", "ultima milha", "entregas", "transferencia", "supply chain",
    "nova fabrica", "nova unidade", "inaugura", "expansao", "amplia", "cotacao",
    "homologacao de transportadoras", "cadastro de transportadoras", "parceiro logistico",
]
DEMAND_EXPLICIT = ["cotacao de frete", "contratar transportadora", "contratacao de transportadora",
                   "busca transportadora", "procura transportadora", "precisamos de transportadora",
                   "cadastro de transportadoras", "homologacao de transportadoras", "solicita cotacao",
                   "parceiro logistico", "contratacao de servicos de transporte", "prestacao de servicos de transporte",
                   "servico de frete", "servicos de frete"]
DEMAND_STRONG = ["novo centro de distribuicao", "novo cd", "inaugura", "nova fabrica", "nova unidade",
                 "amplia operacao", "expansao", "investimento", "novo galpao", "nova planta", "abre centro"]
JOB_SIGNALS = ["vaga", "contrata", "analista de logistica", "coordenador de transporte",
               "supervisor de expedicao", "comprador de frete", "gerente de logistica"]


def _norm(t: str) -> str:
    return " " + strip_accents((t or "").lower()) + " "


def is_relevant(r: RawResult) -> bool:
    if r.kind == "licitacao":
        return True
    t = _norm(r.title + " " + r.snippet)
    return any(sig in t for sig in LOGISTICS_SIGNALS)


# --------------------------------------------------------------------------- validação anti-invenção

def _appears(value: str | None, text: str) -> bool:
    if not value:
        return False
    nv = normalize_name(value)
    nt = normalize_name(text)
    if not nv:
        return False
    if nv in nt:
        return True
    tokens = [t for t in nv.split() if len(t) > 2]
    return bool(tokens) and all(t in nt for t in tokens)


def _evidence_ok(evidence: str, text: str) -> bool:
    words = [w for w in re.findall(r"\w+", strip_accents(evidence.lower())) if len(w) > 3]
    if not words:
        return False
    nt = strip_accents(text.lower())
    hits = sum(1 for w in words if w in nt)
    return hits / len(words) >= 0.6


def _clean(v: str | None) -> str | None:
    if v is None:
        return None
    v = str(v).strip()
    if not v or v.lower() in ("nao identificado", "não identificado", "n/a", "null", "none", "-", "desconhecido"):
        return None
    return v


def _parse_date(v: str | None) -> datetime | None:
    v = _clean(v)
    if not v:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(v[:19], fmt)
        except ValueError:
            continue
    return None


def validate_item(item: dict, raw: RawResult, method: str) -> Extracted | None:
    """Aplica as regras de não-invenção a um item vindo da IA."""
    text = f"{raw.title}\n{raw.snippet}\n{raw.extra.get('orgao', '')}\n{raw.extra.get('texto_pagina', '')}"
    name = _clean(item.get("empresa_nome"))
    if not name or not _appears(name, text):
        return None
    evidence = _clean(item.get("evidencia")) or ""
    if evidence and not _evidence_ok(evidence, text):
        evidence = ""
    if not evidence:
        evidence = raw.snippet[:400] or raw.title
    site = _clean(item.get("empresa_site"))
    if site and not (domain_of(site) and domain_of(site) in text.lower()) and raw.kind != "ia":
        site = None
    if not site and is_company_domain(domain_of(raw.url)):
        site = f"https://{domain_of(raw.url)}"
    contacts = []
    email = (_clean(item.get("contato_email")) or "").lower()
    phone = only_digits(_clean(item.get("contato_telefone")))
    lower_text = text.lower()
    email_ok = bool(email) and email in lower_text
    phone_ok = bool(phone) and phone in only_digits(text)
    cname = _clean(item.get("contato_nome"))
    if cname and not _appears(cname, text):
        cname = None
    if email_ok or phone_ok or cname:
        contacts.append({
            "name": cname, "role": _clean(item.get("contato_cargo")) if cname else None,
            "email": email if email_ok else None, "phone": phone if phone_ok else None,
            "source_name": raw.source_name, "source_url": raw.url,
        })
    cat = item.get("categoria") if item.get("categoria") in CATEGORIAS else "empresa"
    if raw.kind == "licitacao":
        cat = "licitacao"
    uf = (_clean(item.get("uf")) or "").upper()[:2] or None
    freq = item.get("frequencia") if item.get("frequencia") in FREQUENCIAS else "nao_identificada"
    level = item.get("nivel_demanda") if item.get("nivel_demanda") in NIVEIS else "perfil"
    volume = _clean(item.get("volume"))
    if volume and not any(ch.isdigit() for ch in volume):
        volume = None  # volume só com número citado na fonte
    if volume and not any(n in only_digits(text) for n in re.findall(r"\d+", volume)):
        volume = None
    return Extracted(
        raw=raw, company_name=name, company_website=site, segment=_clean(item.get("segmento")),
        city=_clean(item.get("cidade")), state=uf, category=cat,
        service_type=_clean(item.get("servico")), origin=_clean(item.get("origem")),
        destination=_clean(item.get("destino")), frequency=freq,
        vehicle_types=_clean(item.get("veiculos")), volume=volume, demand_level=level,
        deadline=_parse_date(item.get("prazo")), evidence=evidence[:1500],
        summary=_clean(item.get("resumo")) or raw.title, next_action=_clean(item.get("proxima_acao")),
        contacts=contacts, method=method,
    )


# --------------------------------------------------------------------------- IA

ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "index": {"type": "integer"},
        "relevante": {"type": "boolean"},
        "empresa_nome": {"type": "string"},
        "empresa_site": {"type": "string"},
        "segmento": {"type": "string"},
        "cidade": {"type": "string"},
        "uf": {"type": "string"},
        "categoria": {"type": "string", "enum": CATEGORIAS},
        "servico": {"type": "string"},
        "origem": {"type": "string"},
        "destino": {"type": "string"},
        "frequencia": {"type": "string", "enum": FREQUENCIAS},
        "veiculos": {"type": "string"},
        "volume": {"type": "string"},
        "nivel_demanda": {"type": "string", "enum": NIVEIS},
        "prazo": {"type": "string"},
        "evidencia": {"type": "string"},
        "resumo": {"type": "string"},
        "contato_nome": {"type": "string"},
        "contato_cargo": {"type": "string"},
        "contato_email": {"type": "string"},
        "contato_telefone": {"type": "string"},
        "proxima_acao": {"type": "string"},
    },
    "required": ["index", "relevante", "empresa_nome", "empresa_site", "segmento", "cidade", "uf",
                 "categoria", "servico", "origem", "destino", "frequencia", "veiculos", "volume",
                 "nivel_demanda", "prazo", "evidencia", "resumo", "contato_nome", "contato_cargo",
                 "contato_email", "contato_telefone", "proxima_acao"],
    "additionalProperties": False,
}
BATCH_SCHEMA = {
    "type": "object",
    "properties": {"itens": {"type": "array", "items": ITEM_SCHEMA}},
    "required": ["itens"],
    "additionalProperties": False,
}

SYSTEM_EXTRACT = """Você é analista de inteligência comercial de uma transportadora rodoviária brasileira \
(Ícaro Express) que atende principalmente Rio de Janeiro, São Paulo e Joinville (SC), com veículos de \
Fiorino a carreta, fazendo transferências entre estados e filiais, distribuição urbana e regional, \
entregas B2B, last mile, operações dedicadas e cargas volumosas.

Para cada resultado de pesquisa, decida se ele indica uma empresa (ou órgão público) que pode contratar \
esses serviços e extraia os dados.

Regras obrigatórias:
1. Use SOMENTE o que está escrito no texto do resultado. Não complete com conhecimento próprio.
2. Campo sem informação no texto: string vazia "". Nunca invente nomes, e-mails, telefones, CNPJ, \
volumes, rotas, prazos ou sites.
3. "empresa_nome" deve ser o nome como aparece no texto. Se for notícia sobre o setor sem empresa \
identificável, marque relevante=false.
4. "evidencia" deve ser um trecho copiado do texto que justifique a oportunidade.
5. nivel_demanda: "explicita" = pedido de cotação, licitação, busca declarada por transportadora; \
"forte" = novo CD, fábrica, unidade, expansão operacional; "indicio" = vagas de logística, crescimento; \
"perfil" = apenas perfil compatível.
6. categoria: "urgente" somente com demanda explícita e recente; "transferencia" quando há movimentação \
entre estados/unidades; "urbana" para entregas urbanas/last mile; "licitacao" para compras públicas; \
"empresa" nos demais casos.
7. Transportadoras concorrentes não são clientes: relevante=false (exceto se buscam agregados/parceiros \
para carga de retorno).
8. prazo no formato AAAA-MM-DD somente se a data estiver no texto.
9. proxima_acao: uma ação comercial concreta e curta.
10. Não use o caractere travessão."""


def extract_with_ai(batch: list[RawResult]) -> list[Extracted]:
    blocks = []
    for i, r in enumerate(batch):
        extra = {k: v for k, v in r.extra.items() if v and k != "texto_pagina"}
        blocks.append(
            f"<resultado index=\"{i}\">\nFonte: {r.source_name} ({r.kind})\nURL: {r.url}\n"
            f"Publicado: {r.published_at or 'não informado'}\nTítulo: {r.title}\nTrecho: {r.snippet}\n"
            f"Dados adicionais: {extra}\n</resultado>"
        )
    user = "Analise os resultados abaixo e devolva um item por resultado.\n\n" + "\n\n".join(blocks)
    data = claude.call_json(SYSTEM_EXTRACT, user, BATCH_SCHEMA, effort="low")
    if not data:
        return []
    out: list[Extracted] = []
    for item in data.get("itens", []):
        idx = item.get("index")
        if not isinstance(idx, int) or not (0 <= idx < len(batch)) or not item.get("relevante"):
            continue
        ex = validate_item(item, batch[idx], "ia")
        if ex:
            _apply_source_facts(ex)
            out.append(ex)
    return out


# --------------------------------------------------------------------------- heurística

_NEWS_VERBS = r"(inaugura|anuncia|investe|abre|amplia|constroi|constrói|lanca|lança|inicia|instala|ganha|expande|cria|contrata|recebe|terá|tera|vai abrir|vai construir|planeja)"


def _company_from_title(r: RawResult) -> str | None:
    title = r.title
    if r.extra.get("publicador") and title.endswith(" - " + r.extra["publicador"]):
        title = title[: -len(" - " + r.extra["publicador"])]
    title = re.split(r"\s[-|]\s", title)[0] if r.kind == "noticia" else title
    m = re.match(rf"^\s*(?:A |O |As |Os )?([A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9][\w&.\-]*(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9&][\w&.\-]*){{0,4}})\s+{_NEWS_VERBS}\b", title)
    if m:
        cand = m.group(1).strip()
        if normalize_name(cand) and len(cand) > 2 and cand.lower() not in ("empresa", "governo", "prefeitura"):
            return cand
    if r.kind == "vaga":
        parts = [p.strip() for p in re.split(r"\s[-|–]\s", r.title) if p.strip()]
        if len(parts) >= 2 and not any(w in parts[1].lower() for w in ("vaga", "emprego", "indeed", "linkedin", "glassdoor")):
            return parts[1]
    dom = domain_of(r.url)
    if is_company_domain(dom):
        return dom.split(".")[0].replace("-", " ").title()
    return None


def _apply_source_facts(ex: Extracted) -> None:
    """Completa campos com dados estruturados da própria fonte (PNCP etc.)."""
    r = ex.raw
    if r.kind == "licitacao":
        ex.category = "licitacao"
        ex.demand_level = "explicita"
        ex.state = ex.state or r.extra.get("uf")
        ex.city = ex.city or (r.extra.get("municipio") or "").title() or None
        if not ex.deadline and r.extra.get("encerramento"):
            try:
                ex.deadline = datetime.fromisoformat(str(r.extra["encerramento"])[:19])
            except ValueError:
                pass
        if r.extra.get("orgao_cnpj"):
            ex.cnpj = only_digits(r.extra["orgao_cnpj"])
        ex.segment = ex.segment or "Setor público"
    if not ex.city or not ex.state:
        city, uf = detect_city(f"{r.title} {r.snippet}")
        ex.city = ex.city or city
        ex.state = ex.state or uf


def extract_heuristic(r: RawResult) -> Extracted | None:
    text = f"{r.title} {r.snippet}"
    t = _norm(text)
    if r.kind == "licitacao":
        name = r.extra.get("orgao")
    else:
        name = _company_from_title(r)
    if not name:
        return None
    if any(k in t for k in DEMAND_EXPLICIT) or r.kind == "licitacao":
        level = "explicita"
    elif any(k in t for k in DEMAND_STRONG):
        level = "forte"
    elif r.kind == "vaga" or any(k in t for k in JOB_SIGNALS):
        level = "indicio"
    else:
        level = "perfil"
    origin, destination = detect_route(text)
    if r.kind == "licitacao":
        cat = "licitacao"
    elif level == "explicita":
        cat = "urgente"
    elif "transferencia" in t or (origin and destination):
        cat = "transferencia"
    elif any(k in t for k in ("last mile", "ultima milha", "entregas", "distribuicao urbana", "e-commerce", "ecommerce")):
        cat = "urbana"
    else:
        cat = "empresa"
    contacts = []
    emails = find_emails(text)
    phones = find_phones(text)
    if emails or phones:
        contacts.append({"name": None, "role": None, "email": emails[0] if emails else None,
                         "phone": phones[0] if phones else None, "source_name": r.source_name,
                         "source_url": r.url})
    dom = domain_of(r.url)
    ex = Extracted(
        raw=r, company_name=name, company_website=f"https://{dom}" if is_company_domain(dom) else None,
        category=cat, origin=origin, destination=destination, demand_level=level,
        state=None, evidence=(r.snippet or r.title)[:600], summary=r.title,
        contacts=contacts, method="heuristica",
        frequency="recorrente" if "recorrente" in t or "diari" in t else "nao_identificada",
    )
    _apply_source_facts(ex)
    return ex


# --------------------------------------------------------------------------- orquestração

def extract(results: list[RawResult], use_ai: bool, batch_size: int = 8, max_ai_calls: int = 20,
            on_error=None) -> list[Extracted]:
    """Extrai oportunidades. Itens pré-extraídos (pesquisa web da IA) passam direto."""
    out: list[Extracted] = []
    pending: list[RawResult] = []
    for r in results:
        pre = r.extra.get("pre_extraido")
        if pre:
            ex = validate_item(pre, r, "ia")
            if ex:
                _apply_source_facts(ex)
                out.append(ex)
        else:
            pending.append(r)
    calls = 0
    if use_ai and claude.available():
        for i in range(0, len(pending), batch_size):
            batch = pending[i: i + batch_size]
            if not use_ai or calls >= max_ai_calls:
                out.extend(filter(None, (extract_heuristic(r) for r in batch)))
                continue
            try:
                out.extend(extract_with_ai(batch))
                calls += 1
            except claude.AIUnavailable as exc:
                if on_error:
                    on_error(f"IA indisponível, usando heurística: {exc}")
                use_ai = False
                out.extend(filter(None, (extract_heuristic(r) for r in batch)))
        return out
    out.extend(filter(None, (extract_heuristic(r) for r in pending)))
    return out
