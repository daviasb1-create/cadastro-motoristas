"""Cliente da API local gRPC da Starlink (antena + roteador integrado da Starlink Mini).

Fonte dos dados
---------------
* A Starlink NÃO publica documentação oficial da API local para o kit residencial/Mini.
  Ela expõe um serviço gRPC sem autenticação na LAN (``SpaceX.API.Device.Device/Handle``)
  com *server reflection* habilitado. É o mesmo canal usado pelo app oficial.
* Este módulo não embute ``.proto`` próprios: as definições são obtidas por reflection
  direto do equipamento (bibliotecas ``starlink-grpc-core`` e ``yagrc``). Se o firmware
  remover um campo, o código detecta e informa, em vez de inventar valores.

Endereços
---------
* Antena: ``192.168.100.1:9200`` (padrão documentado pela comunidade e usado pelo app).
* Lista de clientes Wi-Fi (``wifi_get_clients``): o roteador integrado da Mini é sondado
  em uma lista de alvos configurável. O primeiro que responder é memorizado.
"""
from __future__ import annotations

import logging
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

try:  # dependências reais; ausência é reportada na UI
    import grpc
    import starlink_grpc
    from google.protobuf.json_format import MessageToDict
    from yagrc import reflector

    GRPC_AVAILABLE = True
except Exception as exc:  # pragma: no cover - ambiente sem dependências
    GRPC_AVAILABLE = False
    log.warning("gRPC indisponível: %s", exc)

STATE_PT = {
    "CONNECTED": "Conectada",
    "SEARCHING": "Procurando satélites",
    "BOOTING": "Inicializando",
    "STOWED": "Recolhida",
    "THERMAL_SHUTDOWN": "Desligada por temperatura",
    "NO_SATS": "Sem satélites",
    "OBSTRUCTED": "Obstruída",
    "NO_DOWNLINK": "Sem downlink",
    "NO_PINGS": "Sem resposta de ping",
    "UNKNOWN": "Desconhecido",
    "OFFLINE": "Sem comunicação",
}

ALERT_PT = {
    "alert_motors_stuck": "Motores travados",
    "alert_thermal_throttle": "Desempenho reduzido por temperatura",
    "alert_thermal_shutdown": "Desligamento por temperatura",
    "alert_mast_not_near_vertical": "Antena fora da vertical",
    "alert_unexpected_location": "Localização inesperada",
    "alert_slow_ethernet_speeds": "Ethernet lenta",
    "alert_slow_ethernet_speeds_100": "Ethernet limitada a 100 Mbps",
    "alert_roaming": "Em roaming",
    "alert_install_pending": "Atualização pendente",
    "alert_is_heating": "Aquecimento ativo (neve/gelo)",
    "alert_power_supply_thermal_throttle": "Fonte com redução térmica",
    "alert_is_power_save_idle": "Modo economia de energia",
    "alert_moving_while_not_mobile": "Em movimento sem plano de mobilidade",
    "alert_moving_too_fast_for_policy": "Velocidade acima do permitido pelo plano",
    "alert_dbf_telem_stale": "Telemetria interna desatualizada",
    "alert_low_motor_current": "Corrente baixa no motor",
    "alert_lower_signal_than_predicted": "Sinal abaixo do previsto",
    "alert_obstruction_map_reset": "Mapa de obstrução reiniciado",
}

IFACE_PT = {"ETH": "Cabo", "RF_2GHZ": "Wi-Fi 2,4 GHz", "RF_5GHZ": "Wi-Fi 5 GHz", "RF_5GHZ_HIGH": "Wi-Fi 5 GHz (alto)"}


@dataclass
class StarlinkSnapshot:
    ok: bool
    ts: float = field(default_factory=time.time)
    error: str | None = None
    status: dict[str, Any] = field(default_factory=dict)
    active_alerts: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def state(self) -> str:
        return self.status.get("state") or ("UNKNOWN" if self.ok else "OFFLINE")

    @property
    def state_pt(self) -> str:
        return STATE_PT.get(self.state, self.state)


@dataclass
class WifiClientsResult:
    ok: bool
    clients: list[dict] = field(default_factory=list)
    target: str | None = None
    error: str | None = None


def _to_int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def normalize_wifi_client(c: dict) -> dict:
    """Converte um WifiClient (dict do protobuf) para o formato interno.

    Nomes de campos conferidos nos protos extraídos da própria antena (``wifi.proto``):
    name, given_name, mac_address, ip_address, signal_strength, iface, rx_stats.bytes,
    tx_stats.bytes, associated_time_s, snr, domain. Contadores são do ponto de vista do
    roteador: rx = recebido do dispositivo (upload dele), tx = enviado ao dispositivo.
    """
    mac = (c.get("mac_address") or "").lower().replace("-", ":")
    iface = c.get("iface")
    rx = (c.get("rx_stats") or {}).get("bytes")
    tx = (c.get("tx_stats") or {}).get("bytes")
    return {
        "mac": mac,
        "ip": c.get("ip_address") or None,
        "hostname": c.get("given_name") or c.get("name") or "",
        "router_name": c.get("name") or "",
        "signal": c.get("signal_strength"),
        "snr": c.get("snr"),
        "iface": IFACE_PT.get(str(iface), str(iface) if iface is not None else None),
        "router_rx_bytes": _to_int(rx),  # upload do dispositivo
        "router_tx_bytes": _to_int(tx),  # download do dispositivo
        "associated_s": _to_int(c.get("associated_time_s")),
        "domain": c.get("domain") or "",
    }


def reachable(target: str, timeout: float = 2.0) -> bool:
    """Teste TCP rápido para não bloquear a coleta quando o equipamento está fora do ar."""
    host, _, port = target.rpartition(":")
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


