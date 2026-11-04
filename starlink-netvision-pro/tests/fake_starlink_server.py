"""Servidor gRPC de TESTE que imita a API local da Starlink.

Usa os descritores reais extraídos da antena (pacote ``starlink-client``, MIT) e expõe
server reflection, exatamente como o equipamento. Assim o cliente do NetVision é testado
pelo mesmo caminho (reflection -> Request -> Handle) que usará com a Starlink Mini real.

Uso: python tests/fake_starlink_server.py <porta> [--no-wifi]
"""
from __future__ import annotations

import sys
import time
from concurrent import futures

import grpc
from grpc_reflection.v1alpha import reflection
from spacex.api.device import device_pb2, device_pb2_grpc

NO_WIFI = "--no-wifi" in sys.argv
START = time.time()


class Device(device_pb2_grpc.DeviceServicer):
    def Handle(self, request, context):
        which = request.WhichOneof("request")
        resp = device_pb2.Response()
        if which == "get_status":
            s = resp.dish_get_status
            s.device_info.id = "ut01000000-00000000-fake0001"
            s.device_info.hardware_version = "mini1_prod2"
            s.device_info.software_version = "2026.10.01.mr12345"
            s.device_info.country_code = "BR"
            s.device_state.uptime_s = int(time.time() - START) + 3600
            s.pop_ping_latency_ms = 31.5
            s.pop_ping_drop_rate = 0.01
            s.downlink_throughput_bps = 12_500_000.0
            s.uplink_throughput_bps = 1_250_000.0
            s.obstruction_stats.fraction_obstructed = 0.02
            s.obstruction_stats.currently_obstructed = False
            s.obstruction_stats.valid_s = 3600
            s.boresight_azimuth_deg = 12.0
            s.boresight_elevation_deg = 65.0
            s.alerts.is_heating = True
            s.eth_speed_mbps = 0
            s.gps_stats.gps_valid = True
            s.gps_stats.gps_sats = 11
        elif which == "get_history":
            h = resp.dish_get_history
            n = 900
            h.current = 5000
            h.pop_ping_drop_rate.extend([0.0] * (n - 10) + [1.0] * 10)
            h.pop_ping_latency_ms.extend([30.0 + (i % 7) for i in range(n)])
            h.downlink_throughput_bps.extend([10_000_000.0] * n)
            h.uplink_throughput_bps.extend([1_000_000.0] * n)
        elif which == "wifi_get_clients":
            if NO_WIFI:
                context.abort(grpc.StatusCode.UNIMPLEMENTED, "Unimplemented")
            for i, (name, mac, ip, iface) in enumerate([
                ("iPhone-de-Ana", "3a:11:22:33:44:55", "192.168.1.20", "RF_5GHZ"),
                ("DESKTOP-GAMER", "00:0c:29:aa:bb:cc", "192.168.1.21", "RF_5GHZ"),
                ("TV-Sala", "b8:27:eb:01:02:03", "192.168.1.22", "RF_2GHZ"),
            ]):
                c = resp.wifi_get_clients.clients.add()
                c.name, c.mac_address, c.ip_address = name, mac, ip
                c.signal_strength = -45.0 - i * 10
                c.iface = getattr(c.Interface, iface) if hasattr(c, "Interface") else 0
                c.rx_stats.bytes = 1_000_000 * (i + 1) + int(time.time() - START) * 1000
                c.tx_stats.bytes = 9_000_000 * (i + 1) + int(time.time() - START) * 10000
                c.associated_time_s = 600 + i
        else:
            context.abort(grpc.StatusCode.UNIMPLEMENTED, "Unimplemented")
        return resp


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 19200
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    device_pb2_grpc.add_DeviceServicer_to_server(Device(), server)
    names = (device_pb2.DESCRIPTOR.services_by_name["Device"].full_name, reflection.SERVICE_NAME)
    reflection.enable_server_reflection(names, server)
    server.add_insecure_port(f"127.0.0.1:{port}")
    server.start()
    print("READY", flush=True)
    server.wait_for_termination()


if __name__ == "__main__":
    main()
