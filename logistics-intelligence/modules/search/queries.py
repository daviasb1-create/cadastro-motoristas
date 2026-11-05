"""Geração das consultas a partir das Configurações (rotacionadas a cada execução)."""
from __future__ import annotations

import hashlib

from services.timeutil import now

REGION_LABELS = {"RJ": "Rio de Janeiro", "SP": "São Paulo", "SC": "Joinville"}


def _regions(settings: dict) -> list[str]:
    states = settings.get("regioes", {}).get("estados", ["RJ", "SP", "SC"])
    return [REGION_LABELS.get(uf, uf) for uf in states]


def _rotate(items: list[dict], n: int, salt: str = "") -> list[dict]:
    """Escolhe n consultas, mudando a seleção a cada janela de execução."""
    if len(items) <= n:
        return items
    slot = now().strftime("%Y%m%d%H")
    offset = int(hashlib.md5((slot + salt).encode()).hexdigest(), 16) % len(items)
    return [items[(offset + i) % len(items)] for i in range(n)]


def build_queries(settings: dict, mode: str, n: int, salt: str = "") -> list[dict]:
    """Retorna lista de {"q": consulta, "kind": tipo}."""
    p = settings.get("pesquisa", {})
    regions = _regions(settings)
    segs = settings.get("segmentos", [])[:8]
    qs: list[dict] = []
    for term in p.get("termos_demanda", []):
        for r in regions:
            qs.append({"q": f'"{term}" {r}', "kind": "cotacao"})
    qs.append({"q": '"cotação de frete" "Rio de Janeiro" "São Paulo"', "kind": "cotacao"})
    qs.append({"q": '"cotação de frete" Joinville', "kind": "cotacao"})
    qs.append({"q": '"transferência" carga "Rio de Janeiro" "Joinville" transportadora', "kind": "cotacao"})
    if mode == "urgente":
        return _rotate(qs, n, salt)
    for term in p.get("termos_expansao", []):
        for r in regions:
            qs.append({"q": f'"{term}" {r}', "kind": "noticia"})
    for term in p.get("termos_vagas", []):
        for r in regions:
            qs.append({"q": f"{term} {r}", "kind": "vaga"})
    for seg in segs:
        for r in regions:
            qs.append({"q": f"{seg} centro de distribuição {r} expansão", "kind": "noticia"})
    return _rotate(qs, n, salt)
