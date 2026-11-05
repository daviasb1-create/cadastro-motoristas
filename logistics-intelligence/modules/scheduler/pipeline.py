"""Orquestração de uma execução do radar.

coleta (fontes) → deduplicação → extração → empresas/leads → enriquecimento →
pontuação → abordagens (rascunhos) → follow-ups → alertas → relatório
"""
from __future__ import annotations

import time
import traceback
from datetime import timedelta

from sqlalchemy import select

from database.db import all_settings, init_db, session_scope
from database.models import (Company, Lead, Message, Opportunity, Route, SearchRun, SeenItem, Source)
from modules.alerts.dispatcher import dispatch, send_daily_summary
from modules.crm import approach
from modules.crm.service import (add_contact, add_history, due_followups, ensure_lead, refresh_lead,
                                 upsert_company)
from modules.enrichment.cnpj import lookup_cnpj
from modules.enrichment.extractor import Extracted, extract, is_relevant
from modules.enrichment.website import scrape_company_site
from modules.lead_scoring.scoring import ScoreInput, priority_label, score
from modules.search.base import RawResult, SearchContext
from modules.search.registry import SOURCE_CLASSES, build_source
from services import http
from services.logger import db_log
from services.textutil import (canonical_url, detect_ufs, is_corporate_email, is_mobile, sha)
from services.timeutil import now

URGENT_SOURCES = {"pncp", "brave", "serper", "claude_web", "google_news"}


class RunStats:
    def __init__(self) -> None:
        self.found = self.relevant = self.new_companies = self.new_opps = 0
        self.messages = self.alerts = self.errors = 0
        self.ai_calls = 0
        self.sources: dict[str, dict] = {}
        self.new_opp_ids: list[int] = []


# --------------------------------------------------------------------------- coleta

def collect(run_id: int, settings: dict, mode: str, stats: RunStats) -> list[RawResult]:
    with session_scope() as s:
        sources = [(src.key, src.config or {}, src.enabled) for src in s.scalars(select(Source))]
    results: list[RawResult] = []
    max_q = 6 if mode == "urgente" else 10
    for key, conf, enabled in sources:
        if not enabled or key not in SOURCE_CLASSES:
            continue
        if mode == "urgente" and key not in URGENT_SOURCES:
            continue
        inst = build_source(key, conf)
        missing = inst.missing_credentials()
        status, error, count = "ok", None, 0
        if missing:
            status, error = "sem_credencial", "Falta configurar: " + ", ".join(missing)
        else:
            try:
                got = inst.search(SearchContext(settings=settings, mode=mode, run_id=run_id, max_queries=max_q))
                count = len(got)
                results.extend(got)
            except http.SourceUnavailable as exc:
                status, error = "indisponivel", str(exc)
                stats.errors += 1
            except Exception as exc:  # noqa: BLE001
                status, error = "erro", f"{exc.__class__.__name__}: {exc}"
                stats.errors += 1
                db_log(run_id, "ERROR", f"fonte:{key}", traceback.format_exc()[-1500:])
        with session_scope() as s:
            src = s.scalar(select(Source).where(Source.key == key))
            src.last_run_at = now()
            src.last_status = status
            src.last_error = error
            src.consecutive_failures = 0 if status in ("ok", "sem_credencial") else src.consecutive_failures + 1
        stats.sources[key] = {"status": status, "resultados": count, "erro": error}
        db_log(run_id, "INFO" if status == "ok" else "WARNING", f"fonte:{key}",
               f"{status}: {count} resultado(s)" + (f" | {error}" if error else ""))
    return results


def filter_new(results: list[RawResult], stats: RunStats) -> list[RawResult]:
    unique: dict[str, RawResult] = {}
    for r in results:
        if r.url or r.title:
            unique.setdefault(r.fingerprint, r)
    stats.found = len(unique)
    with session_scope() as s:
        seen = set(s.scalars(select(SeenItem.fingerprint).where(SeenItem.fingerprint.in_(list(unique)))))
        fresh = [r for fp, r in unique.items() if fp not in seen]
        relevant = []
        for r in fresh:
            rel = is_relevant(r)
            s.add(SeenItem(fingerprint=r.fingerprint, source_key=r.source_key, url=r.url[:1000],
                           title=r.title[:500], relevant=rel))
            if rel:
                relevant.append(r)
    stats.relevant = len(relevant)
    return relevant


# --------------------------------------------------------------------------- persistência

