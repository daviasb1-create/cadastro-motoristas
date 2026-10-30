"""Conversão de números escritos por extenso (pt-BR) em dígitos.

O reconhecimento de voz local costuma entregar "vinte e cinco por cento";
os comandos precisam de 25.
"""
from __future__ import annotations

import re

UNITS = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4,
    "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11,
    "doze": 12, "treze": 13, "quatorze": 14, "catorze": 14, "quinze": 15,
    "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19,
}
TENS = {
    "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60,
    "setenta": 70, "oitenta": 80, "noventa": 90,
}
HUNDREDS = {
    "cem": 100, "cento": 100, "duzentos": 200, "duzentas": 200, "trezentos": 300,
    "trezentas": 300, "quatrocentos": 400, "quatrocentas": 400, "quinhentos": 500,
    "quinhentas": 500, "seiscentos": 600, "seiscentas": 600, "setecentos": 700,
    "setecentas": 700, "oitocentos": 800, "oitocentas": 800, "novecentos": 900,
    "novecentas": 900,
}
NUMBER_WORDS = set(UNITS) | set(TENS) | set(HUNDREDS) | {"mil"}


def _word_value(word: str) -> int:
    return UNITS.get(word) or TENS.get(word) or HUNDREDS.get(word) or (1000 if word == "mil" else 0)


def _can_follow(previous: str, nxt: str) -> bool:
    """'vinte' + 'cinco' compõem 25; 'quinze' + 'trinta' são números distintos."""
    if previous == "mil":
        return nxt != "mil"
    if nxt == "mil":
        return True
    prev_value, next_value = _word_value(previous), _word_value(nxt)
    if previous in HUNDREDS:
        return next_value < 100 and previous != "cem"
    if previous in TENS:
        return 0 < next_value < 10
    return False


def _parse_sequence(tokens: list[str]) -> int | None:
    total, current = 0, 0
    seen = False
    for tok in tokens:
        if tok == "e":
            continue
        if tok in UNITS:
            current += UNITS[tok]
        elif tok in TENS:
            current += TENS[tok]
        elif tok in HUNDREDS:
            current += HUNDREDS[tok]
        elif tok == "mil":
            total += (current or 1) * 1000
            current = 0
        elif tok.isdigit():
            current += int(tok)
        else:
            return None
        seen = True
    return total + current if seen else None


def words_to_digits(text: str) -> str:
    """Substitui sequências numéricas por extenso pelo número.

    "aumenta o volume em vinte e cinco" -> "aumenta o volume em 25".
    A palavra "um/uma" isolada só vira 1 quando acompanha unidade ("um minuto").
    """
    tokens = text.split()
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in NUMBER_WORDS and not (tok == "cento" and (i + 1 >= len(tokens) or tokens[i + 1] != "e")):
            j = i
            seq: list[str] = []
            while j < len(tokens):
                word = tokens[j]
                last = next((t for t in reversed(seq) if t != "e"), None)
                if word == "cento" and not (j + 1 < len(tokens) and tokens[j + 1] == "e"):
                    break  # "por cento" não é número
                if word in NUMBER_WORDS and (last is None or _can_follow(last, word)):
                    seq.append(word)
                    j += 1
                elif (word == "e" and seq and seq[-1] != "e" and j + 1 < len(tokens)
                      and tokens[j + 1] in NUMBER_WORDS and _can_follow(seq[-1], tokens[j + 1])):
                    seq.append(word)
                    j += 1
                else:
                    break
            if tok in ("um", "uma") and len(seq) == 1:
                nxt = tokens[j] if j < len(tokens) else ""
                if not re.match(r"(minuto|hora|segundo|dia|semana|mes|por)", nxt):
                    out.append(tok)
                    i += 1
                    continue
            value = _parse_sequence(seq)
            if value is not None:
                out.append(str(value))
                i = j
                continue
        out.append(tok)
        i += 1
    return " ".join(out)


def first_number(text: str) -> int | None:
    match = re.search(r"\b(\d+)\b", words_to_digits(text))
    return int(match.group(1)) if match else None
