"""Testes do backup/reversão (usam o registro simulado fora do Windows)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tbp.core import registry as reg  # noqa: E402
from tbp.core.journal import Journal  # noqa: E402
from tbp.core.tweaks import TWEAKS, TWEAKS_BY_ID  # noqa: E402


def new_journal():
    d = tempfile.mkdtemp()
    return Journal(os.path.join(d, "j.json"))


def test_apply_and_revert_restores_original():
    j = new_journal()
    reg.write_value("HKCU", r"Control Panel\Desktop", "MenuShowDelay", reg.REG_SZ, "400")
    t = TWEAKS_BY_ID["menu_delay"]
    assert t.status() == "nao"
    t.apply(j)
    assert t.status() == "aplicado"
    assert reg.read_value("HKCU", r"Control Panel\Desktop", "MenuShowDelay")[2] == "0"
    assert t.revert(j) == []
    assert reg.read_value("HKCU", r"Control Panel\Desktop", "MenuShowDelay")[2] == "400"


def test_value_that_did_not_exist_is_deleted_on_revert():
    j = new_journal()
    reg.delete_value("HKCU", "TBPTest", "Novo")
    j.reg_set("tweak:t", "HKCU", "TBPTest", "Novo", reg.REG_DWORD, 1)
    assert reg.read_value("HKCU", "TBPTest", "Novo")[2] == 1
    j.revert_group("tweak:t")
    assert reg.read_value("HKCU", "TBPTest", "Novo")[0] is False


def test_shared_value_kept_until_last_owner_reverts():
    j = new_journal()
    reg.write_value("HKCU", "TBPTest", "V", reg.REG_DWORD, 1)
    j.reg_set("tweak:a", "HKCU", "TBPTest", "V", reg.REG_DWORD, 5)
    j.reg_set("tweak:b", "HKCU", "TBPTest", "V", reg.REG_DWORD, 5)
    j.revert_group("tweak:a")
    assert reg.read_value("HKCU", "TBPTest", "V")[2] == 5  # b ainda depende
    j.revert_group("tweak:b")
    assert reg.read_value("HKCU", "TBPTest", "V")[2] == 1


def test_journal_persists_and_revert_all():
    j = new_journal()
    reg.write_value("HKCU", "TBPTest", "N", reg.REG_BINARY, b"\x02\x00")
    j.reg_set("startup:x", "HKCU", "TBPTest", "N", reg.REG_BINARY, b"\x03\x00")
    j2 = Journal(j.path)  # recarrega do disco
    assert j2.has_group("startup:x")
    assert j2.revert_all() == []
    assert reg.read_value("HKCU", "TBPTest", "N")[2] == b"\x02\x00"
    assert j2.describe() == []


def test_all_tweaks_apply_revert_roundtrip():
    j = new_journal()
    for t in TWEAKS:
        before = {(c.hive, c.path, c.name): reg.read_value(c.hive, c.path, c.name) for c in t.get_changes()}
        t.apply(j)
        assert t.status() in ("aplicado", "indisponivel"), t.id
        t.revert(j)
        after = {(c.hive, c.path, c.name): reg.read_value(c.hive, c.path, c.name) for c in t.get_changes()}
        assert before == after, t.id


def test_windowed_games_preserves_other_keys():
    reg.write_value("HKCU", r"Software\Microsoft\DirectX\UserGpuPreferences", "DirectXUserGlobalSettings",
                    reg.REG_SZ, "AutoHDREnable=1;")
    v = TWEAKS_BY_ID["windowed_opt"].get_changes()[0].value
    assert "AutoHDREnable=1;" in v and "SwapEffectUpgradeEnable=1;" in v


def test_cleaner_safety():
    from tbp.core.cleaner import is_safe
    assert is_safe("/tmp/a/b.txt", ["/tmp/a"])
    assert not is_safe("/tmp/a", ["/tmp/a"])
    assert not is_safe("/tmp/ab/c", ["/tmp/a"])
    assert not is_safe("/etc/passwd", ["/tmp/a"])


def test_dns_packet_roundtrip_offline():
    from tbp.core.network import _dns_query
    assert _dns_query("127.0.0.1", "example.com", timeout=0.2) is None  # sem servidor: retorna None sem erro


def test_bench_stats_from_presentmon_csv(tmp_path=None):
    import csv
    import tempfile
    from tbp.core import bench
    path = os.path.join(tempfile.mkdtemp(), "pm.csv")
    fts = [5.0] * 990 + [20.0] * 10  # 1000 quadros: 1% em 20 ms
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Application", "MsBetweenPresents", "MsCPUBusy", "MsGPUBusy", "PresentMode", "DisplayLatency"])
        for v in fts:
            w.writerow(["cs2.exe", v, 3.0, 4.6, "Hardware: Independent Flip", 9.5])
    s = bench.parse_csv(path)
    assert s["frames"] == 1000
    assert abs(s["fps_avg"] - 1000 / (sum(fts) / 1000)) < 0.2
    assert 50 <= s["fps_1low"] <= 200
    assert s["present_mode"] == "Hardware: Independent Flip"
    assert s["bound"] == "GPU" and s["latency_ms"] == 9.5
    rows = bench.compare(s, dict(s, fps_1low=s["fps_1low"] * 1.10))
    assert bench.verdict(rows).startswith("GANHO")
    assert bench.verdict(bench.compare(s, dict(s))).startswith("Sem diferença")