def _default_next_action(ex: Extracted, has_contact: bool) -> str:
    if ex.category == "licitacao":
        return "Ler o edital, verificar habilitação exigida e registrar proposta antes do prazo."
    if ex.demand_level == "explicita":
        return "Responder à demanda publicada hoje com pedido de detalhes da carga e prazo."
    if not has_contact:
        return "Identificar responsável por logística/compras (site oficial ou LinkedIn da empresa)."
    if ex.demand_level == "forte":
        return "Enviar apresentação mencionando a nova operação e propor conversa de 15 minutos."
    return "Enviar e-mail de apresentação e registrar o contato."


def score_opportunity(opp: Opportunity, company: Company, settings: dict) -> None:
    contacts = company.contacts
    inp = ScoreInput(
        category=opp.category, demand_level=opp.demand_level or "perfil", state=company.state,
        city=company.city, origin=opp.origin, destination=opp.destination, frequency=opp.frequency,
        vehicle_types=opp.vehicle_types, volume=opp.volume, segment=company.segment,
        text=f"{opp.title} {opp.description or ''} {opp.evidence or ''}",
        published_at=opp.published_at, deadline=opp.deadline,
        has_email=any(c.email and is_corporate_email(c.email, company.domain) for c in contacts),
        has_phone=any(c.phone or c.whatsapp for c in contacts),
        has_named_contact=any(c.name and (c.email or c.phone) for c in contacts),
        has_website=bool(company.website), is_public_tender=opp.category == "licitacao",
    )
    total, parts = score(inp, settings)
    opp.score = total
    opp.score_breakdown = parts
    opp.priority = priority_label(total)


def persist(run_id: int, items: list[Extracted], settings: dict, stats: RunStats) -> set[int]:
    touched: set[int] = set()
    for ex in items:
        try:
            with session_scope() as s:
                company, created = upsert_company(
                    s, name=ex.company_name, cnpj=ex.cnpj, website=ex.company_website, segment=ex.segment,
                    city=ex.city, state=ex.state, source=ex.raw.url or ex.raw.source_name)
                if company.opt_out:
                    continue
                for c in ex.contacts:
                    add_contact(s, company, **c)
                fp = sha(canonical_url(ex.raw.url), company.normalized_name, ex.category)
                if s.scalar(select(Opportunity.id).where(Opportunity.fingerprint == fp)):
                    continue
                opp = Opportunity(
                    company=company, fingerprint=fp, title=ex.raw.title[:500] or ex.summary[:500],
                    category=ex.category, service_type=ex.service_type, origin=ex.origin,
                    destination=ex.destination, frequency=ex.frequency, vehicle_types=ex.vehicle_types,
                    volume=ex.volume, description=ex.summary, evidence=ex.evidence,
                    demand_level=ex.demand_level, source_name=ex.raw.source_name, source_url=ex.raw.url,
                    published_at=ex.raw.published_at, deadline=ex.deadline, found_at=now(),
                    extraction_method=ex.method, run_id=run_id,
                    next_action=ex.next_action or _default_next_action(ex, bool(ex.contacts)),
                    estimated_value=_float(ex.raw.extra.get("valor_estimado")),
                    raw={"kind": ex.raw.kind, "query": ex.raw.query,
                         **{k: v for k, v in ex.raw.extra.items() if k not in ("pre_extraido", "texto_pagina") and v is not None}},
                )
                s.add(opp)
                s.flush()
                score_opportunity(opp, company, settings)
                if opp.origin and opp.destination:
                    routes = {(r["origem"], r["destino"]) for r in settings.get("rotas", [])}
                    o = (detect_ufs(opp.origin) or [opp.origin])[0]
                    d = (detect_ufs(opp.destination) or [opp.destination])[0]
                    s.add(Route(opportunity_id=opp.id, origin=opp.origin[:120], destination=opp.destination[:120],
                                matches_served_route=(o, d) in routes))
                lead, lead_created = ensure_lead(s, company)
                add_history(s, lead, "descoberta",
                            f"Nova oportunidade ({ex.category}, score {opp.score}): {opp.title} | Fonte: {opp.source_url or opp.source_name}",
                            author="sistema")
                refresh_lead(s, lead)
                stats.new_opps += 1
                stats.new_companies += int(created)
                stats.new_opp_ids.append(opp.id)
                touched.add(company.id)
        except Exception as exc:  # noqa: BLE001
            stats.errors += 1
            db_log(run_id, "ERROR", "persistencia", f"{ex.company_name}: {exc.__class__.__name__}: {exc}")
    return touched


