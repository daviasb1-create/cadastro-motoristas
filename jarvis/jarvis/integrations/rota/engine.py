"""Motor da roteirização Ícaro (porte fiel do roteirizacao_icaro.html).

Separação mantida da ferramenta original:
  * MOTOR (este arquivo): extração, atribuição por motorista fixo, ordem de
    preenchimento, capacidade, margem de custo. Igual em todas as filiais.
  * CONFIGURAÇÃO (``FilialConfig``): motoristas, aliases de região, regras de
    CEP/bairro, clientes prioritários, capacidades e faixas. Muda por filial e
    fica num arquivo local (rota_filial.json), fora do GitHub.

Regras e o motivo de cada uma: ver a documentação da ferramenta (regras-de-negocio).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any


# ------------------------------------------------------------------ utilidades
def norm(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", text)


def sort_text(value: str) -> str:
    """Chave de ordenação alfabética sem acento/caixa (como localeCompare 'base')."""
    text = unicodedata.normalize("NFD", (value or "").lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


_FLOAT_PREFIX = re.compile(r"^-?(?:\d+\.?\d*|\.\d+)")


def parse_num(value: Any) -> float:
    """Número em formato brasileiro ou americano; NaN quando vazio/inválido."""
    if value is None or value == "":
        return float("nan")
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    s = re.sub(r"\s", "", str(value).strip())
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".", 1)
    elif "," in s:
        s = s.replace(",", ".", 1)
    s = re.sub(r"[^0-9.\-]", "", s)
    m = _FLOAT_PREFIX.match(s)
    return float(m.group(0)) if m else float("nan")


def isnan(x: float) -> bool:
    return x != x


def parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and 20000 < value < 80000:
        # número de série do Excel (célula de data sem formatação)
        return date(1899, 12, 30) + timedelta(days=int(value))
    s = str(value).strip()
    m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})", s)
    if m:
        y = int(m.group(3))
        if y < 100:
            y += 2000
        try:
            return date(y, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    m = re.match(r"^(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def digits(value: Any) -> str:
    return re.sub(r"\D", "", "" if value is None else str(value))


def first_name(name: str) -> str:
    return (name or "").split(" ")[0].capitalize()


# --------------------------------------------------------------- configuração
@dataclass
class Driver:
    motorista: str
    regiao: str
    veiculo: str
    cls: str  # fiorino | kombi
    custo: float | None = None
    addon: dict | None = None  # {"trigger": "gonc", "valor": 50, "label": "São Gonçalo"}
    disponivel: bool = True
    seq: int = 99
    carreg: int = 9
    peso: float = 0
    vol: float = 0
    maxnf: int = 30
    tokens: list[str] = field(default_factory=list)


@dataclass
class FilialConfig:
    nome: str = ""
    drivers: list[dict] = field(default_factory=list)
    carreg: list[list] = field(default_factory=list)  # [["MARCOS SERGIO", 1], ...]
    alias: dict[str, str] = field(default_factory=dict)  # norm(código) -> região do motorista
    # regras especiais de atribuição (ver resolve_driver)
    cep_rules: list[dict] = field(default_factory=list)  # {"prefixes": ["243","244"], "regiao": "NITKY", "flag": "sao_goncalo", "label": "São Gonçalo"}
    bairro_rules: list[dict] = field(default_factory=list)  # {"bairro": "recreio", "regiao": "OES 5/6", "capital_only": true}
    capital_municipio: str = "riodejaneiro"
    capital_cep_prefix: str = "22"
    prio_clientes: str = ""
    prio_excecoes: str = ""
    entregue_status: str = "entrega realizada, entregue"
    fiorino: dict = field(default_factory=lambda: {"peso": 500, "vol": 900, "nf": 30})
    kombi: dict = field(default_factory=lambda: {"peso": 700, "vol": 1290, "nf": 30})
    peso_trava: float = 30
    limite_pct: float = 30
    vermelho_pct: float = 40
    custo_agregado: float = 400

    @classmethod
    def from_dict(cls, data: dict) -> "FilialConfig":
        known = {k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def build_drivers(self) -> list[Driver]:
        drivers = []
        for raw in self.drivers:
            d = Driver(motorista=raw["motorista"], regiao=raw["regiao"], veiculo=raw.get("veiculo", "Fiorino"),
                       cls=raw.get("cls", "fiorino"), custo=raw.get("custo"), addon=raw.get("addon"))
            d.tokens = [t.strip() for t in d.regiao.split("+")]
            upper = d.motorista.upper()
            for i, (key, group) in enumerate(self.carreg):
                if key.upper() in upper:
                    d.seq, d.carreg = i + 1, int(group)
            drivers.append(d)
        return drivers


# ------------------------------------------------------------------ dados
@dataclass
class Note:
    nf: str = ""
    cte: str = ""
    cep: str = ""
    peso: float = 0.0
    volume: float = 0.0
    valor_frete: float = 0.0
    reg_label: str = ""
    prazo: date | None = None
    cliente: str = ""
    ocorrencia: str = ""
    municipio: str = ""
    bairro: str = ""
    endereco: str = ""
    agendado: bool = False
    origem: str = ""
    # marcações do motor
    prioridade: bool = False
    pesado: bool = False
    sao_goncalo: bool = False
    driver: Driver | None = None
    reason: str = ""
    removed: bool = False
    realocado: bool = False
    realoc_fora: bool = False
    cap: bool = False
    urgent: bool = False


@dataclass
class Manifest:
    driver: Driver
    items: list[Note] = field(default_factory=list)
    peso: float = 0.0
    vol: float = 0.0
    absent: bool = False
    util: dict = field(default_factory=dict)
    mx: float = 0.0
    gargalo: str = ""
    valor_frete: float = 0.0
    tem_dia: bool = False
    custo: float = 0.0
    addon_label: str = ""
    resultado: float = 0.0
    pct_custo: float | None = None
    band: str = ""
    recomenda: str = ""


@dataclass
class Issues:
    sem_peso: int = 0
    sem_vol: int = 0
    sem_prazo: int = 0
    dup: int = 0
    entregue: int = 0


@dataclass
class RouteResult:
    manifests: list[Manifest]
    overflow: list[Note]
    iss: Issues
    data_rota: date
    total: int
    limite: float
    vermelho: float
    has_valor: bool
    all_regions: list[str]

    # ---- leituras usadas pelo assistente
    def must_ship(self, r: Note) -> bool:
        return bool((r.prazo and r.prazo <= self.data_rota) or r.prioridade or r.agendado)

    @property
    def allocated(self) -> int:
        return sum(len(m.items) for m in self.manifests if not m.absent)

    @property
    def routes_with_load(self) -> list[Manifest]:
        return [m for m in self.manifests if not m.absent and m.items]

    @property
    def absent_urgent(self) -> list[Note]:
        return [r for m in self.manifests if m.absent for r in m.items
                if (r.prazo and r.prazo <= self.data_rota) or r.prioridade]

    @property
    def overflow_urgent(self) -> list[Note]:
        return [r for r in self.overflow if r.urgent]

    @property
    def urgent_problem(self) -> int:
        return len(self.absent_urgent) + len(self.overflow_urgent)

    def recommend(self, kind: str) -> list[Manifest]:
        return [m for m in self.manifests if m.recomenda == kind]


# ------------------------------------------------------------------ motor
FIELDS = ["nf", "cte", "regiao", "cep", "peso", "volume", "comprimento", "largura", "altura", "prazo", "cliente",
          "municipio", "bairro", "endereco", "valorFrete", "ocorrencia"]

DET = {
    "nf": ["notasfiscais", "nf", "nota", "nfe", "documento"],
    "cte": ["cte", "ctenumero", "numerocte", "numcte", "conhecimento", "numeroconhecimento", "ctrc", "mdfe"],
    "regiao": ["regiaodeentrega", "regiao", "rota", "area", "setor", "praca"],
    "cep": ["cepdestinatario", "cepdestino", "cepentrega", "cep"],
    "peso": ["pesoreal", "peso", "pesokg", "pesobruto", "kg"],
    "volume": ["cubagem", "cubagemm3", "cubicom3", "volumem3", "cubico", "m3", "pesocubado", "pesocubad", "cubado"],
    "comprimento": ["comprimento", "compr"], "largura": ["largura", "larg"], "altura": ["altura", "alt"],
    "prazo": ["prazoentrega", "prazodeentrega", "prazo", "dataentrega", "dataentregaprevista", "sla", "previsao",
              "datalimite", "entregarate", "dtentrega"],
    "cliente": ["remetente", "cliente", "embarcador", "tomador"],
    "municipio": ["cidadedestinatario", "municipiodestinatario", "municipio", "cidade"],
    "bairro": ["bairrodestinatario", "bairro"],
    "endereco": ["enderecodestinatario", "endereco", "logradouro", "rua"],
    "valorFrete": ["valordofrete", "valorfrete", "vlrfrete", "totalfrete", "fretetotal", "valorfretecobrado",
                   "fretecobrado", "valorfretepeso", "frete"],
    "ocorrencia": ["ocorrencia", "ultimaocorrencia", "status", "statusentrega", "situacao", "situacaoentrega", "statusnf"],
}
AVOID = {"cep": ["remetente"], "municipio": ["remetente"], "bairro": ["remetente"], "endereco": ["remetente"]}

SOURCES = ("chegando", "no_rj", "agendado")
ORIGEM = {"chegando": "Chegando ao RJ", "agendado": "Agendado", "no_rj": "Já no RJ"}


def auto_detect(headers: list[str], f: str) -> str:
    cands = DET.get(f, [])
    avoid = AVOID.get(f, [])

    def ok(h: str) -> bool:
        n = norm(h)
        return not any(a in n for a in avoid)

    for h in headers:
        if ok(h) and norm(h) in cands:
            return h
    for h in headers:
        if ok(h) and any(c in norm(h) for c in cands):
            return h
    return ""


@dataclass
class Report:
    """Linhas de uma origem (várias planilhas somadas), como a ferramenta lê."""
    rows: list[dict]
    headers: list[str]
    files: list[str] = field(default_factory=list)


class RouteEngine:
    def __init__(self, config: FilialConfig) -> None:
        self.config = config
        self.drivers = config.build_drivers()
        self.token: dict[str, Driver] = {}
        self.byreg: dict[str, Driver] = {}
        for d in self.drivers:
            self.byreg[d.regiao] = d
            self.token[norm(d.regiao)] = d
        for d in self.drivers:
            for t in d.tokens:
                self.token.setdefault(norm(t), d)
        self.alias = {norm(k): v for k, v in config.alias.items()}
        self.cep_map: list[tuple[str, str]] = []  # de-para CEP opcional (prefixo, região)

    # ---------------------------------------------------------- região
    def match_driver(self, label: str) -> Driver | None:
        if not label:
            return None
        n = norm(label)
        if n in self.alias and self.alias[n] in self.byreg:
            return self.byreg[self.alias[n]]
        if n in self.token:
            return self.token[n]
        n2 = re.sub(r"^rio", "", n)
        if n2 and n2 in self.token:
            return self.token[n2]
        for part in re.split(r"[+/.\-]", label):
            p = re.sub(r"^rio", "", norm(part))
            if p and p in self.token:
                return self.token[p]
        return None

    def set_cep_map(self, entries: list[tuple[str, str]]) -> None:
        self.cep_map = sorted(entries, key=lambda e: -len(e[0]))

    def _longest_cep(self, cep: str) -> str | None:
        for prefix, regiao in self.cep_map:
            if cep.startswith(prefix):
                return regiao
        return None

    # --------------------------------------------------------- extração
    def mapping_for(self, reports: dict[str, Report], overrides: dict | None = None) -> dict[str, dict[str, str]]:
        mapping: dict[str, dict[str, str]] = {}
        for f in FIELDS:
            mapping[f] = {}
            for src, rep in reports.items():
                forced = ((overrides or {}).get(f) or {}).get(src) if isinstance((overrides or {}).get(f), dict) else (overrides or {}).get(f)
                mapping[f][src] = forced if forced and forced in rep.headers else auto_detect(rep.headers, f)
        return mapping

    def missing_fields(self, reports: dict[str, Report], mapping: dict) -> list[str]:
        loaded = list(reports)
        miss = []
        if not all(mapping["peso"].get(s) for s in loaded):
            miss.append("Peso")
        has_vol = all(mapping["volume"].get(s) for s in loaded)
        has_dim = all(all(mapping[k].get(s) for k in ("comprimento", "largura", "altura")) for s in loaded)
        if not has_vol and not has_dim:
            miss.append("Volume ou C/L/A")
        has_reg = any(mapping["regiao"].get(s) for s in loaded)
        has_cep = any(mapping["cep"].get(s) for s in loaded)
        if not (has_reg or (has_cep and self.cep_map)):
            miss.append("Região ou CEP+de-para")
        return miss

    def _get_regiao(self, row: dict, src: str, mapping: dict) -> str:
        col = mapping["regiao"].get(src)
        if col:
            v = str(row.get(col, "") or "").strip()
            if v:
                return v
        col = mapping["cep"].get(src)
        if col and self.cep_map:
            c = digits(row.get(col))
            if c:
                r = self._longest_cep(c)
                if r:
                    return r
        return ""

    def extract(self, reports: dict[str, Report], mapping: dict) -> tuple[list[Note], Issues]:
        iss = Issues()
        ent_kw = [norm(s) for s in self.config.entregue_status.split(",") if norm(s)]
        out: list[Note] = []
        for src in SOURCES:
            if src not in reports:
                continue

            def g(row, f, src=src):
                col = mapping[f].get(src)
                return row.get(col, "") if col else ""

            for row in reports[src].rows:
                occ = str(g(row, "ocorrencia") or "").strip()
                if ent_kw and any(k in norm(occ) for k in ent_kw):
                    iss.entregue += 1
                    continue
                peso = parse_num(g(row, "peso"))
                vol = parse_num(g(row, "volume"))
                if isnan(vol):
                    c, l, a = (parse_num(g(row, k)) for k in ("comprimento", "largura", "altura"))
                    if not (isnan(c) or isnan(l) or isnan(a)):
                        vol = (c * l * a) / 1e6
                prazo = parse_date(g(row, "prazo"))
                frete = parse_num(g(row, "valorFrete"))
                if isnan(frete):
                    frete = 0.0
                if isnan(peso) or peso <= 0:
                    iss.sem_peso += 1
                if not (vol > 0):
                    iss.sem_vol += 1
                if not prazo:
                    iss.sem_prazo += 1
                out.append(Note(
                    nf=_text(g(row, "nf")), cte=_text(g(row, "cte")), cep=digits(_text(g(row, "cep"))),
                    peso=0.0 if isnan(peso) else peso, volume=vol if vol > 0 else 0.0, valor_frete=frete,
                    reg_label=self._get_regiao(row, src, mapping), prazo=prazo, cliente=_text(g(row, "cliente")),
                    ocorrencia=occ, municipio=_text(g(row, "municipio")), bairro=_text(g(row, "bairro")),
                    endereco=_text(g(row, "endereco")), agendado=src == "agendado", origem=ORIGEM[src]))
        seen: dict[str, Note] = {}
        dedup: list[Note] = []
        for r in out:
            k = r.nf.strip()
            if k and k in seen:
                iss.dup += 1
                if r.agendado:
                    seen[k].agendado = True
                continue
            if k:
                seen[k] = r
            dedup.append(r)
        return dedup, iss

    # -------------------------------------------------------- atribuição
    def is_prioridade(self, cliente: str) -> bool:
        n = norm(cliente)
        excecoes = [norm(s) for s in self.config.prio_excecoes.split(",") if norm(s)]
        if any(e in n for e in excecoes):
            return False
        chaves = [norm(s) for s in self.config.prio_clientes.split(",") if norm(s)]
        return bool(chaves) and any(k in n for k in chaves)

    def resolve_driver(self, r: Note) -> tuple[Driver | None, str]:
        cfg = self.config
        cep = r.cep or ""
        b = norm(r.bairro)
        capital = cfg.capital_municipio in norm(r.municipio) or cep.startswith(cfg.capital_cep_prefix)
        for rule in cfg.cep_rules:
            drv = self.byreg.get(rule["regiao"])
            if drv and any(cep.startswith(p) for p in rule["prefixes"]):
                if rule.get("flag") == "sao_goncalo":
                    r.sao_goncalo = True
                r.reg_label = r.reg_label or rule.get("label", rule["regiao"])
                return drv, ""
        for rule in cfg.bairro_rules:
            drv = self.byreg.get(rule["regiao"])
            if drv and (capital or not rule.get("capital_only", True)) and norm(rule["bairro"]) in b:
                r.reg_label = r.reg_label or rule.get("label", rule["regiao"])
                return drv, ""
        drv = self.match_driver(r.reg_label)
        if not r.reg_label:
            return None, "Sem região"
        if not drv:
            return None, f"Região '{r.reg_label}' sem motorista fixo"
        return drv, ""

    def caps(self) -> dict:
        cfg = self.config

        def val(d, k, default):
            v = parse_num(d.get(k))
            return v if not isnan(v) and v else default

        return {"fiorino": {"peso": val(cfg.fiorino, "peso", 500), "vol": val(cfg.fiorino, "vol", 900), "nf": int(val(cfg.fiorino, "nf", 30))},
                "kombi": {"peso": val(cfg.kombi, "peso", 700), "vol": val(cfg.kombi, "vol", 1290), "nf": int(val(cfg.kombi, "nf", 30))}}

    def assign(self, reports: dict[str, Report], data_rota: date, mapping: dict | None = None,
               absent: set[str] | None = None, removed: set[str] | None = None,
               reassign: dict[str, str] | None = None) -> RouteResult:
        """absent: nomes de motoristas ausentes; removed: NFs retiradas; reassign: motorista -> região alvo."""
        cfg = self.config
        mapping = mapping or self.mapping_for(reports)
        removed = removed or set()
        absent = {a.upper() for a in (absent or set())}
        caps = self.caps()
        limite = (parse_num(cfg.limite_pct) or 30) / 100
        vermelho = (parse_num(cfg.vermelho_pct) or 40) / 100
        peso_trava = parse_num(cfg.peso_trava) or 30
        custo_ag = parse_num(cfg.custo_agregado)
        custo_ag = 0 if isnan(custo_ag) else custo_ag
        has_valor = any(mapping["valorFrete"].get(s) for s in reports)
        for d in self.drivers:
            c = caps[d.cls]
            d.peso, d.vol, d.maxnf = c["peso"], c["vol"], c["nf"]
            d.disponivel = d.motorista.upper() not in absent
        rows, iss = self.extract(reports, mapping)
        by_driver: dict[int, list[Note]] = {id(d): [] for d in self.drivers}
        pre_out: list[Note] = []
        reassigned: set[int] = set()
        target_to_driver: dict[str, Driver] = {}
        realoc_target: dict[int, str] = {}
        for name, target in (reassign or {}).items():
            d = next((x for x in self.drivers if x.motorista == name), None)
            if d and target:
                reassigned.add(id(d))
                target_to_driver[norm(target)] = d
                realoc_target[id(d)] = target
        for r in rows:
            r.prioridade = self.is_prioridade(r.cliente)
            r.pesado = r.peso >= peso_trava
            if r.nf and r.nf in removed:
                r.reason, r.removed = "Removida manualmente", True
                pre_out.append(r)
                continue
            drv, reason = self.resolve_driver(r)
            reg_n = norm(r.reg_label)
            if reg_n in target_to_driver:
                r.driver, r.realocado = target_to_driver[reg_n], True
                by_driver[id(r.driver)].append(r)
                continue
            if reason:
                r.reason = reason
                pre_out.append(r)
                continue
            if id(drv) in reassigned:
                r.reason = f"Motorista {drv.motorista.split(' ')[0]} realocado para {realoc_target[id(drv)]}"
                r.realoc_fora = True
                pre_out.append(r)
                continue
            r.driver = drv
            by_driver[id(drv)].append(r)

        def must(r: Note) -> bool:
            return bool((r.prazo and r.prazo <= data_rota) or r.prioridade or r.agendado)

        def cep_num(c: str) -> int:
            try:
                return int(c or "0")
            except ValueError:
                return 0

        manifests: list[Manifest] = []
        cap_out: list[Note] = []
        for d in self.drivers:
            fio = d.cls == "fiorino"
            items = sorted(by_driver[id(d)], key=lambda r: (
                0 if must(r) else 1,
                (1 if (not must(r) and r.pesado) else 0) if fio else 0,
                cep_num(r.cep), r.peso))
            man = Manifest(driver=d, absent=not d.disponivel)
            for r in items:
                fits = (len(man.items) < d.maxnf and man.peso + r.peso <= d.peso + 1e-6
                        and man.vol + r.volume <= d.vol + 1e-6)
                if fits:
                    man.items.append(r)
                    man.peso += r.peso
                    man.vol += r.volume
                else:
                    r.reason = (f"Peso elevado ({_fmt(r.peso)}kg), não coube na Fiorino, usar veículo maior"
                                if fio and r.pesado else "Região cheia (excede a saída única)")
                    r.cap = True
                    cap_out.append(r)
            man.items.sort(key=lambda r: (sort_text(r.bairro), cep_num(r.cep)))
            self._finalize(man, d, must, custo_ag, limite, vermelho, has_valor)
            manifests.append(man)
        overflow = pre_out + cap_out
        for r in overflow:
            r.urgent = must(r)
        regions = sorted({r.reg_label for r in rows if r.reg_label})
        return RouteResult(manifests, overflow, iss, data_rota, len(rows), limite, vermelho, has_valor, regions)

    @staticmethod
    def _finalize(man: Manifest, d: Driver, must, custo_ag, limite, vermelho, has_valor) -> None:
        u_nf, u_p, u_v = len(man.items) / d.maxnf, man.peso / d.peso, man.vol / d.vol
        mx = max(u_nf, u_p, u_v)
        man.util, man.mx = {"nf": u_nf, "peso": u_p, "vol": u_v}, mx
        man.gargalo = "Peso" if mx == u_p else "Volume" if mx == u_v else "NF"
        man.valor_frete = sum(r.valor_frete or 0 for r in man.items)
        man.tem_dia = any(must(r) for r in man.items)
        base = d.custo if d.custo is not None else custo_ag
        addon = 0
        if d.addon and any(d.addon["trigger"] in norm(r.reg_label) or (d.addon["trigger"] == "gonc" and r.sao_goncalo)
                           for r in man.items):
            addon, man.addon_label = d.addon["valor"], d.addon.get("label", "")
        man.custo = base + addon
        man.resultado = man.valor_frete - man.custo
        man.pct_custo = man.custo / man.valor_frete if man.valor_frete > 0 else None
        if man.pct_custo is None:
            man.band = ""
        else:
            man.band = "verde" if man.pct_custo <= limite else "bege" if man.pct_custo <= vermelho else "vermelho"
        if not man.items:
            man.recomenda = "vazio"
        elif not has_valor:
            man.recomenda = ""
        elif man.pct_custo is None:
            man.recomenda = "semvalor"
        elif man.pct_custo <= limite:
            man.recomenda = "ok"
        else:
            man.recomenda = "tetoprazo" if man.tem_dia else "segurar"


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    return str(value).strip()


def _fmt(n: float, d: int = 0) -> str:
    """Número no formato brasileiro, arredondando 0,5 para cima (como o navegador)."""
    from decimal import ROUND_HALF_UP, Decimal

    rounded = Decimal(repr(n)).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP)
    text = f"{rounded:,.{d}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")
