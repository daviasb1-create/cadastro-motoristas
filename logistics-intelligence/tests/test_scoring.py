from datetime import timedelta

from config.defaults import DEFAULT_SETTINGS
from modules.lead_scoring.scoring import ScoreInput, priority_label, score
from services.timeutil import now


def test_explicit_demand_in_region_is_priority():
    inp = ScoreInput(category="urgente", demand_level="explicita", state="RJ", city="Duque de Caxias",
                     origin="RJ", destination="SP", frequency="semanal", text="cotação de frete carga paletizada",
                     published_at=now(), deadline=now() + timedelta(days=3), has_email=True, has_phone=True,
                     has_named_contact=True, has_website=True)
    total, parts = score(inp, DEFAULT_SETTINGS)
    assert total >= 80, parts
    assert priority_label(total) == "Oportunidade prioritária"
    assert all({"criterio", "pontos", "max", "justificativa"} <= set(p) for p in parts)
    assert sum(p["max"] for p in parts) == 100


def test_profile_only_far_away_is_low():
    inp = ScoreInput(category="empresa", demand_level="perfil", state="AM", city="Manaus",
                     text="grande empresa multinacional com faturamento bilionário")
    total, _ = score(inp, DEFAULT_SETTINGS)
    assert total < 40


def test_size_does_not_score():
    base = dict(category="empresa", demand_level="perfil", state="SP", text="empresa")
    a, _ = score(ScoreInput(**base), DEFAULT_SETTINGS)
    b, _ = score(ScoreInput(**{**base, "text": "empresa gigante, maior do Brasil, bilionária"}), DEFAULT_SETTINGS)
    assert a == b


def test_expired_deadline_no_urgency():
    inp = ScoreInput(category="licitacao", demand_level="explicita", state="SP", deadline=now() - timedelta(days=1))
    _, parts = score(inp, DEFAULT_SETTINGS)
    urg = next(p for p in parts if p["criterio"] == "Urgência")
    assert urg["pontos"] == 0
