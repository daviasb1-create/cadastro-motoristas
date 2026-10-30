"""Roteirização por voz: lê as planilhas da pasta, monta a rota e responde.

Fluxo do dia:
  1. Salve as planilhas exportadas do sistema nas subpastas de
     "Documentos/Roteirizacao Icaro" (Fretes chegando, Cargas já no Rio, Agendamentos).
  2. "Jarvis, monta a rota de amanhã" -> lê tudo, aplica as regras da filial,
     salva o Excel e os romaneios em "Rotas geradas" e resume por voz.
  3. Ajustes do dia por voz: motorista ausente, tirar/restaurar nota,
     realocar motorista para outra região. Cada ajuste refaz a rota.

A configuração da filial (motoristas, custos, regiões, clientes) fica em
rota_filial.json, na pasta de dados do JARVIS ou em config/ do programa,
e não vai para o GitHub.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from ...actions.base import STR, ActionResult, ServiceUnavailable, action, props
from ...core import paths
from ...nlu.normalize import normalize
from .engine import FilialConfig, Manifest, Report, RouteEngine, RouteResult, _fmt, first_name, norm
from .export import write_excel, write_romaneios
from .reader import FOLDERS, ensure_folders, read_depara, read_report, recent_files

log = logging.getLogger(__name__)

CONFIG_NAME = "rota_filial.json"
WEEKDAYS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def config_paths() -> list[Path]:
    return [paths.data_dir() / CONFIG_NAME, paths.project_root() / "config" / CONFIG_NAME]


def load_filial_config() -> FilialConfig:
    for path in config_paths():
        if path.exists():
            try:
                return FilialConfig.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError) as exc:
                raise ServiceUnavailable(f"O arquivo {path.name} da roteirização está com erro: {exc}") from exc
    raise ServiceUnavailable("A roteirização ainda não tem a configuração da filial (arquivo rota_filial.json). "
                             "Copie o arquivo que veio no pacote para a pasta config do JARVIS.")


def default_folder() -> Path:
    from ...platform.windows import known_folder

    documents = known_folder("documentos") or Path.home() / "Documents"  # respeita o Documentos do OneDrive
    return documents / "Roteirizacao Icaro"


def money(value: float) -> str:
    return "R$ " + _fmt(value)


def qty(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def pct(value: float | None) -> str:
    return "sem frete" if value is None else f"{round(value * 100)}%"


class RotaService:
    def __init__(self, settings, bus=None) -> None:
        self.settings = settings
        self.bus = bus
        self._lock = threading.RLock()
        self.engine: RouteEngine | None = None
        self.result: RouteResult | None = None
        self.data_rota: date | None = None
        self.absent: set[str] = set()
        self.removed: set[str] = set()
        self.reassign: dict[str, str] = {}
        self.files_used: dict[str, list[str]] = {}
        self.ignored_old: list[str] = []
        self.excel_path: Path | None = None
        self.print_path: Path | None = None
        self._reports: dict[str, Report] = {}

    def publish_status(self, detail: str = "") -> None:
        if self.bus is None:
            return
        if not any(p.exists() for p in config_paths()):
            self.bus.publish("connection", service="rota", status="error", detail="Falta o arquivo rota_filial.json")
        else:
            self.bus.publish("connection", service="rota", status="ok",
                             detail=detail or f"Planilhas em {self.folder}")

    # ---------------------------------------------------------- pasta
    @property
    def folder(self) -> Path:
        custom = (self.settings.get("rota.folder", "") or "").strip()
        return Path(custom) if custom else default_folder()

    def prepare_folder(self) -> Path:
        ensure_folders(self.folder)
        return self.folder

    # --------------------------------------------------------- montagem
    def _engine(self) -> RouteEngine:
        engine = RouteEngine(load_filial_config())
        return engine

    def load(self) -> dict[str, Report]:
        base = self.prepare_folder()
        max_age = float(self.settings.get("rota.max_age_hours", 20) or 0)
        reports: dict[str, Report] = {}
        self.files_used, self.ignored_old = {}, []
        for src in ("chegando", "no_rj", "agendado"):
            files, old = recent_files(base / FOLDERS[src], max_age)
            self.ignored_old += [p.name for p in old]
            if files:
                reports[src] = read_report(files)
                self.files_used[src] = [p.name for p in files]
                if not reports[src].rows:
                    del reports[src]
        if not reports:
            raise ServiceUnavailable(
                f"Não encontrei planilhas recentes na pasta {base.name}. Salve os relatórios do dia nas subpastas "
                f"\"{FOLDERS['chegando']}\", \"{FOLDERS['no_rj']}\" ou \"{FOLDERS['agendado']}\" e peça de novo.")
        return reports

    def build(self, data_rota: date, reload: bool = True) -> RouteResult:
        with self._lock:
            if self.data_rota != data_rota:
                self.absent, self.removed, self.reassign = set(), set(), {}
            self.data_rota = data_rota
            if reload or self.engine is None or not self._reports:
                self.engine = self._engine()
                self._reports = self.load()
                depara_files, _ = recent_files(self.folder / FOLDERS["depara"], 0)
                if depara_files:
                    self.engine.set_cep_map(read_depara(depara_files[-1]))
            engine = self.engine
            mapping = engine.mapping_for(self._reports, self.settings.get("rota.columns", {}) or {})
            missing = engine.missing_fields(self._reports, mapping)
            if missing:
                raise ServiceUnavailable("Não achei nas planilhas as colunas de " + ", ".join(missing) +
                                         ". Confira se são os relatórios certos.")
            self.result = engine.assign(self._reports, data_rota, mapping, self.absent, self.removed, self.reassign)
            self._save_outputs()
            self.publish_status(f"Rota {self.day_label(data_rota)}: {self.result.allocated} NFs")
            return self.result

    def rebuild(self) -> RouteResult:
        if self.result is None or self.data_rota is None:
            raise ServiceUnavailable("Ainda não montei a rota. Diga: monta a rota de amanhã.")
        return self.build(self.data_rota, reload=False)

    def _save_outputs(self) -> None:
        out = self.folder / FOLDERS["saida"]
        stamp = self.data_rota.strftime("%Y%m%d")
        cfg_name = self.engine.config.nome or "ÍCARO EXPRESS"
        try:
            self.excel_path = write_excel(self.result, out / f"Rotas_Icaro_{stamp}.xlsx")
        except PermissionError:
            # arquivo aberto no Excel: salva com outro nome em vez de falhar
            self.excel_path = write_excel(self.result, out / f"Rotas_Icaro_{stamp}_{datetime.now():%H%M}.xlsx")
        self.print_path = write_romaneios(self.result, out / f"Romaneios_{stamp}.html", cfg_name)

    # ------------------------------------------------------ consultas
    def require_result(self) -> RouteResult:
        if self.result is None:
            raise ServiceUnavailable("Ainda não montei a rota. Diga: monta a rota de amanhã.")
        return self.result

    def find_driver(self, spoken: str) -> Manifest | None:
        """Motorista pelo nome falado ("Marcos", "o Elias") ou pela região ("OES 3", "DCX")."""
        result = self.require_result()
        q = norm(spoken)
        words = [w for w in normalize(spoken).split() if w not in ("o", "a", "do", "da", "de", "rota", "motorista")]
        if not q:
            return None
        for m in result.manifests:
            if norm(m.driver.regiao) == q or norm(m.driver.regiao) == q.replace("rio", "", 1):
                return m
        for m in result.manifests:
            tokens = normalize(m.driver.motorista).split()
            if words and all(w in tokens for w in words):
                return m
        for m in result.manifests:
            if any(norm(t) == q for t in m.driver.tokens):
                return m
        return None

    def find_region(self, spoken: str) -> str | None:
        result = self.require_result()
        q = norm(spoken).replace("rio", "", 1) if norm(spoken).startswith("rio") else norm(spoken)
        for reg in result.all_regions:
            n = norm(reg)
            if n == q or n.replace("rio", "", 1) == q:
                return reg
        for reg in result.all_regions:
            if q and q in norm(reg):
                return reg
        return None

    # --------------------------------------------------------- frases
    def day_label(self, d: date) -> str:
        today = date.today()
        if d == today:
            prefix = "de hoje"
        elif d == today + timedelta(days=1):
            prefix = "de amanhã"
        else:
            prefix = f"de {WEEKDAYS[d.weekday()]}"
        return f"{prefix}, {d.strftime('%d/%m')}"

    def summary(self, result: RouteResult) -> tuple[str, str]:
        r = result
        parts = [f"Rota {self.day_label(r.data_rota)} montada: {qty(r.allocated, 'nota', 'notas')} em {qty(len(r.routes_with_load), 'rota', 'rotas')}."]
        if r.urgent_problem:
            parts.append(f"Atenção: {qty(r.urgent_problem, 'carga obrigatória', 'cargas obrigatórias')} sem cobertura.")
        else:
            parts.append("Toda a carga obrigatória está coberta.")
        if r.overflow:
            parts.append(f"{qty(len(r.overflow), 'nota ficou', 'notas ficaram')} fora para realocar.")
        if r.has_valor:
            segurar = r.recommend("segurar")
            if segurar:
                economia = sum(m.custo for m in segurar)
                parts.append(f"{qty(len(segurar), 'rota pode ser segurada', 'rotas podem ser seguradas')}, economia de {money(economia)}.")
            teto = r.recommend("tetoprazo")
            if teto:
                parts.append(f"{qty(len(teto), 'rota', 'rotas')} acima do teto, mas com carga obrigatória.")
        absent = [m for m in r.manifests if m.absent and m.items]
        if absent:
            parts.append("Ausentes com carga: " + ", ".join(first_name(m.driver.motorista) for m in absent) + ".")
        say = " ".join(parts)
        return say, say + "\n\n" + self.details(r)

    def details(self, r: RouteResult) -> str:
        lines = []
        for m in sorted(r.manifests, key=lambda m: (m.driver.carreg, m.driver.seq)):
            d = m.driver
            status = "AUSENTE" if m.absent else ""
            money_txt = f" · custo {pct(m.pct_custo)} ({m.band})" if m.band else ""
            lines.append(f"C{d.carreg} {first_name(d.motorista)} ({d.regiao}): {len(m.items)} NFs, {_fmt(m.peso)} kg"
                         f"{money_txt} {status}".rstrip())
        iss = r.iss
        quality = []
        if iss.entregue:
            quality.append(f"{iss.entregue} já entregues removidas")
        if iss.dup:
            quality.append(f"{iss.dup} duplicadas removidas")
        if iss.sem_peso:
            quality.append(f"{iss.sem_peso} sem peso")
        if iss.sem_prazo:
            quality.append(f"{iss.sem_prazo} sem prazo")
        if quality:
            lines.append("Dados: " + ", ".join(quality) + ".")
        if self.ignored_old:
            lines.append(f"Planilhas antigas ignoradas: {', '.join(self.ignored_old[:5])}")
        if self.excel_path:
            lines.append(f"Excel: {self.excel_path}")
        return "\n".join(lines)

    def driver_text(self, m: Manifest) -> str:
        d = m.driver
        name = first_name(d.motorista)
        if m.absent:
            return f"{name} está marcado como ausente; {qty(len(m.items), 'nota', 'notas')} da {d.regiao} para realocar."
        if not m.items:
            return f"{name} está sem carga na rota {self.day_label(self.result.data_rota)}."
        text = (f"{name}, {d.regiao}, carregamento {d.carreg}: {qty(len(m.items), 'nota', 'notas')}, {_fmt(m.peso)} quilos, "
                f"{round(m.mx * 100)}% da capacidade.")
        if m.band:
            text += f" Custo de {pct(m.pct_custo)} do frete, faixa {m.band}."
            if m.recomenda == "segurar":
                text += " Pode segurar, não tem carga obrigatória."
            elif m.recomenda == "tetoprazo":
                text += " Acima do teto, mas tem carga obrigatória."
        if m.addon_label:
            text += f" Inclui adicional de {m.addon_label}."
        return text

    def overflow_text(self, r: RouteResult) -> tuple[str, str]:
        if not r.overflow:
            return "Nada ficou de fora.", "Nada ficou de fora."
        reasons: dict[str, int] = {}
        for n in r.overflow:
            key = ("sem motorista fixo" if "sem motorista" in n.reason else "sem região" if n.reason == "Sem região"
                   else "peso elevado" if n.reason.startswith("Peso elevado") else "região cheia" if n.cap
                   else "removidas" if n.removed else "realocação" if n.realoc_fora else n.reason)
            reasons[key] = reasons.get(key, 0) + 1
        say = f"{qty(len(r.overflow), 'nota', 'notas')} fora: " + ", ".join(f"{v} {k}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])) + "."
        urgent = len(r.overflow_urgent)
        if urgent:
            say += " 1 é obrigatória." if urgent == 1 else f" {urgent} são obrigatórias."
        regions = sorted({n.reg_label for n in r.overflow if "sem motorista" in n.reason})
        if regions:
            say += " Regiões sem motorista: " + ", ".join(regions[:4]) + "."
        rows = [f"{'URGENTE ' if n.urgent else ''}NF {n.nf or '–'} · {n.cliente[:25]} · {n.bairro or n.municipio} · "
                f"{_fmt(n.peso, 1)} kg · {n.reason}" for n in sorted(r.overflow, key=lambda n: not n.urgent)]
        return say, say + "\n\n" + "\n".join(rows[:80])


# ------------------------------------------------------------------ ações
def _svc(services) -> RotaService:
    svc = services.extras.get("rota")
    if svc is None:
        raise ServiceUnavailable("A roteirização não está disponível.")
    return svc


def parse_day(text: str) -> date:
    t = normalize(text or "")
    today = date.today()
    if "hoje" in t:
        return today
    if "depois de amanha" in t:
        return today + timedelta(days=2)
    for i, name in enumerate(["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]):
        if name in t:
            return today + timedelta(days=(i - today.weekday()) % 7 or 7)
    if "amanha" in t:
        return today + timedelta(days=1)
    return today + timedelta(days=1)  # padrão da ferramenta: rota do dia seguinte


def _rebuilt(services, svc: RotaService, prefix: str) -> ActionResult:
    result = svc.rebuild()
    say, display = svc.summary(result)
    services.activity(prefix, kind="rota")
    return ActionResult(prefix + " " + say, display=prefix + "\n" + display)


@action("rota_montar", "Monta a rota dos motoristas agregados a partir das planilhas da pasta de roteirização "
        "(regras da Ícaro: carga obrigatória, capacidade, custo). Dia: hoje, amanhã ou dia da semana.",
        props(day=STR))
def rota_montar(services, params):
    svc = _svc(services)
    data_rota = parse_day(params.get("day", ""))
    result = svc.build(data_rota)
    say, display = svc.summary(result)
    services.activity(f"Rota {svc.day_label(data_rota)} montada ({result.allocated} NFs)", kind="rota")
    if services.settings.get("rota.open_excel_after_build", False) and services.open_url and svc.excel_path:
        services.open_url(str(svc.excel_path))
    return ActionResult(say, display=display)


@action("rota_resumo", "Repete o resumo da última rota montada.")
def rota_resumo(services, params):
    svc = _svc(services)
    say, display = svc.summary(svc.require_result())
    return ActionResult(say, display=display)


@action("rota_motorista", "Mostra a rota de um motorista (nome ou região).", props(["driver"], driver=STR))
def rota_motorista(services, params):
    svc = _svc(services)
    m = svc.find_driver(params.get("driver", ""))
    if m is None:
        return ActionResult.fail(f"Não achei o motorista {params.get('driver', '')} na rota.")
    lines = [f"{n.nf or '–'} · {n.cliente[:28]} · {n.bairro or n.municipio} · CEP {n.cep} · {_fmt(n.peso, 1)} kg"
             + (" · OBRIGATÓRIA" if svc.result.must_ship(n) else "") for n in m.items]
    say = svc.driver_text(m)
    return ActionResult(say, display=say + ("\n\n" + "\n".join(lines) if lines else ""))


@action("rota_fora", "Lista as notas que ficaram fora da rota (para realocar) e o motivo.")
def rota_fora(services, params):
    svc = _svc(services)
    say, display = svc.overflow_text(svc.require_result())
    return ActionResult(say, display=display)


@action("rota_ausente", "Marca um motorista como ausente (ou presente) no dia e refaz a rota.",
        props(["driver"], driver=STR, present={"type": "boolean"}))
def rota_ausente(services, params):
    svc = _svc(services)
    m = svc.find_driver(params.get("driver", ""))
    if m is None:
        return ActionResult.fail(f"Não achei o motorista {params.get('driver', '')}.")
    name = m.driver.motorista
    if params.get("present"):
        svc.absent.discard(name.upper())
        prefix = f"{first_name(name)} de volta na rota."
    else:
        svc.absent.add(name.upper())
        prefix = f"{first_name(name)} marcado como ausente."
    return _rebuilt(services, svc, prefix)


@action("rota_remover_nota", "Tira uma nota fiscal da rota (vai para Fora / realocar) ou restaura.",
        props(["nf"], nf=STR, restore={"type": "boolean"}))
def rota_remover_nota(services, params):
    svc = _svc(services)
    result = svc.require_result()
    nf = re.sub(r"\D", "", str(params.get("nf", "")))
    known = {n.nf for m in result.manifests for n in m.items} | {n.nf for n in result.overflow}
    match = next((k for k in known if re.sub(r"\D", "", k) == nf), None)
    if not nf or match is None:
        return ActionResult.fail(f"Não achei a nota {nf or ''} nas planilhas.")
    if params.get("restore"):
        svc.removed.discard(match)
        return _rebuilt(services, svc, f"Nota {match} restaurada.")
    svc.removed.add(match)
    return _rebuilt(services, svc, f"Nota {match} retirada da rota.")


@action("rota_realocar", "Realoca um motorista para atender outra região no dia (a rota original dele fica de fora). "
        "Região vazia desfaz a realocação.", props(["driver"], driver=STR, region=STR))
def rota_realocar(services, params):
    svc = _svc(services)
    m = svc.find_driver(params.get("driver", ""))
    if m is None:
        return ActionResult.fail(f"Não achei o motorista {params.get('driver', '')}.")
    name = m.driver.motorista
    spoken = (params.get("region") or "").strip()
    if not spoken:
        svc.reassign.pop(name, None)
        return _rebuilt(services, svc, f"{first_name(name)} voltou para a rota dele.")
    region = svc.find_region(spoken)
    if region is None:
        return ActionResult.fail(f"Não achei a região {spoken} nas planilhas de hoje.")
    svc.reassign[name] = region
    return _rebuilt(services, svc, f"{first_name(name)} realocado para {region}.")


@action("rota_abrir", "Abre a planilha da rota, os romaneios para impressão, a pasta de planilhas ou a ferramenta "
        "de roteirização no navegador.", props(["what"], what={"type": "string", "enum": ["excel", "romaneio", "pasta", "ferramenta"]}))
def rota_abrir(services, params):
    svc = _svc(services)
    what = params.get("what", "excel")
    if services.open_url is None:
        return ActionResult.fail("Não consigo abrir arquivos aqui.")
    if what == "pasta":
        services.open_url(str(svc.prepare_folder()))
        return ActionResult("Abrindo a pasta da roteirização.")
    if what == "ferramenta":
        tool = (services.settings.get("rota.tool_html", "") or "").strip()
        candidates = [Path(tool)] if tool else []
        candidates.append(paths.project_root() / "ferramentas" / "roteirizacao_icaro.html")
        for path in candidates:
            if path.exists():
                services.open_url(str(path))
                return ActionResult("Abrindo a ferramenta de roteirização.")
        return ActionResult.fail("Não achei o arquivo da ferramenta. Indique o caminho em Configurações > Roteirização.")
    svc.require_result()
    path = svc.excel_path if what == "excel" else svc.print_path
    if not path or not path.exists():
        return ActionResult.fail("O arquivo da rota não foi encontrado. Monte a rota de novo.")
    services.open_url(str(path))
    return ActionResult("Abrindo a planilha da rota." if what == "excel" else "Abrindo os romaneios para impressão.")

