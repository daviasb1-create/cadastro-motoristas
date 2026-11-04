"""Motor de monitoramento: coleta real contra a antena de teste, pausa/retomada e persistência."""
import time

import pytest

pytest.importorskip("spacex.api.device.device_pb2")

from netvision.core.config import Settings  # noqa: E402
from netvision.core.database import Database  # noqa: E402
from netvision.engine import Engine  # noqa: E402


from PySide6.QtCore import QCoreApplication  # noqa: E402

_app = QCoreApplication.instance() or QCoreApplication([])


def _wait(cond, timeout=10.0):
    """Processa o loop de eventos Qt (sinais entre threads são enfileirados, como na interface)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        _app.processEvents()
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_engine_collects_and_pauses(fake_dish, tmp_path):
    s = Settings()
    s.dish_target = fake_dish
    s.router_targets = [fake_dish]
    s.ping_targets = ["127.0.0.1"]
    s.speedtest_auto = False
    s.app_monitor_enabled = False
    s.scan_resolve_names = False
    db = Database(tmp_path / "e.sqlite3")
    e = Engine(s, db)
    got = {}
    e.starlink_updated.connect(lambda d: got.setdefault("star", d))
    e.wifi_clients_updated.connect(lambda d: got.setdefault("wifi", d))
    e.latency_updated.connect(lambda d: got.setdefault("lat", d))
    e.devices_updated.connect(lambda d: got.setdefault("dev", d))
    e.start()
    assert _wait(lambda: {"star", "wifi", "lat", "dev"} <= got.keys(), 20), got.keys()
    assert got["star"]["ok"] and got["star"]["state"] == "CONNECTED"
    assert got["wifi"]["ok"] and len(got["wifi"]["clients"]) == 3
    assert got["lat"]["primary"]["samples"] >= 1
    assert "API Starlink" in got["dev"]["method"]
    assert any("Aquecimento" in ev["message"] for ev in db.events())

    e.pause()
    assert not e.active
    n = len(got)
    _wait(lambda: False, 1)  # descarta sinais já enfileirados antes da pausa
    got.clear()
    _wait(lambda: False, 3)
    assert "star" not in got, "coleta deveria estar pausada"
    e.resume()
    assert _wait(lambda: "star" in got, 10)
    e.shutdown()
    msgs = [ev["message"] for ev in db.events()]
    assert "Monitoramento pausado" in msgs and msgs.count("Monitoramento iniciado") == 2
    assert db.query("SELECT COUNT(*) n FROM minute_stats")[0]["n"] >= 1
    assert n == 4
