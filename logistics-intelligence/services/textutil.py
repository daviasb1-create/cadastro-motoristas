"""Normalização, deduplicação e extração de dados públicos de contato."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

NAO_IDENTIFICADO = "Não identificado"

_LEGAL_SUFFIXES = r"\b(ltda|ltd|s\.?a\.?|s/a|eireli|me|epp|cia|companhia|grupo|do brasil|brasil|industria e comercio|ind\.? e com\.?|comercio|com\.?)\b"

UF_NAMES = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA", "ceara": "CE",
    "distrito federal": "DF", "espirito santo": "ES", "goias": "GO", "maranhao": "MA",
    "mato grosso do sul": "MS", "mato grosso": "MT", "minas gerais": "MG",
    "paraiba": "PB", "parana": "PR", "pernambuco": "PE", "piaui": "PI", "rio de janeiro": "RJ",
    "rio grande do norte": "RN", "rio grande do sul": "RS", "rondonia": "RO", "roraima": "RR",
    "santa catarina": "SC", "sao paulo": "SP", "sergipe": "SE", "tocantins": "TO",
}

CITY_UF = {
    "rio de janeiro": "RJ", "duque de caxias": "RJ", "nova iguacu": "RJ", "sao goncalo": "RJ",
    "niteroi": "RJ", "itaguai": "RJ", "queimados": "RJ", "resende": "RJ", "belford roxo": "RJ",
    "sao joao de meriti": "RJ", "petropolis": "RJ", "volta redonda": "RJ", "macae": "RJ",
    "sao paulo": "SP", "guarulhos": "SP", "barueri": "SP", "osasco": "SP", "cajamar": "SP",
    "jundiai": "SP", "campinas": "SP", "sao bernardo do campo": "SP", "santo andre": "SP",
    "embu das artes": "SP", "sorocaba": "SP", "santos": "SP", "sao jose dos campos": "SP",
    "ribeirao preto": "SP", "louveira": "SP", "itupeva": "SP", "extrema": "MG",
    "joinville": "SC", "itajai": "SC", "navegantes": "SC", "jaragua do sul": "SC",
    "blumenau": "SC", "araquari": "SC", "florianopolis": "SC", "sao jose": "SC",
    "itapoa": "SC", "sao francisco do sul": "SC", "curitiba": "PR", "belo horizonte": "MG",
    "porto alegre": "RS",
}

CITY_DISPLAY = {
    "sao paulo": "São Paulo", "niteroi": "Niterói", "nova iguacu": "Nova Iguaçu", "sao goncalo": "São Gonçalo",
    "itaguai": "Itaguaí", "sao joao de meriti": "São João de Meriti", "petropolis": "Petrópolis",
    "macae": "Macaé", "jundiai": "Jundiaí", "sao bernardo do campo": "São Bernardo do Campo",
    "santo andre": "Santo André", "sao jose dos campos": "São José dos Campos", "ribeirao preto": "Ribeirão Preto",
    "itajai": "Itajaí", "jaragua do sul": "Jaraguá do Sul", "florianopolis": "Florianópolis",
    "sao jose": "São José", "itapoa": "Itapoá", "sao francisco do sul": "São Francisco do Sul",
    "vitoria": "Vitória", "embu das artes": "Embu das Artes",
}


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalize_name(name: str | None) -> str:
    if not name:
        return ""
    t = strip_accents(name.lower())
    t = re.sub(r"[^\w\s/.]", " ", t)
    t = re.sub(_LEGAL_SUFFIXES, " ", t)
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def domain_of(url: str | None) -> str | None:
    if not url:
        return None
    if "://" not in url:
        url = "http://" + url
    host = urlparse(url).netloc.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host or None


# Domínios que NÃO são o site da empresa (portais, redes sociais, diretórios)
NON_COMPANY_DOMAINS = (
    "google.", "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "glassdoor", "indeed.", "vagas.com.br", "infojobs", "catho.com.br",
    "gupy.io", "trabalhabrasil", "g1.globo.com", "globo.com", "uol.com.br", "estadao.com.br",
    "folha.uol", "valor.globo", "exame.com", "cnnbrasil", "pncp.gov.br", "gov.br",
    "wikipedia.org", "reclameaqui", "econodata", "cnpj.biz", "casadosdados", "jusbrasil",
    "mercadolivre", "olx.com.br", "fretebras", "bing.com", "yahoo.com", "msn.com",
)


def is_company_domain(domain: str | None) -> bool:
    if not domain:
        return False
    return not any(bad in domain for bad in NON_COMPANY_DOMAINS)


def canonical_url(url: str | None) -> str:
    if not url:
        return ""
    p = urlparse(url.strip())
    q = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith(("utm_", "fbclid", "gclid"))]
    return urlunparse((p.scheme.lower(), p.netloc.lower().removeprefix("www."), p.path.rstrip("/"), "", urlencode(q), ""))


def sha(*parts: str | None) -> str:
    raw = "|".join((p or "").strip().lower() for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- CNPJ

def only_digits(text: str | None) -> str:
    return re.sub(r"\D", "", text or "")


def valid_cnpj(cnpj: str | None) -> bool:
    d = only_digits(cnpj)
    if len(d) != 14 or d == d[0] * 14:
        return False

    def calc(base: str, weights: list[int]) -> str:
        s = sum(int(n) * w for n, w in zip(base, weights))
        r = s % 11
        return "0" if r < 2 else str(11 - r)

    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    w2 = [6] + w1
    dv1 = calc(d[:12], w1)
    dv2 = calc(d[:12] + dv1, w2)
    return d[-2:] == dv1 + dv2


CNPJ_RE = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")


def find_cnpjs(text: str) -> list[str]:
    out = []
    for m in CNPJ_RE.findall(text or ""):
        d = only_digits(m)
        if valid_cnpj(d) and d not in out:
            out.append(d)
    return out


def format_cnpj(cnpj: str | None) -> str:
    d = only_digits(cnpj)
    if len(d) != 14:
        return NAO_IDENTIFICADO
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


# ---------------------------------------------------------------- E-mail / telefone

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_BAD_EMAIL_PARTS = ("sentry", "wixpress", "@2x", ".png", ".jpg", ".gif", ".webp", ".svg", "seuemail")
_BAD_EMAIL_DOMAINS = ("example.com", "example.org", "exemplo.com", "exemplo.com.br", "email.com", "domain.com",
                      "dominio.com", "dominio.com.br", "seudominio.com.br", "empresa.com.br", "suaempresa.com.br")
_BAD_EMAIL_LOCALS = ("email", "nome", "usuario", "seunome", "fulano", "exemplo", "example")
FREE_MAIL = ("gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "yahoo.com.br", "bol.com.br",
             "uol.com.br", "live.com", "icloud.com", "terra.com.br", "ig.com.br")

# prioridade de caixas por relevância comercial para transporte
EMAIL_PRIORITY = ["logistica", "transporte", "frete", "expedicao", "supply", "compras",
                  "suprimentos", "comercial", "contato", "atendimento", "sac", "vendas"]


def find_emails(text: str) -> list[str]:
    out: list[str] = []
    for e in EMAIL_RE.findall(text or ""):
        e = e.strip(".").lower()
        local, _, dom = e.partition("@")
        if any(b in e for b in _BAD_EMAIL_PARTS) or len(e) > 120 or dom in _BAD_EMAIL_DOMAINS \
                or local in _BAD_EMAIL_LOCALS:
            continue
        if e not in out:
            out.append(e)
    return out


def email_rank(email: str) -> int:
    local = email.split("@")[0]
    for i, k in enumerate(EMAIL_PRIORITY):
        if k in local:
            return i
    return len(EMAIL_PRIORITY)


def is_corporate_email(email: str, company_domain: str | None = None) -> bool:
    dom = email.split("@")[-1].lower()
    if dom in FREE_MAIL:
        return False
    if company_domain:
        return dom == company_domain or dom.endswith("." + company_domain) or company_domain.endswith(dom)
    return True


PHONE_RE = re.compile(r"(?:\+?55[\s.\-]?)?\(?\b([1-9]{2})\)?[\s.\-]?(9?\d{4})[\s.\-]?(\d{4})\b")


def find_phones(text: str) -> list[str]:
    out: list[str] = []
    for ddd, p1, p2 in PHONE_RE.findall(text or ""):
        num = f"{ddd}{p1}{p2}"
        if len(num) not in (10, 11):
            continue
        if len(set(num)) <= 2:
            continue
        if num not in out:
            out.append(num)
    # 0800 / 4003 / 3003
    for m in re.findall(r"\b(0800[\s\-]?\d{3}[\s\-]?\d{4}|[34]00[0-9][\s\-]?\d{4})\b", text or ""):
        d = only_digits(m)
        if d not in out:
            out.append(d)
    return out


def format_phone(num: str | None) -> str:
    d = only_digits(num)
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return num or NAO_IDENTIFICADO


def is_mobile(num: str | None) -> bool:
    d = only_digits(num)
    if d.startswith("55") and len(d) == 13:
        d = d[2:]
    return len(d) == 11 and d[2] == "9"


def whatsapp_number(num: str | None) -> str | None:
    """Número no formato internacional para wa.me (somente celulares válidos)."""
    d = only_digits(num)
    if d.startswith("55") and len(d) == 13:
        d = d[2:]
    if len(d) == 11 and d[2] == "9":
        return "55" + d
    return None


WA_LINK_RE = re.compile(r"(?:wa\.me/|api\.whatsapp\.com/send\?phone=|whatsapp\.com/send/\?phone=)\+?(\d{10,13})")


def find_whatsapp_links(html: str) -> list[str]:
    out = []
    for n in WA_LINK_RE.findall(html or ""):
        w = whatsapp_number(n)
        if w and w not in out:
            out.append(w)
    return out


# ---------------------------------------------------------------- Localização

def _positions(t: str, name: str) -> int:
    best = -1
    for sep in (" ", ",", ".", ")", "/", "-", ";"):
        i = t.find(f" {name}{sep}")
        if i >= 0 and (best < 0 or i < best):
            best = i
    i = t.find(f"({name})")
    if i >= 0 and (best < 0 or i < best):
        best = i
    return best


def detect_ufs(text: str) -> list[str]:
    """UFs citadas no texto, na ordem em que aparecem (cidades, nomes de estado e siglas)."""
    raw = " " + (text or "") + " "
    t = " " + strip_accents((text or "").lower()) + " "
    hits: list[tuple[int, str]] = []
    for city, uf in CITY_UF.items():
        pos = _positions(t, city)
        if pos >= 0:
            hits.append((pos, uf))
    for name, uf in UF_NAMES.items():
        pos = _positions(t, name)
        if pos >= 0:
            hits.append((pos, uf))
    lowered = " " + (text or "").lower() + " "
    for m in re.finditer(r"[\s(]par[áa](?=[\s),.])", lowered):
        if "á" in m.group(0) or "estado do para" in t:
            hits.append((m.start(), "PA"))
    for m in re.finditer(r"[\s(/\-]([A-Z]{2})(?=[\s),.\-/])", raw):
        if m.group(1) in UF_NAMES.values():
            hits.append((m.start(), m.group(1)))
    found: list[str] = []
    for _, uf in sorted(hits):
        if uf not in found:
            found.append(uf)
    return found


def _display(name: str) -> str:
    if len(name) == 2:
        return name.upper()
    if name in CITY_DISPLAY:
        return CITY_DISPLAY[name]
    accented = {"sao paulo": "São Paulo", "espirito santo": "Espírito Santo", "parana": "Paraná", "goias": "Goiás"}
    if name in accented:
        return accented[name]
    return " ".join(w if w in ("de", "do", "dos", "da", "das", "e") else w.capitalize() for w in name.split())


_ROUTE_SEP = r"\s*(?:x|↔|→|->|/|-|para|até|ate|a|e)\s*"


def detect_route(text: str) -> tuple[str | None, str | None]:
    """Origem/destino SOMENTE quando o texto declara o trajeto (ex.: 'de SP para Joinville',
    'rota RJ x SP', 'entre Rio de Janeiro e São Paulo'). Nunca deduz rota de menções soltas."""
    t = strip_accents((text or "").lower())
    names = sorted(list(CITY_UF) + list(UF_NAMES) + [u.lower() for u in UF_NAMES.values()], key=len, reverse=True)
    alt = "|".join(re.escape(n) for n in names)
    patterns = [
        rf"\bde\s+({alt})\s+(?:para|ate|a)\s+({alt})\b",
        rf"\bentre\s+({alt})\s+e\s+({alt})\b",
        rf"\b(?:rota|trecho|transferencia|transferencias|frete|fretes|cotacao)\s*(?:de\s+)?({alt})\s*(?:x|↔|→|->|/|-)\s*({alt})\b",
        rf"\b({alt})\s*(?:x|↔|→|->)\s*({alt})\b",
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            a, b = m.group(1), m.group(2)
            ua = CITY_UF.get(a) or UF_NAMES.get(a) or (a.upper() if a.upper() in UF_NAMES.values() else None)
            ub = CITY_UF.get(b) or UF_NAMES.get(b) or (b.upper() if b.upper() in UF_NAMES.values() else None)
            if ua and ub and a != b:
                return _display(a), _display(b)
    return None, None


def detect_city(text: str) -> tuple[str | None, str | None]:
    """Primeira cidade conhecida citada no texto."""
    t = " " + strip_accents((text or "").lower()) + " "
    hits = []
    for city, uf in CITY_UF.items():
        pos = _positions(t, city)
        if pos >= 0:
            hits.append((pos, -len(city), city, uf))
    if not hits:
        return None, None
    _, _, city, uf = sorted(hits)[0]
    return _display(city), uf


def clean_text(text: str | None, limit: int = 2000) -> str:
    t = re.sub(r"<[^>]+>", " ", text or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit]


def no_dash(text: str | None) -> str:
    """Remove travessão (preferência de estilo) dos textos gerados."""
    if not text:
        return text or ""
    return text.replace(" — ", ", ").replace("—", ", ").replace(" – ", ", ")
