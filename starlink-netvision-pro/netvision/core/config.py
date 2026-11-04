"""Configurações persistentes em JSON."""
from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field, fields
from typing import Any

from netvision.core import paths


@dataclass
class Settings:
    # Starlink
    dish_target: str = "192.168.100.1:9200"
    # Alvos testados (em ordem) para a lista de clientes Wi-Fi do roteador integrado.
    router_targets: list[str] = field(default_factory=lambda: ["192.168.100.1:9200", "192.168.1.1:9000"])
    starlink_interval_s: float = 2.0
    wifi_clients_interval_s: float = 30.0

    # Latência
    ping_targets: list[str] = field(default_factory=lambda: ["1.1.1.1", "8.8.8.8"])
    ping_interval_s: float = 1.0
    ping_timeout_ms: int = 1000
    latency_window: int = 60  # amostras usadas para jitter/perda

    # Scanner
    scan_interval_s: float = 60.0
    scan_offline_after_misses: int = 2
    scan_resolve_names: bool = True

    # Teste de velocidade
    speedtest_auto: bool = True
    speedtest_interval_min: int = 180
    speedtest_duration_s: float = 8.0
    speedtest_streams: int = 4
    speedtest_base_url: str = "https://speed.cloudflare.com"

    # Aplicativos
    app_monitor_enabled: bool = True
    capture_interface: str = ""  # vazio = automático

    # DNS local (identificação de serviços na rede)
    dns_proxy_enabled: bool = False
    dns_proxy_port: int = 53
    dns_upstream: str = "1.1.1.1"

    # Geral
    start_with_windows: bool = False
    start_minimized: bool = False
    monitoring_on_start: bool = True
    notify_new_devices: bool = True
    alert_ping_ms: float = 150.0
    alert_loss_pct: float = 5.0
    data_retention_days: int = 400

    @classmethod
    def load(cls) -> "Settings":
        p = paths.config_path()
        s = cls()
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                known = {f.name for f in fields(cls)}
                for k, v in raw.items():
                    if k in known:
                        setattr(s, k, v)
            except (OSError, ValueError):
                pass
        return s

    def save(self) -> None:
        with _lock:
            p = paths.config_path()
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(p)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_lock = threading.Lock()
