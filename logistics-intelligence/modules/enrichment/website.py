"""Coleta de contatos corporativos publicados no site oficial da empresa.

Respeita robots.txt, visita poucas páginas (home + contato/sobre/trabalhe
conosco), não faz login, não contorna bloqueios. Registra a URL de origem de
cada dado coletado.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from services import http
from services.textutil import (domain_of, email_rank, find_cnpjs, find_emails, find_phones,
                               find_whatsapp_links, is_corporate_email)

CONTACT_HINTS = ("contato", "fale-conosco", "faleconosco", "fale conosco", "atendimento", "sobre",
                 "quem-somos", "institucional", "empresa", "contact", "about", "fornecedor", "compras")
LINKEDIN_RE = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/[A-Za-z0-9_\-%.]+", re.I)


def _contact_links(base_url: str, soup: BeautifulSoup, limit: int = 3) -> list[str]:
    host = urlparse(base_url).netloc
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        label = (a.get_text(" ", strip=True) + " " + href).lower()
        if not any(h in label for h in CONTACT_HINTS):
            continue
        url = urljoin(base_url, href)
        if urlparse(url).netloc != host or url in links or url.rstrip("/") == base_url.rstrip("/"):
            continue
        if url.startswith(("mailto:", "tel:", "javascript:")):
            continue
        links.append(url)
        if len(links) >= limit:
            break
    return links


def parse_page(html: str, url: str, company_domain: str | None) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    mailtos = [a["href"][7:].split("?")[0] for a in soup.find_all("a", href=True) if a["href"].lower().startswith("mailto:")]
    tels = [a["href"][4:] for a in soup.find_all("a", href=True) if a["href"].lower().startswith("tel:")]
    emails = [e for e in find_emails(" ".join(mailtos) + " " + text) if is_corporate_email(e, company_domain)]
    phones = find_phones(" ".join(tels) + " " + text)
    return {
        "url": url,
        "emails": sorted(emails, key=email_rank),
        "phones": phones,
        "whatsapp": find_whatsapp_links(html),
        "cnpjs": find_cnpjs(text),
        "linkedin": list(dict.fromkeys(LINKEDIN_RE.findall(html)))[:2],
        "soup": soup,
    }


def scrape_company_site(website: str, max_pages: int = 4) -> dict:
    """Retorna contatos encontrados com a URL de origem de cada um."""
    if not website.startswith("http"):
        website = "https://" + website
    dom = domain_of(website)
    found = {"emails": {}, "phones": {}, "whatsapp": {}, "cnpjs": {}, "linkedin": {}, "pages": []}
    html = http.fetch_page(website)
    if html is None:
        return found
    pages = [parse_page(html, website, dom)]
    for link in _contact_links(website, pages[0]["soup"], limit=max_pages - 1):
        sub = http.fetch_page(link)
        if sub:
            pages.append(parse_page(sub, link, dom))
    for p in pages:
        found["pages"].append(p["url"])
        for k in ("emails", "phones", "whatsapp", "cnpjs", "linkedin"):
            for v in p[k]:
                found[k].setdefault(v, p["url"])
    return found
