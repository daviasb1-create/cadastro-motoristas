"""Teste de integração REAL no Windows (executado no GitHub Actions, em máquina descartável).

Aplica as modificações do WINDOWS ULTRA LITE / GAMING EDITION no sistema, reverte tudo e confere se o
registro, os serviços e as tarefas agendadas voltaram exatamente ao estado original.
"""
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tbp.core import registry as reg, services, snapshot, system_mods, ultralite as UL, winapi, winver  # noqa: E402
from tbp.core.engine import engine  # noqa: E402
from tbp.core.tweaks import TWEAKS  # noqa: E402

fails, notes = [], []


def check(cond, msg):
    (notes if cond else fails).append(("OK   " if cond else "FALHA ") + msg)


print("Windows:", winver.label(), "| admin:", winapi.is_admin(), "| compat:", winver.compatibility())

# ---------------------------------------------------------------- estado original
reg_before = {(c.hive, c.path, c.name): c.current() for t in TWEAKS for c in t.get_changes()}
svc_before = {n: (services.get_service(n) or {}).get("start") for n in services.PROFILES}
tasks_before = {t["full"]: t["enabled"] for t in system_mods.list_tasks()}
apps = system_mods.list_apps()
feats = system_mods.list_features()
print(f"Itens: {len(reg_before)} valores de registro, {sum(1 for v in svc_before.values() if v)} serviços, "
      f"{len(tasks_before)} tarefas, {len(apps)} apps, {len(feats)} recursos")

# ---------------------------------------------------------------- planos montam sem erro
t0 = time.time()
plan = UL.plan_ultra_lite()
check(len(plan) > 10, f"Plano Ultra Lite montado: {len(plan)} ações em {time.time() - t0:.0f}s")
gplan = UL.plan_gaming_edition()
check(len(gplan) > 5, f"Plano Gaming Edition montado: {len(gplan)} ações")

# ---------------------------------------------------------------- aplica (perfil extremo + tudo selecionado)
for a in plan:
    if a.id.startswith(("appx:", "feat:", "startup:", "hibernate")):
        a.selected = False  # testados separadamente abaixo
    else:
        a.selected = True
res = engine.execute(plan)
print(f"Ultra Lite: {len(res.messages)} ok, {len(res.errors)} erros, {len(res.skipped_admin)} sem admin")
for e in res.errors:
    print("   erro:", e)
check(not [e for e in res.errors if "ponto de restauração" not in e.lower() and "restauração" not in e.lower()],
      "Ultra Lite aplicado sem erros")
check(UL.is_active(UL.ULTRA_GID), "Ultra Lite marcado como ativo")
for name, start in [(c["name"], c["target"]) for c in services.profile_plan("extremo")]:
    services.set_start(name, start, engine.journal)
changed = sum(1 for k, v in reg_before.items() if reg.read_value(*k) != v)
check(changed > 20, f"{changed} valores de registro realmente alterados")
res_g = engine.execute([a for a in gplan if a.id != "power"])
check(not [e for e in res_g.errors if "restauração" not in e.lower()], "Gaming Edition aplicado sem erros")

# ---------------------------------------------------------------- appx (remove e reinstala 1 app)
if apps:
    app = apps[-1]
    try:
        print(system_mods.remove_app(app, engine.journal))
        gone = not any(a["name"] == app["name"] for a in system_mods.list_apps())
        check(gone, f"App {app['name']} removido")
        errs = engine.journal.revert_group(f"appx:{app['name']}")
        back = any(a["name"] == app["name"] for a in system_mods.list_apps())
        if back:
            check(True, f"App {app['name']} reinstalado offline")
        else:
            notes.append(f"AVISO app {app['name']} não reinstalado offline (Store aberta): {errs}")
    except Exception as e:
        notes.append(f"AVISO remoção de app não testável neste Windows: {e}")

# ---------------------------------------------------------------- ETAPA 2
from tbp.core import analysis2, bench, stage2, power  # noqa: E402
from tbp.utils import powershell_json as pj  # noqa: E402

pf_before = pj("$c=Get-CimInstance Win32_ComputerSystem; [pscustomobject]@{Auto=$c.AutomaticManagedPagefile; "
               "Files=@(Get-CimInstance Win32_PageFileSetting | ForEach-Object { \"$($_.Name)|$($_.InitialSize)|"
               "$($_.MaximumSize)\" })}")
