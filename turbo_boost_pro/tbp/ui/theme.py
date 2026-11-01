"""Paleta e fontes da interface (tema escuro com azul neon)."""
import sys

BG = "#060a13"
SIDEBAR = "#080e1b"
PANEL = "#0c1322"
CARD = "#0f1829"
CARD_HI = "#14203a"
BORDER = "#1a2944"
NEON = "#00d4ff"
NEON_DIM = "#0a5d7a"
NEON_DARK = "#08324a"
BLUE = "#1f6bff"
TEXT = "#e6f1ff"
MUTED = "#7f93b5"
SUBTLE = "#4a5d7e"
OK = "#2ee59d"
WARN = "#ffb020"
BAD = "#ff3b5c"
TRACK = "#15223a"

_WIN = sys.platform == "win32"
FAMILY = "Segoe UI" if _WIN else "DejaVu Sans"
FAMILY_SEMI = "Segoe UI Semibold" if _WIN else "DejaVu Sans"
FAMILY_TECH = "Bahnschrift" if _WIN else "DejaVu Sans"


def font(size=13, weight="normal", tech=False):
    return (FAMILY_TECH if tech else FAMILY, size, weight)


def level_color(pct: float | None) -> str:
    if pct is None:
        return SUBTLE
    if pct < 60:
        return NEON
    if pct < 85:
        return WARN
    return BAD


def score_color(score: float) -> str:
    return OK if score >= 85 else NEON if score >= 65 else WARN if score >= 40 else BAD


def temp_color(t: float | None) -> str:
    if t is None:
        return SUBTLE
    return OK if t < 70 else WARN if t < 85 else BAD


def blend(c1: str, c2: str, t: float) -> str:
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{int(x + (y - x) * t):02x}" for x, y in zip(a, b))