class StarlinkClient:
    def __init__(self, dish_target: str = "192.168.100.1:9200", router_targets: list[str] | None = None,
                 timeout: float = 5.0):
        self.dish_target = dish_target
        self.router_targets = list(router_targets or ["192.168.100.1:9200", "192.168.1.1:9000"])
        self.timeout = timeout
        self._ctx = None
        self._lock = threading.Lock()
        self._router_target_ok: str | None = None
        self._router_classes: dict[str, tuple[Any, Any]] = {}
        self.router_probe_log: list[str] = []

    # ------------------------------------------------------------ antena
    def _context(self):
        if self._ctx is None:
            self._ctx = starlink_grpc.ChannelContext(target=self.dish_target)
        return self._ctx

    def close(self) -> None:
        with self._lock:
            if self._ctx is not None:
                self._ctx.close()
                self._ctx = None

    def get_status(self) -> StarlinkSnapshot:
        if not GRPC_AVAILABLE:
            return StarlinkSnapshot(ok=False, error="Bibliotecas gRPC não instaladas")
        if not reachable(self.dish_target):
            self.close()
            return StarlinkSnapshot(ok=False, error=f"Antena não acessível em {self.dish_target} "
                                                    "(verifique se este PC está na rede Wi-Fi da Starlink)")
        with self._lock:
            try:
                status, obstruction, alerts = starlink_grpc.status_data(context=self._context())
            except starlink_grpc.GrpcError as e:
                self._ctx = None
                return StarlinkSnapshot(ok=False, error=f"Antena não respondeu em {self.dish_target}: {e}")
            except Exception as e:  # noqa: BLE001 - qualquer falha vira estado offline
                self._ctx = None
                return StarlinkSnapshot(ok=False, error=f"Falha ao consultar a antena: {e}")
            extra: dict[str, Any] = {"obstruction_valid_s": obstruction.get("valid_s")}
            try:  # campos adicionais presentes em firmwares recentes (opcionais)
                raw = starlink_grpc.get_status(context=self._context())
                d = MessageToDict(raw, preserving_proto_field_name=True)
                for k in ("eth_speed_mbps", "mobility_class", "class_of_service", "disablement_code",
                          "software_update_state", "has_actuators", "is_cell_disabled"):
                    if k in d:
                        extra[k] = d[k]
                dev = d.get("device_info", {})
                for k in ("country_code", "utc_offset_s", "bootcount", "board_rev"):
                    if k in dev:
                        extra[k] = dev[k]
            except Exception:  # noqa: BLE001
                pass
        active = [k for k, v in alerts.items() if v]
        return StarlinkSnapshot(ok=True, status=status, active_alerts=active, extra=extra)

    def get_history_stats(self, samples: int = 900) -> dict[str, Any]:
        """Estatísticas dos últimos ``samples`` segundos calculadas pela própria antena."""
        if not GRPC_AVAILABLE:
            return {}
        with self._lock:
            try:
                groups = starlink_grpc.history_stats(samples, context=self._context())
            except Exception as e:  # noqa: BLE001
                return {"error": str(e)}
        out: dict[str, Any] = {}
        for g in groups:
            if isinstance(g, dict):
                out.update(g)
        return out

    # ----------------------------------------------------------- roteador
    def _router_call(self, target: str):
        if not reachable(target):
            raise RuntimeError("porta não acessível")
        channel = grpc.insecure_channel(target)
        try:
            if target not in self._router_classes:
                client = reflector.GrpcReflectionClient()
                client.load_protocols(channel, symbols=["SpaceX.API.Device.Device"])
                self._router_classes[target] = (
                    client.service_stub_class("SpaceX.API.Device.Device"),
                    client.message_class("SpaceX.API.Device.Request"),
                )
            stub_cls, request_cls = self._router_classes[target]
            try:
                req = request_cls(wifi_get_clients={})
            except ValueError as e:
                raise RuntimeError("firmware não expõe 'wifi_get_clients' neste alvo") from e
            resp = stub_cls(channel).Handle(req, timeout=self.timeout)
            if not resp.HasField("wifi_get_clients"):
                raise RuntimeError("resposta sem 'wifi_get_clients'")
            d = MessageToDict(resp.wifi_get_clients, preserving_proto_field_name=True)
            return [normalize_wifi_client(c) for c in d.get("clients", [])]
        finally:
            channel.close()

    def get_wifi_clients(self) -> WifiClientsResult:
        if not GRPC_AVAILABLE:
            return WifiClientsResult(ok=False, error="Bibliotecas gRPC não instaladas")
        targets = ([self._router_target_ok] if self._router_target_ok else []) + [
            t for t in self.router_targets if t != self._router_target_ok
        ]
        errors = []
        for t in targets:
            try:
                clients = self._router_call(t)
                self._log_probe(errors)
                if self._router_target_ok != t:
                    self.router_probe_log.append(f"{time.strftime('%H:%M:%S')} {t}: OK ({len(clients)} clientes)")
                self._router_target_ok = t
                return WifiClientsResult(ok=True, clients=clients, target=t)
            except Exception as e:  # noqa: BLE001
                msg = e.details() if hasattr(e, "details") and callable(e.details) else str(e)
                errors.append(f"{t}: {msg}")
                self._router_classes.pop(t, None)
                if t == self._router_target_ok:
                    self._router_target_ok = None
        self._log_probe(errors)
        return WifiClientsResult(ok=False, error="; ".join(errors))

    def _log_probe(self, errors: list[str]) -> None:
        self.router_probe_log.extend(f"{time.strftime('%H:%M:%S')} {e}" for e in errors)
        self.router_probe_log = self.router_probe_log[-50:]
