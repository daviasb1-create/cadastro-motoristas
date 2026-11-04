"""Testes do cliente Starlink contra um servidor gRPC com reflection e descritores reais da antena."""
import pytest

pytest.importorskip("spacex.api.device.device_pb2", reason="instale requirements-dev.txt (starlink-client)")

from netvision.services.starlink import StarlinkClient, normalize_wifi_client  # noqa: E402

from tests.conftest import _free_port  # noqa: E402


def test_status_via_reflection(fake_dish):
    c = StarlinkClient(fake_dish, [fake_dish])
    snap = c.get_status()
    assert snap.ok, snap.error
    assert snap.state == "CONNECTED"
    assert snap.status["hardware_version"] == "mini1_prod2"
    assert snap.status["pop_ping_latency_ms"] == pytest.approx(31.5)
    assert snap.status["downlink_throughput_bps"] == pytest.approx(12_500_000)
    assert "alert_is_heating" in snap.active_alerts
    assert snap.extra.get("country_code") == "BR"
    c.close()


def test_history_stats(fake_dish):
    c = StarlinkClient(fake_dish, [fake_dish])
    h = c.get_history_stats(900)
    assert "error" not in h, h
    assert h["samples"] == 900
    assert h["total_ping_drop"] == pytest.approx(10)
    assert h["mean_full_ping_latency"] > 29
    c.close()


def test_wifi_clients(fake_dish):
    c = StarlinkClient(fake_dish, [fake_dish])
    res = c.get_wifi_clients()
    assert res.ok, res.error
    assert res.target == fake_dish
    names = {x["hostname"] for x in res.clients}
    assert names == {"iPhone-de-Ana", "DESKTOP-GAMER", "TV-Sala"}
    iphone = next(x for x in res.clients if x["hostname"] == "iPhone-de-Ana")
    assert iphone["mac"] == "3a:11:22:33:44:55"
    assert iphone["ip"] == "192.168.1.20"
    assert iphone["iface"] == "Wi-Fi 5 GHz"
    assert iphone["router_tx_bytes"] >= 9_000_000


def test_wifi_probe_falls_back_to_second_target(fake_router_no_wifi, fake_dish):
    c = StarlinkClient(fake_dish, [fake_router_no_wifi, fake_dish])
    res = c.get_wifi_clients()
    assert res.ok and res.target == fake_dish
    assert any("Unimplemented" in line for line in c.router_probe_log)


def test_offline_dish_reports_error():
    c = StarlinkClient(f"127.0.0.1:{_free_port()}", [], timeout=1)
    snap = c.get_status()
    assert not snap.ok and snap.state == "OFFLINE" and snap.error
    assert not c.get_wifi_clients().ok


def test_normalize_handles_missing_fields():
    d = normalize_wifi_client({"mac_address": "AA-BB-CC-DD-EE-FF"})
    assert d["mac"] == "aa:bb:cc:dd:ee:ff" and d["ip"] is None and d["router_rx_bytes"] is None
