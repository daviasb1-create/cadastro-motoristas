"""Exportação de relatórios (CSV e HTML) a partir do banco local."""
from __future__ import annotations

import csv
import html
import time
from datetime import datetime, timedelta
from pathlib import Path

from netvision import APP_NAME, __version__
from netvision.core.database import Database


def fmt_bytes(n: float | None) -> str:
    if n is None:
        return "-"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:,.1f} {unit}".replace(",", "X").replace(".", ",").replace("X", ".")
        n /= 1024
    return str(n)


def fmt_num(v: float | None, dec: int = 1) -> str:
    if v is None:
        return "-"
    return f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # BOM: abre corretamente no Excel
        if not rows:
            f.write("sem dados\n")
            return
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(rows)


def export_csv(db: Database, out_dir: Path, days: int = 31) -> list[Path]:
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out_dir.mkdir(parents=True, exist_ok=True)
    since = int(time.time()) - days * 86400
    since_day = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    files = {
        f"netvision_minutos_{stamp}.csv": [
            {**r, "ts": datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d %H:%M")} for r in db.minutes(since)
        ],
        f"netvision_diario_{stamp}.csv": db.daily_summary(days),
        f"netvision_mensal_{stamp}.csv": db.monthly_summary(),
        f"netvision_velocidade_{stamp}.csv": [
            {**r, "ts": datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d %H:%M:%S")} for r in db.speedtests(10000)
        ],
        f"netvision_dispositivos_{stamp}.csv": [
            {**r,
             "first_seen": datetime.fromtimestamp(r["first_seen"]).strftime("%Y-%m-%d %H:%M") if r["first_seen"] else "",
             "last_seen": datetime.fromtimestamp(r["last_seen"]).strftime("%Y-%m-%d %H:%M") if r["last_seen"] else ""}
            for r in db.get_devices()
        ],
        f"netvision_aplicativos_{stamp}.csv": db.app_usage(since_day),
        f"netvision_servicos_{stamp}.csv": db.service_usage(since_day),
        f"netvision_eventos_{stamp}.csv": [
            {**r, "ts": datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d %H:%M:%S")} for r in db.events(100000)
        ],
    }
    paths = []
    for name, rows in files.items():
        p = out_dir / name
        _write_csv(p, rows)
        paths.append(p)
    return paths


def _table(headers: list[str], rows: list[list]) -> str:
    th = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    trs = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{trs or '<tr><td colspan=99>Sem dados</td></tr>'}</tbody></table>"


def export_html(db: Database, out_dir: Path, days: int = 31) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    since_day = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    today, month = db.usage_today(), db.usage_month()
    daily = db.daily_summary(days)
    monthly = db.monthly_summary()
    st = db.speedtests(30)
    devs = db.get_devices()
    apps = db.app_usage(since_day)[:25]
    svcs = db.service_usage(since_day)[:40]
    sections = [
        "<h2>Consumo</h2>",
        _table(["Período", "PC download", "PC upload", "Rede (antena) download", "Rede (antena) upload"], [
            ["Hoje", fmt_bytes(today["pc_rx"]), fmt_bytes(today["pc_tx"]), fmt_bytes(today["net_rx"]), fmt_bytes(today["net_tx"])],
            ["Mês atual", fmt_bytes(month["pc_rx"]), fmt_bytes(month["pc_tx"]), fmt_bytes(month["net_rx"]), fmt_bytes(month["net_tx"])],
        ]),
        "<h2>Histórico diário</h2>",
        _table(["Dia", "PC ↓", "PC ↑", "Rede ↓", "Rede ↑", "Ping médio (ms)", "Jitter (ms)", "Perda (%)",
                "Ping antena→PoP (ms)", "Min. monitorados", "Min. sem conexão"],
               [[r["dia"], fmt_bytes(r["pc_rx"]), fmt_bytes(r["pc_tx"]), fmt_bytes(r["net_rx"]), fmt_bytes(r["net_tx"]),
                 fmt_num(r["ping_avg"]), fmt_num(r["jitter"]), fmt_num(r["loss_pct"], 2), fmt_num(r["dish_ping"]),
                 r["minutos"], r["minutos_fora"]] for r in daily]),
        "<h2>Histórico mensal</h2>",
        _table(["Mês", "PC ↓", "PC ↑", "Rede ↓", "Rede ↑", "Ping médio", "Jitter", "Perda (%)"],
               [[r["mes"], fmt_bytes(r["pc_rx"]), fmt_bytes(r["pc_tx"]), fmt_bytes(r["net_rx"]), fmt_bytes(r["net_tx"]),
                 fmt_num(r["ping_avg"]), fmt_num(r["jitter"]), fmt_num(r["loss_pct"], 2)] for r in monthly]),
        "<h2>Testes de velocidade (últimos 30)</h2>",
        _table(["Data", "Download (Mbps)", "Upload (Mbps)", "Ping (ms)", "Resultado"],
               [[datetime.fromtimestamp(r["ts"]).strftime("%d/%m/%Y %H:%M"), fmt_num(r["down_mbps"]), fmt_num(r["up_mbps"]),
                 fmt_num(r["ping_ms"]), "OK" if r["ok"] else (r["error"] or "falha")] for r in st]),
        "<h2>Dispositivos</h2>",
        _table(["Nome", "IP", "MAC", "Fabricante", "Origem", "Status", "Visto pela última vez"],
               [[r["custom_name"] or r["hostname"] or "-", r["ip"], r["mac"], r["vendor"] or "-", r["source"] or "-",
                 "online" if r["online"] else "offline",
                 datetime.fromtimestamp(r["last_seen"]).strftime("%d/%m/%Y %H:%M") if r["last_seen"] else "-"] for r in devs]),
        f"<h2>Aplicativos neste computador ({days} dias)</h2>",
        _table(["Aplicativo", "Download", "Upload"], [[r["app"], fmt_bytes(r["rx"]), fmt_bytes(r["tx"])] for r in apps]),
        f"<h2>Serviços identificados ({days} dias, estimativa)</h2>",
        _table(["Origem", "Serviço", "Ocorrências", "Bytes (somente PC)"],
               [[r["source"], r["service"], r["hits"], fmt_bytes(r["bytes"]) if r["bytes"] else "-"] for r in svcs]),
    ]
    doc = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>Relatório {APP_NAME}</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;background:#0b1220;color:#e2e8f0;margin:32px}}
h1{{color:#22d3ee;margin-bottom:4px}} h2{{color:#93c5fd;margin-top:32px;border-bottom:1px solid #1e293b;padding-bottom:6px}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:8px}}
th{{background:#111a2e;color:#94a3b8;text-align:left;padding:6px 8px}} td{{padding:6px 8px;border-bottom:1px solid #1e293b}}
.note{{color:#94a3b8;font-size:12px}}
@media print{{body{{background:#fff;color:#000}} th{{background:#eee;color:#000}}}}
</style></head><body>
<h1>{APP_NAME}</h1>
<div class="note">Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} · versão {__version__}.
"Rede (antena)" é estimado integrando o throughput informado pela Starlink a cada poucos segundos.
Serviços identificados por DNS/SNI são estimativas.</div>
{''.join(sections)}
</body></html>"""
    p = out_dir / f"netvision_relatorio_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
    p.write_text(doc, encoding="utf-8")
    return p