for fn in (analysis2.cpu_report, analysis2.ram_report, analysis2.gpu_report, analysis2.latency_report,
           analysis2.disk_report):
    try:
        rep = fn()
        check(bool(rep["facts"]), f"{fn.__name__}: {len(rep['facts'])} dados, {len(rep['findings'])} achados")
    except Exception as e:  # noqa: BLE001
        check(False, f"{fn.__name__} falhou: {e!r}")
audit = analysis2.process_audit(3)
check(isinstance(audit["rows"], list), f"Auditoria de processos: {len(audit['rows'])} processos ativos em repouso")
s2 = stage2.plan_stage2()
for a in s2:
    a.selected = a.id not in ("nic_eee",)
res2 = engine.execute(s2)
for e in res2.errors:
    print("   erro etapa 2:", e)
check(not [e for e in res2.errors if "restauração" not in e.lower()], f"Etapa 2 aplicada ({len(s2)} ações)")
check(power.read_setting("PERFBOOSTMODE") is not None, f"Leitura do plano de energia: {power.cpu_settings()}")
msgs = system_mods.set_pagefile_auto(engine.journal)
print("  ", msgs)
svc_run_before = {n: (services.get_service(n) or {}).get("status") for n in stage2.CS2_SESSION_SERVICES}
print("   Modo CS2:", stage2.start_cs2_session(launch=False, close_apps=False))
check(stage2.cs2_session_active(), "Modo CS2 iniciado")
stage2.end_cs2_session()
time.sleep(5)
svc_run_after = {n: (services.get_service(n) or {}).get("status") for n in stage2.CS2_SESSION_SERVICES}
diff_run = {n: (svc_run_before[n], svc_run_after[n]) for n in svc_run_before
            if svc_run_before[n] == "running" and svc_run_after[n] != "running"}
check(not diff_run, "Serviços pausados pelo Modo CS2 voltaram a rodar" + (f": {diff_run}" if diff_run else ""))
try:
    r = bench.capture("dwm.exe", 5, "CI")
    check(r["frames"] > 0, f"Benchmark PresentMon: {r['frames']} quadros, {r['fps_avg']} FPS")
except bench.BenchError as e:
    check("quadro" in str(e).lower(), f"Benchmark PresentMon executou (sem GPU no CI): {e}")
print("   PresentMon:", bench.presentmon_path())

# ---------------------------------------------------------------- medição
snap = snapshot.capture("CI", cpu_seconds=2, journal=engine.journal)
check(snap["processes"] > 0 and snap["ram_used"] > 0, f"Medição: {snap['processes']} processos, "
      f"{snap['ram_used'] // 2**20} MB, boot {snap['boot_ms']} ms")

# ---------------------------------------------------------------- RESTAURAR WINDOWS ORIGINAL
errs = UL.restore_windows_original()
for e in errs:
    print("   aviso restauração:", e)
check(not engine.journal.describe(), "Diário vazio após restaurar")
diff = [k for k, v in reg_before.items() if reg.read_value(*k) != v]
check(not diff, f"Registro idêntico ao original ({len(reg_before)} valores)" + (f" - diferentes: {diff[:5]}" if diff
                                                                               else ""))
svc_after = {n: (services.get_service(n) or {}).get("start") for n in services.PROFILES}
sdiff = {n: (svc_before[n], svc_after[n]) for n in svc_before if svc_before[n] != svc_after[n]}
check(not sdiff, "Serviços com inicialização original" + (f" - diferentes: {sdiff}" if sdiff else ""))
pf_after = pj("$c=Get-CimInstance Win32_ComputerSystem; [pscustomobject]@{Auto=$c.AutomaticManagedPagefile; "
              "Files=@(Get-CimInstance Win32_PageFileSetting | ForEach-Object { \"$($_.Name)|$($_.InitialSize)|"
              "$($_.MaximumSize)\" })}")
check(pf_before == pf_after, f"Paginação restaurada ({pf_before} = {pf_after})")
tasks_after = {t["full"]: t["enabled"] for t in system_mods.list_tasks()}
tdiff = [k for k in tasks_before if tasks_before[k] != tasks_after.get(k)]
check(not tdiff, "Tarefas agendadas no estado original" + (f" - diferentes: {tdiff}" if tdiff else ""))

print("\n".join(notes))
print("\n".join(fails))
print(f"\nRESULTADO: {len(notes)} verificações OK/avisos, {len(fails)} falhas")
sys.exit(1 if fails else 0)