def _float(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- enriquecimento

def enrich(run_id: int, company_ids: set[int], settings: dict, stats: RunStats) -> None:
    limit = int(settings.get("limites", {}).get("max_enriquecimentos_por_execucao", 15))
    with session_scope() as s:
        q = select(Company.id).where(Company.opt_out.is_(False), Company.enriched_at.is_(None))
        pending = list(company_ids) + [cid for cid in s.scalars(q.limit(limit * 2)) if cid not in company_ids]
    for cid in pending[:limit]:
        try:
            with session_scope() as s:
                company = s.get(Company, cid)
                if company is None or company.opt_out:
                    continue
                website = company.website
                cnpj = company.cnpj
            site_data = scrape_company_site(website) if website else None
            cnpj_data = None
            if not cnpj and site_data and site_data["cnpjs"]:
                cnpj = next(iter(site_data["cnpjs"]))
            if cnpj:
                cnpj_data = lookup_cnpj(cnpj)
            with session_scope() as s:
                company = s.get(Company, cid)
                if site_data:
                    for email, url in list(site_data["emails"].items())[:4]:
                        add_contact(s, company, email=email, department=email.split("@")[0],
                                    source_name="Site oficial", source_url=url)
                    for phone, url in list(site_data["phones"].items())[:3]:
                        add_contact(s, company, phone=phone, whatsapp=None, source_name="Site oficial", source_url=url)
                    for wa, url in list(site_data["whatsapp"].items())[:2]:
                        add_contact(s, company, whatsapp=wa, source_name="Site oficial (link WhatsApp)", source_url=url)
                    if site_data["linkedin"] and not company.linkedin_url:
                        company.linkedin_url = next(iter(site_data["linkedin"]))
                if cnpj_data and cnpj_data.get("cnpj"):
                    from modules.crm.service import _set_if_empty
                    clash = s.scalar(select(Company.id).where(Company.cnpj == cnpj_data["cnpj"], Company.id != company.id))
                    if not clash:
                        src = f"BrasilAPI/Receita Federal (CNPJ {cnpj_data['cnpj']})"
                        _set_if_empty(company, "cnpj", cnpj_data["cnpj"], src)
                        _set_if_empty(company, "legal_name", cnpj_data.get("razao_social"), src)
                        _set_if_empty(company, "cnae", cnpj_data.get("cnae"), src)
                        _set_if_empty(company, "address", cnpj_data.get("endereco"), src)
                        _set_if_empty(company, "city", cnpj_data.get("cidade"), src)
                        _set_if_empty(company, "state", cnpj_data.get("uf"), src)
                        if cnpj_data.get("telefone"):
                            add_contact(s, company, phone=cnpj_data["telefone"], source_name="Cadastro CNPJ (Receita Federal)",
                                        source_url=f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_data['cnpj']}")
                company.enriched_at = now()
                s.flush()
                for opp in company.opportunities:
                    score_opportunity(opp, company, settings)
                if company.lead:
                    refresh_lead(s, company.lead)
        except Exception as exc:  # noqa: BLE001
            stats.errors += 1
            db_log(run_id, "WARNING", "enriquecimento", f"empresa {cid}: {exc.__class__.__name__}: {exc}")


# --------------------------------------------------------------------------- abordagem e follow-up

def prepare_approaches(run_id: int, settings: dict, stats: RunStats) -> None:
    lim = settings.get("limites", {})
    budget = max(0, int(lim.get("max_chamadas_ia_por_execucao", 20)) - stats.ai_calls)
    min_score = int(settings.get("score", {}).get("minimo_abordagem", 40))
    with session_scope() as s:
        has_first = select(Message.lead_id).where(Message.stage == "primeiro_contato", Message.channel == "email")
        leads = list(s.scalars(select(Lead).join(Company).where(
            Company.opt_out.is_(False), Lead.score >= min_score, Lead.id.not_in(has_first),
            Lead.status.not_in(["Perdido", "Contrato fechado"])).order_by(Lead.score.desc()).limit(60)))
        for lead in leads:
            use_ai = budget > 0
            try:
                created = approach.generate_for_lead(s, lead, settings, use_ai=use_ai)
            except Exception as exc:  # noqa: BLE001
                db_log(run_id, "WARNING", "abordagem", f"lead {lead.id}: {exc}")
                continue
            if any(m.generated_by == "ia" for m in created):
                budget -= 1
                stats.ai_calls += 1
            stats.messages += len(created)
        for fu in due_followups(s):
            try:
                created = approach.generate_for_lead(s, fu.lead, settings, stage=fu.stage, use_ai=budget > 0)
                if any(m.generated_by == "ia" for m in created):
                    budget -= 1
                stats.messages += len(created)
            except Exception as exc:  # noqa: BLE001
                db_log(run_id, "WARNING", "followup", f"lead {fu.lead_id}: {exc}")


# --------------------------------------------------------------------------- execução

def _running_elsewhere() -> bool:
    with session_scope() as s:
        cutoff = now() - timedelta(hours=2)
        return bool(s.scalar(select(SearchRun.id).where(SearchRun.status == "executando",
                                                         SearchRun.started_at >= cutoff)))


def run_pipeline(mode: str = "completa", trigger: str = "manual", attempt: int = 1) -> dict:
    init_db()
    if _running_elsewhere():
        return {"status": "ignorado", "motivo": "Já existe uma pesquisa em execução"}
    settings = all_settings()
    with session_scope() as s:
        run = SearchRun(mode=mode, trigger=trigger, attempt=attempt, status="executando", started_at=now())
        s.add(run)
        s.flush()
        run_id = run.id
    stats = RunStats()
    status = "ok"
    db_log(run_id, "INFO", "pipeline", f"Início da pesquisa ({mode}, {trigger}, tentativa {attempt})")
    try:
        raw = collect(run_id, settings, mode, stats)
        fresh = filter_new(raw, stats)
        lim = settings.get("limites", {})
        extracted = extract(fresh, use_ai=True, batch_size=int(lim.get("itens_por_lote_ia", 8)),
                            max_ai_calls=int(lim.get("max_chamadas_ia_por_execucao", 20)),
                            on_error=lambda m: db_log(run_id, "WARNING", "extracao", m))
        from modules.ai import claude as _claude
        if _claude.available():
            stats.ai_calls += (len(fresh) + int(lim.get("itens_por_lote_ia", 8)) - 1) // max(1, int(lim.get("itens_por_lote_ia", 8)))
        db_log(run_id, "INFO", "extracao", f"{len(extracted)} oportunidade(s) extraída(s) de {len(fresh)} resultado(s) novos e relevantes")
        touched = persist(run_id, extracted, settings, stats)
        if mode == "completa":
            enrich(run_id, touched, settings, stats)
        prepare_approaches(run_id, settings, stats)
        with session_scope() as s:
            opps = list(s.scalars(select(Opportunity).where(Opportunity.id.in_(stats.new_opp_ids))))
            sent, alert_errors = dispatch(s, opps, settings)
            stats.alerts = sent
            for e in alert_errors:
                db_log(run_id, "WARNING", "alertas", e)
        working = [k for k, v in stats.sources.items() if v["status"] == "ok"]
        if not working:
            status = "erro"
        elif stats.errors:
            status = "parcial"
    except Exception as exc:  # noqa: BLE001
        status = "erro"
        stats.errors += 1
        db_log(run_id, "ERROR", "pipeline", f"{exc.__class__.__name__}: {exc}\n{traceback.format_exc()[-2000:]}")
    summary = {
        "fontes": stats.sources, "resultados": stats.found, "relevantes": stats.relevant,
        "novas_empresas": stats.new_companies, "novas_oportunidades": stats.new_opps,
        "mensagens_geradas": stats.messages, "alertas_enviados": stats.alerts, "erros": stats.errors,
    }
    with session_scope() as s:
        run = s.get(SearchRun, run_id)
        run.status = status
        run.finished_at = now()
        run.results_found = stats.found
        run.results_relevant = stats.relevant
        run.new_companies = stats.new_companies
        run.new_opportunities = stats.new_opps
        run.messages_generated = stats.messages
        run.alerts_sent = stats.alerts
        run.errors = stats.errors
        run.summary = summary
    db_log(run_id, "INFO", "pipeline", f"Fim: {status} | {summary}")
    if mode == "completa":
        try:
            from modules.reports.daily import build_daily_report, save_daily_report
            text = build_daily_report()
            save_daily_report(text)
            if trigger != "manual" and now().hour >= 17:
                for e in send_daily_summary(text, settings):
                    db_log(run_id, "WARNING", "relatorio", e)
        except Exception as exc:  # noqa: BLE001
            db_log(run_id, "WARNING", "relatorio", f"Falha ao gerar relatório diário: {exc}")
    return {"status": status, "run_id": run_id, **summary}


def run_with_retries(mode: str = "completa", trigger: str = "agendado", max_attempts: int | None = None,
                     wait_seconds: int = 90) -> dict:
    if max_attempts is None:
        init_db()
        max_attempts = int(all_settings().get("agenda", {}).get("max_tentativas", 3))
    result: dict = {}
    for attempt in range(1, max_attempts + 1):
        result = run_pipeline(mode=mode, trigger=trigger, attempt=attempt)
        if result.get("status") != "erro":
            return result
        if attempt < max_attempts:
            time.sleep(wait_seconds * attempt)
    return result
