"""Cliente HTTP educado: timeout, retentativas, robots.txt e limite de tamanho."""
from __future__ import annotations

import time
from functools import lru_cache
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "LogisticsIntelligenceBot/1.0 (pesquisa comercial B2B; respeita robots.txt)"
DEFAULT_TIMEOUT = 20
MAX_PAGE_BYTES = 1_500_000


class SourceUnavailable(Exception):
    """Fonte fora do ar, bloqueada ou com credencial inválida."""


def build_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset(["GET", "POST"]), respect_retry_after_header=True)
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9"})
    return s


_session = build_session()


def get(url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    try:
        resp = _session.get(url, **kwargs)
    except requests.RequestException as exc:
        raise SourceUnavailable(f"Falha de conexão: {exc.__class__.__name__}") from exc
    return resp


def post(url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    try:
        return _session.post(url, **kwargs)
    except requests.RequestException as exc:
        raise SourceUnavailable(f"Falha de conexão: {exc.__class__.__name__}") from exc


@lru_cache(maxsize=512)
def _robots_for(base: str) -> RobotFileParser | None:
    rp = RobotFileParser()
    try:
        resp = _session.get(base + "/robots.txt", timeout=10)
    except requests.RequestException:
        return None
    if resp.status_code in (401, 403):
        rp.disallow_all = True  # type: ignore[attr-defined]
        return rp
    if resp.status_code >= 400:
        return None  # sem robots.txt: permitido
    rp.parse(resp.text.splitlines())
    return rp


def allowed_by_robots(url: str) -> bool:
    p = urlparse(url)
    if not p.scheme or not p.netloc:
        return False
    rp = _robots_for(f"{p.scheme}://{p.netloc}")
    if rp is None:
        return True
    return rp.can_fetch(USER_AGENT, url)


def fetch_page(url: str, delay: float = 1.0) -> str | None:
    """Baixa uma página pública se o robots.txt permitir. Retorna HTML ou None."""
    if not allowed_by_robots(url):
        return None
    time.sleep(delay)
    try:
        resp = _session.get(url, timeout=DEFAULT_TIMEOUT, stream=True)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    ctype = resp.headers.get("Content-Type", "")
    if "html" not in ctype and "text" not in ctype:
        return None
    content = resp.raw.read(MAX_PAGE_BYTES, decode_content=True)
    enc = resp.encoding or "utf-8"
    try:
        return content.decode(enc, errors="replace")
    except LookupError:
        return content.decode("utf-8", errors="replace")
