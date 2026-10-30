"""Roteirização por voz com o próprio código da ferramenta roteirizacao_icaro.html.

Fluxo do dia:
  1. Salve os relatórios (mesmo modelo de planilha da ferramenta) nas subpastas de
     "Documentos/Roteirizacao Icaro": Fretes chegando, Cargas já no Rio, Agendamentos.
  2. "Jarvis, monta a rota" -> lê as planilhas, roda o assign() da ferramenta para o próximo
     dia útil e responde o resumo.
  3. Ajustes por voz usam as mesmas funções dos botões da ferramenta (mover nota, motorista
     que não vai, trocar rotas, realocar região, tirar/restaurar nota).
  4. Excel (aba "Eletros 413" primeiro) e PDFs do Circuit saem em "Rotas geradas".

A rota do dia fica salva e volta quando o JARVIS abre de novo (como o saveDay da ferramenta).
O HTML fica em referencia/ (só no PC, fora do GitHub, porque tem dados da filial).
"""
from __future__ import annotations

import logging
import re
import threading
from datetime import date, timedelta
from pathlib import Path

from ...actions.base import STR, ActionResult, ServiceUnavailable, action, props
from ...core import paths
from ...nlu.normalize import normalize
from .reader import FOLDERS, ensure_folders, recent_files

log = logging.getLogger(__name__)

WEEKDAYS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
TOOL_NAME = "roteirizacao_icaro.html"


def default_folder() -> Path:
    from ...platform.windows import known_folder

    documents = known_folder("documentos") or Path.home() / "Documents"  # respeita o Documentos do OneDrive
    return documents / "Roteirizacao Icaro"


