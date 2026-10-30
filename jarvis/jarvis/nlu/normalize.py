"""Normalização de texto em português para interpretação de comandos."""
from __future__ import annotations

import re
import unicodedata

_POLITE = [
    r"por favor", r"por gentileza", r"se possivel", r"pra mim", r"para mim",
    r"faz favor", r"rapidinho", r"agora mesmo",
]
_POLITE_RE = re.compile(r"\b(" + "|".join(_POLITE) + r")\b")
_SPACES = re.compile(r"\s+")


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def normalize(text: str) -> str:
    """Minúsculas, sem acentos, sem pontuação e sem expressões de cortesia."""
    text = text.lower()
    text = text.replace("e-mail", "email").replace("e-mails", "emails")
    text = strip_accents(text)
    text = re.sub(r"\be mails?\b", lambda m: "emails" if m.group(0).endswith("s") else "email", text)
    text = re.sub(r"[^\w\s%:/\.\-@+]", " ", text)
    text = re.sub(r"(?<!\d)[\.\-](?!\d)", " ", text)
    text = re.sub(r"[\.\-:]+(?=\s|$)", " ", text)
    text = _POLITE_RE.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def strip_wake_words(text: str, variants: list[str]) -> str:
    """Remove a palavra de ativação do início (e repetições) do texto normalizado."""
    words = text.split()
    normalized_variants = {normalize(v) for v in variants if v}
    while words and (words[0] in normalized_variants or words[0] in ("ei", "hey", "oi", "ola", "e ai")):
        words.pop(0)
    return " ".join(words)


def similar(a: str, b: str) -> float:
    """Similaridade 0..1 entre dois textos já normalizados."""
    from difflib import SequenceMatcher

    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ratio = SequenceMatcher(None, a, b).ratio()
    a_tokens, b_tokens = set(a.split()), set(b.split())
    if a_tokens and b_tokens:
        overlap = len(a_tokens & b_tokens) / len(a_tokens)
        if a_tokens <= b_tokens:
            overlap = max(overlap, 0.9)
        ratio = max(ratio, overlap * 0.95)
    if a in b:
        ratio = max(ratio, 0.85 if len(a) >= 3 else 0.5)
    return ratio


def recover_original(raw: str, fragment: str) -> str:
    """Devolve o trecho do texto original (com acentos e maiúsculas) que
    corresponde a ``fragment`` normalizado. Ex.: ("Lembra de ligar pro João", "ligar pro joao")
    -> "ligar pro João". Se não achar, retorna o próprio fragmento."""
    if not fragment:
        return fragment
    raw_words = raw.split()
    norm_words = [normalize(w) for w in raw_words]
    target = fragment.split()
    for start in range(len(norm_words)):
        i, j = start, 0
        picked: list[int] = []
        while i < len(norm_words) and j < len(target):
            if not norm_words[i]:
                i += 1
                continue
            parts = norm_words[i].split()
            if parts == target[j:j + len(parts)]:
                picked.append(i)
                j += len(parts)
                i += 1
            else:
                break
        if j == len(target) and picked:
            text = " ".join(raw_words[picked[0]:picked[-1] + 1])
            return text.strip(" ,.;:!?")
    return fragment
