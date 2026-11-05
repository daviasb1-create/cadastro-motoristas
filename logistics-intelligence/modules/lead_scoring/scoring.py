"""Pontuação de leads (0 a 100), explicável e baseada em evidências.

Cada critério devolve pontos + justificativa. O tamanho da empresa NÃO pontua.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from services.textutil import detect_ufs, strip_accents
from services.timeutil import now

PRIORITY_LABELS = [
    (80, "Oportunidade prioritária"),
    (60, "Oportunidade qualificada"),
    (40, "Oportunidade em observação"),
    (0, "Baixa prioridade"),
]

VOLUMOSO = ("movel", "moveis", "eletro", "eletrodomest", "colchao", "material de construcao",
            "materiais de construcao", "equipamento", "maquina", "linha branca", "estofado")


@dataclass
class ScoreInput:
    category: str
    demand_level: str
    state: str | None = None
    city: str | None = None
    origin: str | None = None
    destination: str | None = None
    frequency: str | None = None
    vehicle_types: str | None = None
    volume: str | None = None
    segment: str | None = None
    text: str = ""
    published_at: datetime | None = None
    deadline: datetime | None = None
    has_email: bool = False
    has_phone: bool = False
    has_named_contact: bool = False
    has_website: bool = False
    is_public_tender: bool = False


def priority_label(score: int) -> str:
    for threshold, label in PRIORITY_LABELS:
        if score >= threshold:
            return label
    return PRIORITY_LABELS[-1][1]


def _uf(v: str | None) -> str | None:
    if not v:
        return None
    v = v.strip()
    if len(v) == 2 and v.isalpha():
        return v.upper()
    ufs = detect_ufs(v)
    return ufs[0] if ufs else None


def score(inp: ScoreInput, settings: dict) -> tuple[int, list[dict]]:
    served = set(settings.get("regioes", {}).get("estados", ["RJ", "SP", "SC"]))
    connected = set(settings.get("regioes", {}).get("estados_conexao", []))
    cities = [strip_accents(c.lower()) for c in settings.get("regioes", {}).get("cidades_prioritarias", [])]
    routes = [(r["origem"], r["destino"]) for r in settings.get("rotas", []) if r.get("ativa", True)]
    vehicles = [v.lower() for v in settings.get("veiculos", [])]
    t = strip_accents((inp.text or "").lower())
    o, d = _uf(inp.origin), _uf(inp.destination)
    mentioned = set(detect_ufs(inp.text or ""))
    if inp.state:
        mentioned.add(inp.state)
    parts: list[dict] = []

    def add(crit: str, pts: int, maxp: int, why: str) -> None:
        parts.append({"criterio": crit, "pontos": max(0, min(pts, maxp)), "max": maxp, "justificativa": why})

    # 1. Evidência concreta de demanda (20)
    ev = {"explicita": 20, "forte": 13, "indicio": 7, "perfil": 2}.get(inp.demand_level, 2)
    add("Evidência de demanda", ev, 20, {
        "explicita": "Demanda de transporte declarada na fonte (cotação, licitação ou busca por transportadora)",
        "forte": "Sinal operacional forte (novo CD, fábrica, unidade ou expansão)",
        "indicio": "Indício indireto (vagas de logística, crescimento)",
        "perfil": "Apenas perfil compatível, sem demanda comprovada",
    }.get(inp.demand_level, "Sem evidência"))

    # 2. Compatibilidade regional (15)
    city_hit = bool(inp.city) and strip_accents(inp.city.lower()) in cities
    if city_hit:
        add("Região atendida", 15, 15, f"Cidade prioritária: {inp.city}")
    elif mentioned & served:
        add("Região atendida", 12, 15, f"Estado atendido: {', '.join(sorted(mentioned & served))}")
    elif mentioned & connected:
        add("Região atendida", 6, 15, f"Estado com conexão operacional: {', '.join(sorted(mentioned & connected))}")
    elif not mentioned:
        add("Região atendida", 3, 15, "Localização não identificada na fonte")
    else:
        add("Região atendida", 0, 15, f"Fora da área de atuação: {', '.join(sorted(mentioned))}")

    # 3. Transferência interestadual (10)
    if o and d and o != d and (o in served and d in served):
        add("Transferência interestadual", 10, 10, f"Fluxo {o} ↔ {d} entre estados atendidos")
    elif o and d and o != d and (o in served or d in served):
        add("Transferência interestadual", 6, 10, f"Fluxo {o} ↔ {d} com uma ponta atendida")
    elif len(mentioned & served) >= 2 or "transferencia" in t or inp.category == "transferencia":
        add("Transferência interestadual", 5, 10, "Indício de movimentação entre unidades/estados")
    else:
        add("Transferência interestadual", 0, 10, "Sem indicação de transferência")

    # 4. Recorrência (10)
    freq = (inp.frequency or "").lower()
    if freq in ("diaria", "recorrente"):
        add("Potencial de recorrência", 10, 10, f"Frequência {freq} informada")
    elif freq == "semanal":
        add("Potencial de recorrência", 8, 10, "Frequência semanal informada")
    elif inp.category in ("transferencia", "urbana") or inp.demand_level == "forte":
        add("Potencial de recorrência", 5, 10, "Operação tende a ser contínua (CD/distribuição)")
    elif freq == "eventual":
        add("Potencial de recorrência", 2, 10, "Demanda eventual")
    else:
        add("Potencial de recorrência", 2, 10, "Frequência não identificada")

    # 5. Urgência (10)
    n = now()
    if inp.deadline and inp.deadline >= n:
        days = (inp.deadline - n).days
        pts = 10 if days <= 7 else 7 if days <= 15 else 4
        add("Urgência", pts, 10, f"Prazo em {days} dia(s) ({inp.deadline:%d/%m/%Y})")
    elif inp.deadline and inp.deadline < n:
        add("Urgência", 0, 10, "Prazo já encerrado")
    elif inp.published_at and (n - inp.published_at).days <= 3 and inp.demand_level == "explicita":
        add("Urgência", 8, 10, "Demanda explícita publicada há até 3 dias")
    elif inp.published_at and (n - inp.published_at).days <= 7:
        add("Urgência", 4, 10, "Publicação recente (até 7 dias)")
    else:
        add("Urgência", 1, 10, "Sem prazo identificado")

    # 6. Acesso ao contato (10)
    if inp.has_named_contact and (inp.has_email or inp.has_phone):
        add("Acesso ao contato", 10, 10, "Contato nominal com canal corporativo")
    elif inp.has_email and inp.has_phone:
        add("Acesso ao contato", 8, 10, "E-mail e telefone corporativos")
    elif inp.has_email or inp.has_phone:
        add("Acesso ao contato", 6, 10, "Um canal corporativo identificado")
    elif inp.is_public_tender:
        add("Acesso ao contato", 5, 10, "Canal oficial do edital")
    elif inp.has_website:
        add("Acesso ao contato", 2, 10, "Apenas site oficial")
    else:
        add("Acesso ao contato", 0, 10, "Nenhum canal identificado")

    # 7. Potencial de volume (10): somente com base informada ou fundamentada
    seg = strip_accents((inp.segment or "").lower())
    if inp.volume:
        add("Potencial de volume", 8, 10, f"Volume informado na fonte: {inp.volume}")
    elif inp.demand_level == "forte" and any(k in t for k in ("centro de distribuicao", " cd ", "galpao", "fabrica")):
        add("Potencial de volume", 6, 10, "Nova estrutura física (CD/fábrica) gera fluxo contínuo")
    elif any(k in t or k in seg for k in VOLUMOSO):
        add("Potencial de volume", 5, 10, "Carga volumosa compatível (móveis, eletros, construção)")
    else:
        add("Potencial de volume", 2, 10, "Volume não informado")

    # 8. Veículos compatíveis (5)
    vt = strip_accents((inp.vehicle_types or "").lower())
    if vt and any(v.lower().replace("/", "") in vt.replace("/", "") for v in vehicles):
        add("Veículos compatíveis", 5, 5, f"Veículo citado compatível com a frota: {inp.vehicle_types}")
    elif vt:
        add("Veículos compatíveis", 2, 5, f"Veículo citado: {inp.vehicle_types}")
    elif any(k in t for k in ("carga seca", "paletizad", "caixa", "volume")):
        add("Veículos compatíveis", 3, 5, "Carga geral compatível")
    else:
        add("Veículos compatíveis", 2, 5, "Tipo de veículo não informado")

    # 9. Viabilidade operacional / distância (5)
    far = mentioned and not (mentioned & (served | connected))
    if mentioned & served:
        add("Viabilidade operacional", 5, 5, "Dentro da malha atendida")
    elif mentioned & connected:
        add("Viabilidade operacional", 3, 5, "Estado vizinho/conectado")
    elif far:
        add("Viabilidade operacional", 0, 5, "Distante da operação atual")
    else:
        add("Viabilidade operacional", 2, 5, "Localização incerta")

    # 10. Aproveitamento de rotas existentes (5)
    if o and d and (o, d) in routes:
        add("Aproveitamento de rotas", 5, 5, f"Coincide com rota ativa {o} → {d}")
    elif o and d and (d, o) in routes:
        add("Aproveitamento de rotas", 4, 5, f"Possível carga de retorno {o} → {d}")
    elif mentioned & served:
        add("Aproveitamento de rotas", 2, 5, "Pode compor rotas já operadas")
    else:
        add("Aproveitamento de rotas", 0, 5, "Sem relação com rotas atuais")

    total = sum(p["pontos"] for p in parts)
    return int(max(0, min(100, total))), parts


def explain(parts: list[dict]) -> str:
    return "\n".join(f"{p['criterio']}: {p['pontos']}/{p['max']}, {p['justificativa']}" for p in parts)


def recommended_service(category: str, text: str, segment: str | None = None) -> str:
    t = strip_accents(f"{text} {segment or ''}".lower())
    if category == "transferencia":
        return "transferências recorrentes entre unidades e centros de distribuição"
    if category == "urbana" or any(k in t for k in ("e-commerce", "ecommerce", "loja virtual", "marketplace", "last mile")):
        return "distribuição urbana, entregas B2B e last mile"
    if any(k in t for k in VOLUMOSO):
        return "distribuição de cargas volumosas (móveis, eletrodomésticos e similares)"
    if category == "licitacao":
        return "prestação de serviço de transporte de cargas conforme o edital"
    if any(k in t for k in ("centro de distribuicao", " cd ", "fabrica", "nova unidade")):
        return "transporte para a nova operação, com transferências e distribuição regional"
    if category == "urgente":
        return "atendimento da demanda de frete publicada"
    return "transporte rodoviário de cargas e distribuição regional"