def next_business_day(today: date | None = None) -> date:
    """Mesma regra da ferramenta: dia seguinte, pulando sábado e domingo."""
    d = (today or date.today()) + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def parse_day(text: str, today: date | None = None) -> date:
    t = normalize(text or "")
    today = today or date.today()
    if "depois de amanha" in t:
        return today + timedelta(days=2)
    if re.search(r"\bhoje\b", t):
        return today
    if re.search(r"\bamanha\b", t):
        return today + timedelta(days=1)
    for i, name in enumerate(["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]):
        if re.search(rf"\b{name}\b", t):
            return today + timedelta(days=(i - today.weekday()) % 7 or 7)
    return next_business_day(today)


def money(v: float) -> str:
    text = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "R$ " + text


def num(v: float, d: int = 0) -> str:
    return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def qty(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def pct(v) -> str:
    return "sem frete" if v is None else f"{round(v * 100)}%"


def first(name: str) -> str:
    return (name or "").split(" ")[0].capitalize()


def short(name: str) -> str:
    """Nome e sobrenome, sem partículas: "EDUARDO DA SILVA FRANCA" -> "Eduardo Silva"."""
    words = [w for w in (name or "").split() if w.lower() not in ("da", "de", "do", "das", "dos", "e")]
    return " ".join(words[:2]).title()


class RotaService:
    def __init__(self, settings, bus=None) -> None:
        self.settings = settings
        self.bus = bus
        self._lock = threading.RLock()
        self._engine = None
        self.result: dict | None = None
        self.ausentes: set[str] = set()
        self.files_used: dict[str, list[str]] = {}
        self.ignored_old: list[str] = []
        self.excel_path: Path | None = None
        self.circuit_dir: Path | None = None

    # ----------------------------------------------------------- caminhos
    @property
    def folder(self) -> Path:
        custom = (self.settings.get("rota.folder", "") or "").strip()
        return Path(custom) if custom else default_folder()

    def tool_path(self) -> Path:
        custom = (self.settings.get("rota.tool_html", "") or "").strip()
        return Path(custom) if custom else paths.project_root() / "referencia" / TOOL_NAME

    def store_path(self) -> Path:
        return paths.data_dir() / "rota_dia.json"

    def prepare_folder(self) -> Path:
        ensure_folders(self.folder)
        return self.folder

    # ------------------------------------------------------------- motor
    def engine(self):
        with self._lock:
            if self._engine is None:
                from .jsengine import EngineError, RotaJS

                tool = self.tool_path()
                if not tool.exists():
                    raise ServiceUnavailable(
                        f"Não achei a ferramenta de roteirização ({TOOL_NAME}). Coloque o arquivo na pasta referencia "
                        "do JARVIS ou indique o caminho em Configurações > Roteirização.")
                try:
                    self._engine = RotaJS(tool, self.store_path())
                except EngineError as exc:
                    raise ServiceUnavailable(f"A ferramenta de roteirização não rodou no JARVIS: {exc}") from exc
            return self._engine

    def restore(self) -> dict | None:
        """Rota salva do dia (como o loadDay da ferramenta ao abrir)."""
        try:
            result = self.engine().restore_day()
        except ServiceUnavailable as exc:
            log.info("Roteirização indisponível: %s", exc)
            return None
        if result:
            self.result = result
            self.ausentes = {m["nome"] for m in result["motoristas"] if not m["disponivel"]}
        return result

    def close(self) -> None:
        with self._lock:
            if self._engine is not None:
                self._engine.close()
                self._engine = None

    def publish_status(self, detail: str = "") -> None:
        if self.bus is None:
            return
        if not self.tool_path().exists():
            self.bus.publish("connection", service="rota", status="error", detail=f"Falta o arquivo {TOOL_NAME}")
        else:
            self.bus.publish("connection", service="rota", status="ok", detail=detail or f"Planilhas em {self.folder}")

    # --------------------------------------------------------- montagem
    def build(self, data_rota: date, fds: bool = False) -> dict:
        with self._lock:
            engine = self.engine()
            base = self.prepare_folder()
            max_age = float(self.settings.get("rota.max_age_hours", 20) or 0)
            engine.reset()
            self.files_used, self.ignored_old = {}, []
            for src in ("chegando", "no_rj", "agendado"):
                files, old = recent_files(base / FOLDERS[src], max_age)
                self.ignored_old += [p.name for p in old]
                if files:
                    out = engine.load(src, files)
                    if out and out.get("ok"):
                        self.files_used[src] = [p.name for p in files]
            if not self.files_used:
                raise ServiceUnavailable(
                    f"Não encontrei planilhas recentes na pasta {base.name}. Salve os relatórios do dia em "
                    f"\"{FOLDERS['no_rj']}\" (e, se tiver, em \"{FOLDERS['chegando']}\" e \"{FOLDERS['agendado']}\").")
            status = engine.status()
            if not status.get("ok"):
                raise ServiceUnavailable(f"As planilhas não têm o que a ferramenta precisa: {status.get('msg', '')}")
            if self.result and self.result.get("data") != data_rota.isoformat():
                self.ausentes = set()
            self.result = engine.assign(data_rota.isoformat(), fds, sorted(self.ausentes))
            self.publish_status(f"Rota {self.day_label(data_rota)}: {self.allocated()} notas")
            return self.result

    def require(self) -> dict:
        if self.result is None:
            raise ServiceUnavailable("Ainda não montei a rota. Diga: monta a rota.")
        return self.result

    def apply(self, method: str, *args) -> dict:
        with self._lock:
            self.require()
            self.result = getattr(self.engine(), method)(*args)
            return self.result

    # -------------------------------------------------------- consultas
    def allocated(self) -> int:
        r = self.result or {}
        return sum(len(m["notas"]) for m in r.get("manifests", []) if not m["ausente"])

    def find_driver(self, spoken: str) -> dict | list[dict] | None:
        """Motorista pelo nome falado ("Marcos", "Ronald Yuri") ou região ("OES 3"). Lista = ambíguo."""
        result = self.require()
        words = [w for w in normalize(spoken).split() if w not in ("o", "a", "do", "da", "de", "motorista", "rota")]
        if not words:
            return None
        key = re.sub(r"[^a-z0-9]", "", " ".join(words))
        motoristas = result["motoristas"]
        hits = [m for m in motoristas if all(w in normalize(m["nome"]).split() for w in words)]
        if not hits:
            hits = [m for m in motoristas if re.sub(r"[^a-z0-9]", "", normalize(m["regiao"])) == key]
        if len(hits) > 1:
            starts = [m for m in hits if normalize(m["nome"]).split()[0] == words[0]]
            hits = starts if len(starts) == 1 else hits
        if not hits:
            return None
        return hits[0] if len(hits) == 1 else hits

    def driver_or_fail(self, spoken: str) -> dict:
        found = self.find_driver(spoken)
        if found is None:
            raise ServiceUnavailable(f"Não achei o motorista {spoken}.")
        if isinstance(found, list):
            names = ", ".join(short(m["nome"]) for m in found[:4])
            raise ServiceUnavailable(f"Tem mais de um {spoken}: {names}. Diga o nome e o sobrenome.")
        return found

    def manifest(self, idx: int) -> dict | None:
        return next((m for m in self.require()["manifests"] if m["idx"] == idx), None)

    def find_region(self, spoken: str) -> str | None:
        result = self.require()
        q = re.sub(r"[^a-z0-9]", "", normalize(spoken))
        q = q[3:] if q.startswith("rio") else q
        for reg in result["regioes"]:
            n = re.sub(r"[^a-z0-9]", "", normalize(reg))
            if n == q or n.replace("rio", "", 1) == q:
                return reg
        for reg in result["regioes"]:
            if q and q in re.sub(r"[^a-z0-9]", "", normalize(reg)):
                return reg
        return None

    def find_nf(self, spoken: str) -> str | None:
        result = self.require()
        q = re.sub(r"\D", "", spoken or "")
        if not q:
            return None
        notas = [n for m in result["manifests"] for n in m["notas"]] + result["fora"]
        exact = [n["nf"] for n in notas if re.sub(r"\D", "", n["nf"]) == q]
        if exact:
            return exact[0]
        tail = [n["nf"] for n in notas if re.sub(r"\D", "", n["nf"]).endswith(q) and len(q) >= 4]
        return tail[0] if len(tail) == 1 else None

    # ----------------------------------------------------------- frases
    def day_label(self, d: date) -> str:
        today = date.today()
        prefix = ("de hoje" if d == today else "de amanhã" if d == today + timedelta(days=1)
                  else f"de {WEEKDAYS[d.weekday()]}")
        return f"{prefix}, {d.strftime('%d/%m')}"

    def summary(self) -> tuple[str, str]:
        r = self.require()
        d = date.fromisoformat(r["data"])
        com_carga = [m for m in r["manifests"] if m["notas"] and not m["ausente"]]
        urgentes = [n for n in r["fora"] if n["urgente"]]
        parts = [f"Rota {self.day_label(d)}{' (fim de semana ou feriado)' if r['fds'] else ''}: "
                 f"{qty(self.allocated(), 'nota', 'notas')} em {qty(len(com_carga), 'rota', 'rotas')}."]
        parts.append(f"Atenção: {qty(len(urgentes), 'obrigatória ficou', 'obrigatórias ficaram')} fora." if urgentes
                     else "Toda a carga obrigatória saiu.")
        if r["fora"]:
            parts.append(f"{qty(len(r['fora']), 'nota', 'notas')} em Fora / realocar.")
        if r["hasValor"]:
            segurar = [m for m in com_carga if m["recomenda"] == "segurar"]
            if segurar:
                parts.append(f"{qty(len(segurar), 'rota pode ser segurada', 'rotas podem ser seguradas')}, economia de "
                             f"{money(sum(m['custo'] for m in segurar))}.")
        if r["foraFilial"]:
            parts.append(f"{qty(len(r['foraFilial']), 'nota fora da filial excluída', 'notas fora da filial excluídas')}.")
        say = " ".join(parts)
        return say, say + "\n\n" + self.table(com_carga)

    def table(self, manifests: list[dict]) -> str:
        lines = ["Motorista · Região · Veículo · NFs · Peso · Volumes · Frete · Custo · % custo/frete"]
        for m in manifests:
            lines.append(f"{short(m['nome'])} · {m['regiao']} · {m['veiculo']} · {len(m['notas'])} · "
                         f"{num(m['peso'], 1)} kg · {num(m['qtdVol'])} · {money(m['frete'])} · {money(m['custo'])}"
                         f"{' (+' + m['adicional'] + ')' if m['adicional'] else ''} · {pct(m['pct'])}")
        if self.ignored_old:
            lines.append(f"Planilhas antigas ignoradas: {', '.join(self.ignored_old[:5])}")
        return "\n".join(lines)

    def driver_text(self, m: dict) -> str:
        name = first(m["nome"])
        if m["ausente"]:
            return f"{name} não vai hoje."
        if not m["notas"]:
            return f"{name} está sem carga."
        text = (f"{name}, {m['regiao']}, {m['veiculo']}: {qty(len(m['notas']), 'nota', 'notas')}, {num(m['peso'])} quilos, "
                f"{qty(int(m['qtdVol']), 'volume', 'volumes')}. Frete {money(m['frete'])}, custo {money(m['custo'])}, "
                f"{pct(m['pct'])} do frete.")
        if m["recomenda"] == "segurar":
            text += " Acima do teto e sem obrigatória: pode segurar."
        elif m["recomenda"] == "tetoprazo":
            text += " Acima do teto, mas tem obrigatória: sai mesmo assim."
        return text

    # ------------------------------------------------------------ saídas
    def save_excel(self) -> Path:
        nome, data = self.engine().excel()
        out = self.prepare_folder() / FOLDERS["saida"]
        path = out / nome
        try:
            path.write_bytes(data)
        except PermissionError:  # arquivo aberto no Excel
            path = out / (path.stem + "_novo.xlsx")
            path.write_bytes(data)
        self.excel_path = path
        return path

    def save_circuit(self, idx: int | None = None) -> list[Path]:
        r = self.require()
        folder = self.prepare_folder() / FOLDERS["saida"] / f"Circuit_{r['data']}"
        folder.mkdir(parents=True, exist_ok=True)
        saved = []
        for nome, _, data in self.engine().circuit(idx):
            path = folder / nome
            path.write_bytes(data)
            saved.append(path)
        self.circuit_dir = folder
        return saved


# ------------------------------------------------------------------ ações
def _svc(services) -> RotaService:
    svc = services.extras.get("rota")
    if svc is None:
        raise ServiceUnavailable("A roteirização não está disponível.")
    return svc


def _after(services, svc: RotaService, prefix: str) -> ActionResult:
    say, display = svc.summary()
    services.activity(prefix, kind="rota")
    return ActionResult(prefix, display=prefix + "\n\n" + display)


@action("rota_montar", "Monta a rota dos agregados com a ferramenta de roteirização da Ícaro a partir das planilhas da "
        "pasta. Dia padrão: próximo dia útil. fds=true em fim de semana ou feriado (tira entregas para CNPJ).",
        props(day=STR, fds={"type": "boolean"}))
def rota_montar(services, params):
    svc = _svc(services)
    data_rota = parse_day(params.get("day", ""))
    fds = bool(params.get("fds")) or data_rota.weekday() >= 5
    svc.build(data_rota, fds)
    say, display = svc.summary()
    services.activity(f"Rota {svc.day_label(data_rota)} montada ({svc.allocated()} notas)", kind="rota")
    if services.settings.get("rota.open_excel_after_build", False) and services.open_url:
        services.open_url(str(svc.save_excel()))
    return ActionResult(say, display=display)


@action("rota_resumo", "Resumo da rota montada, com tabela por motorista (região, veículo, notas, peso, volumes, frete, custo, %).")
def rota_resumo(services, params):
    say, display = _svc(services).summary()
    return ActionResult(say, display=display)


@action("rota_motorista", "Resumo de um motorista (nome ou região): notas, peso, volumes, frete, custo e % custo/frete.",
        props(["driver"], driver=STR))
def rota_motorista(services, params):
    svc = _svc(services)
    m = svc.manifest(svc.driver_or_fail(params.get("driver", ""))["idx"])
    if m is None:
        return ActionResult.fail("Esse motorista não está na rota de hoje.")
    lines = [f"NF {n['nf']} · {(n['destinatario'] or n['cliente'])[:28]} · {n['bairro']} · {num(n['peso'], 1)} kg"
             + (" · OBRIGATÓRIA" if n["obrigatoria"] else "") for n in m["notas"]]
    say = svc.driver_text(m)
    return ActionResult(say, display=say + ("\n\n" + "\n".join(lines) if lines else ""))


@action("rota_fora", "Notas em Fora / realocar, com o motivo.")
def rota_fora(services, params):
    svc = _svc(services)
    r = svc.require()
    if not r["fora"]:
        return ActionResult("Nada ficou de fora.")
    reasons: dict[str, int] = {}
    for n in r["fora"]:
        key = n["motivo"].split(" (")[0] or "sem motivo"
        reasons[key] = reasons.get(key, 0) + 1
    say = f"{qty(len(r['fora']), 'nota', 'notas')} fora: " + "; ".join(
        f"{v} {k.lower()}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])[:4]) + "."
    urg = sum(1 for n in r["fora"] if n["urgente"])
    if urg:
        say += f" {qty(urg, 'é obrigatória', 'são obrigatórias')}."
    rows = [f"{'OBRIGATÓRIA ' if n['urgente'] else ''}NF {n['nf']} · {n['bairro'] or n['municipio']} · {n['regLabel']} · {n['motivo']}"
            for n in sorted(r["fora"], key=lambda n: not n["urgente"])]
    return ActionResult(say, display=say + "\n\n" + "\n".join(rows[:100]))


@action("rota_ausente", "Marca que um motorista não vai hoje (ou que vai) e manda as notas dele para realocar.",
        props(["driver"], driver=STR, present={"type": "boolean"}))
def rota_ausente(services, params):
    svc = _svc(services)
    d = svc.driver_or_fail(params.get("driver", ""))
    m = svc.manifest(d["idx"])
    want_absent = not params.get("present")
    if m is None or bool(m["ausente"]) == want_absent:
        return ActionResult(f"{first(d['nome'])} já está como {'ausente' if want_absent else 'presente'}.")
    (svc.ausentes.add if want_absent else svc.ausentes.discard)(d["nome"])
    svc.apply("toggle", d["idx"])
    return _after(services, svc, f"{first(d['nome'])} {'não vai hoje; notas dele em Fora / realocar' if want_absent else 'de volta na rota'}.")


@action("rota_mover_nota", "Move uma nota fiscal para outro motorista.", props(["nf", "driver"], nf=STR, driver=STR))
def rota_mover_nota(services, params):
    svc = _svc(services)
    nf = svc.find_nf(params.get("nf", ""))
    if nf is None:
        return ActionResult.fail(f"Não achei a nota {params.get('nf', '')} na rota.")
    d = svc.driver_or_fail(params.get("driver", ""))
    svc.apply("move", nf, d["idx"])
    return _after(services, svc, f"Nota {nf} com {first(d['nome'])}.")


@action("rota_trocar", "Troca as rotas inteiras entre dois motoristas.", props(["a", "b"], a=STR, b=STR))
def rota_trocar(services, params):
    svc = _svc(services)
    a, b = svc.driver_or_fail(params.get("a", "")), svc.driver_or_fail(params.get("b", ""))
    if a["idx"] == b["idx"]:
        return ActionResult.fail("Preciso de dois motoristas diferentes.")
    svc.apply("swap", a["idx"], b["idx"])
    return _after(services, svc, f"Rotas trocadas: {first(a['nome'])} e {first(b['nome'])}.")


@action("rota_realocar", "Realoca um motorista para outra região no dia (a rota dele fica de fora). Região vazia desfaz.",
        props(["driver"], driver=STR, region=STR))
def rota_realocar(services, params):
    svc = _svc(services)
    d = svc.driver_or_fail(params.get("driver", ""))
    spoken = (params.get("region") or "").strip()
    region = svc.find_region(spoken) if spoken else ""
    if spoken and not region:
        return ActionResult.fail(f"Não achei a região {spoken} nas planilhas.")
    svc.apply("reassign", d["idx"], region)
    return _after(services, svc, f"{first(d['nome'])} realocado para {region}." if region
                  else f"{first(d['nome'])} voltou para a rota dele.")


@action("rota_remover_nota", "Tira uma nota da rota (vai para Fora / realocar) ou restaura.",
        props(["nf"], nf=STR, restore={"type": "boolean"}))
def rota_remover_nota(services, params):
    svc = _svc(services)
    nf = svc.find_nf(params.get("nf", ""))
    if nf is None:
        return ActionResult.fail(f"Não achei a nota {params.get('nf', '')} na rota.")
    if params.get("restore"):
        svc.apply("restore", nf)
        return _after(services, svc, f"Nota {nf} restaurada.")
    svc.apply("remove", nf)
    return _after(services, svc, f"Nota {nf} retirada da rota.")


@action("rota_excel", "Gera o Excel da rota (igual ao da ferramenta, aba Eletros 413 primeiro) e abre.")
def rota_excel(services, params):
    svc = _svc(services)
    svc.require()
    path = svc.save_excel()
    if services.open_url:
        services.open_url(str(path))
    return ActionResult("Excel da rota gerado.", display=f"Excel: {path}")


@action("rota_circuit", "Gera os PDFs do Circuit (um por motorista, ou só do motorista pedido) e abre a pasta.",
        props(driver=STR))
def rota_circuit(services, params):
    svc = _svc(services)
    svc.require()
    spoken = (params.get("driver") or "").strip()
    idx = svc.driver_or_fail(spoken)["idx"] if spoken else None
    saved = svc.save_circuit(idx)
    if not saved:
        return ActionResult.fail("Nenhuma rota com carga para gerar o Circuit.")
    if services.open_url:
        services.open_url(str(svc.circuit_dir))
    return ActionResult(f"{qty(len(saved), 'PDF do Circuit gerado', 'PDFs do Circuit gerados')}.",
                        display="\n".join(str(p) for p in saved))


@action("rota_abrir", "Abre a pasta das planilhas ou a ferramenta de roteirização (com o mapa) no navegador.",
        props(["what"], what={"type": "string", "enum": ["pasta", "ferramenta"]}))
def rota_abrir(services, params):
    svc = _svc(services)
    if services.open_url is None:
        return ActionResult.fail("Não consigo abrir arquivos aqui.")
    if params.get("what") == "ferramenta":
        tool = svc.tool_path()
        if not tool.exists():
            return ActionResult.fail(f"Não achei o arquivo {TOOL_NAME}.")
        services.open_url(str(tool))
        return ActionResult("Abrindo a ferramenta de roteirização.")
    services.open_url(str(svc.prepare_folder()))
    return ActionResult("Abrindo a pasta da roteirização.")
