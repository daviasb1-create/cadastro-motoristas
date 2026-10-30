"""Frases curtas do assistente (sem IA), por perfil de voz."""
from __future__ import annotations

import random
import re

THANKS = ["Disponha.", "Sempre às ordens.", "Por nada.", "É um prazer."]
GREETING = {"jarvis": ["Boa noite. Em que posso ajudar?"], "friday": ["Oi! Em que posso ajudar?"]}
NOT_UNDERSTOOD = [
    "Não entendi. Pode repetir de outro jeito?",
    "Desculpe, não captei. Pode repetir?",
]
NO_AI_HINT = ("Não reconheci esse comando. Diga ajuda para ver exemplos, ou configure um provedor de IA "
              "para conversas livres.")


def ack(settings) -> str:
    profile = settings.get("voice.profile", "jarvis")
    acks = settings.get(f"profiles.{profile}.acks", []) or ["Pois não?"]
    return random.choice(acks)


def first_sentence(text: str) -> str:
    match = re.match(r"(.+?[\.!\?])(\s|$)", text.strip())
    return match.group(1) if match else text


def for_speech(text: str) -> str:
    """Limpa texto para síntese de voz (remove URLs, marcadores e símbolos)."""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_#`>|•]+", " ", text)
    text = text.replace("—", ", ").replace("–", ", ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()
