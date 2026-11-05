"""Pesquisa na web conduzida pela Claude (ferramenta oficial web_search da Anthropic).

A Claude pesquisa, lê os resultados e devolve oportunidades estruturadas. Cada
item só é aceito se a URL de fonte informada estiver entre as URLs realmente
retornadas pela ferramenta de busca nesta execução.
"""
from __future__ import annotations

from modules.ai import claude
from modules.enrichment.extractor import ITEM_SCHEMA
from modules.search.base import BaseSource, RawResult, SearchContext
from modules.search.queries import build_queries
from services import http
from services.textutil import canonical_url, clean_text

SYSTEM = """Você é pesquisador de inteligência comercial de uma transportadora rodoviária brasileira \
(Ícaro Express) com operação em Rio de Janeiro, São Paulo e Joinville (SC): transferências entre estados \
e filiais, distribuição urbana e regional, entregas B2B, last mile, operações dedicadas e cargas volumosas, \
com veículos de Fiorino a carreta.

Sua tarefa: usar a ferramenta de pesquisa para encontrar oportunidades REAIS e RECENTES de empresas que \
possam contratar esses serviços. Priorize evidência concreta: pedidos de cotação de frete, empresas \
buscando transportadoras ou parceiros logísticos, processos de cadastro/homologação de transportadoras, \
novos centros de distribuição, fábricas ou unidades, expansão de operações, vagas de logística/transportes.

Regras:
- Cada oportunidade precisa de uma URL de fonte que você realmente abriu nos resultados.
- Não invente nada. Campo sem informação na fonte: "".
- Contatos (nome, e-mail, telefone) só se estiverem publicados na fonte e forem corporativos.
- Ignore transportadoras concorrentes e notícias sem empresa identificável.
- Não use o caractere travessão.

Ao final, responda APENAS com um bloco ```json contendo {"itens": [...]}, onde cada item tem os campos:
""" + ", ".join(ITEM_SCHEMA["properties"].keys()) + """, fonte_url, fonte_titulo, fonte_trecho.
Use index sequencial a partir de 0 e relevante=true."""


class ClaudeWebSource(BaseSource):
    key = "claude_web"
    name = "Claude: pesquisa na web"
    requires = ("ANTHROPIC_API_KEY",)
    description = "A Claude pesquisa e qualifica oportunidades com fonte verificável (custo por uso)."

    def search(self, ctx: SearchContext) -> list[RawResult]:
        if self.budget(1) <= 0:
            return []
        max_searches = int(ctx.settings.get("limites", {}).get("max_buscas_web_ia_por_execucao", 8))
        qs = build_queries(ctx.settings, ctx.mode, 6, salt=self.key)
        regions = ", ".join(ctx.settings.get("regioes", {}).get("estados", ["RJ", "SP", "SC"]))
        user = (
            f"Regiões prioritárias: {regions} (Rio de Janeiro, São Paulo e Joinville). "
            f"Modo: {'somente oportunidades urgentes publicadas nos últimos 3 dias' if ctx.mode == 'urgente' else 'oportunidades dos últimos 30 dias'}.\n"
            "Sugestões de pesquisa (adapte livremente):\n- " + "\n- ".join(q["q"] for q in qs) +
            "\n\nEncontre até 10 oportunidades distintas com a melhor evidência possível."
        )
        try:
            data, seen = claude.web_research(SYSTEM, user, max_searches=max_searches)
        except claude.AIUnavailable as exc:
            raise http.SourceUnavailable(str(exc)) from exc
        self.track()  # tokens e buscas ficam registrados em "claude"
        if not data:
            return []
        seen_canon = {canonical_url(u) for u in seen}
        out: list[RawResult] = []
        for item in (data.get("itens") if isinstance(data, dict) else data) or []:
            url = item.get("fonte_url") or ""
            if canonical_url(url) not in seen_canon:
                continue  # fonte não verificada: descartado
            snippet = clean_text(item.get("fonte_trecho") or item.get("evidencia") or "", 1500)
            r = RawResult(
                source_key=self.key, source_name=self.name,
                title=clean_text(item.get("fonte_titulo") or item.get("resumo") or "", 400),
                url=url, snippet=snippet, kind="ia", query="claude_web",
            )
            # o texto verificável inclui o que a IA citou como evidência da fonte
            r.extra["texto_pagina"] = " ".join(str(item.get(k, "")) for k in (
                "fonte_trecho", "evidencia", "empresa_nome", "empresa_site", "contato_nome",
                "contato_email", "contato_telefone"))
            r.extra["pre_extraido"] = item
            out.append(r)
        return out
