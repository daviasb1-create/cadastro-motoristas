"""Monitoramento em tempo real: CPU, GPU, RAM, disco, rede e temperaturas.

GPU: nvidia-smi (NVIDIA) ou contadores de desempenho 'GPU Engine' do Windows (qualquer fabricante).
Temperatura: LibreHardwareMonitor/OpenHardwareMonitor (se estiverem abertos, mais preciso),
contador 'Thermal Zone Information' do Windows ou nvidia-smi para a GPU.
"""
from __future__ import annotations

import os
import re
import shutil
import threading
import time
from collections import deque

import psutil

from ..config import IS_WINDOWS
from ..utils import CREATE_NO_WINDOW, log

HISTORY = 60


class GpuProbe:
    def __init__(self):
        self.name = ""
        self.nvsmi = shutil.which("nvidia-smi") or (
            r"C:\Windows\System32\nvidia-smi.exe" if os.path.exists(r"C:\Windows\System32\nvidia-smi.exe") else None)
        self._pdh = None
        self._pdh_counters = []
        self._pdh_time = 0.0
        self._mem_counters = []

    def _nvidia(self):
        import subprocess
        try:
            out = subprocess.run([self.nvsmi, "--query-gpu=utilization.gpu,temperature.gpu,memory.used,"
                                  "memory.total,name", "--format=csv,noheader,nounits"], capture_output=True,
                                 text=True, timeout=3, creationflags=CREATE_NO_WINDOW).stdout.strip()
            util, temp, used, total, name = [x.strip() for x in out.splitlines()[0].split(",")][:5]
            self.name = name
            return {"util": float(util), "temp": float(temp), "mem_used": float(used) * 1048576,
                    "mem_total": float(total) * 1048576}
        except Exception:
            self.nvsmi = None
            return None

    def _pdh_read(self):
        try:
            import win32pdh
        except ImportError:
            return None
        now = time.time()
        if self._pdh is None or now - self._pdh_time > 15:  # reexpande: instâncias mudam com os processos
            try:
                if self._pdh:
                    win32pdh.CloseQuery(self._pdh)
                q = win32pdh.OpenQuery()
                paths = win32pdh.ExpandCounterPath(r"\GPU Engine(*engtype_3D)\Utilization Percentage")
                self._pdh_counters = [(p, win32pdh.AddCounter(q, p)) for p in paths]
                mpaths = win32pdh.ExpandCounterPath(r"\GPU Adapter Memory(*)\Dedicated Usage")
                self._mem_counters = [win32pdh.AddCounter(q, p) for p in mpaths]
                win32pdh.CollectQueryData(q)
                self._pdh, self._pdh_time = q, now
                return None
            except Exception as e:
                log.debug("PDH GPU indisponível: %s", e)
                self._pdh = None
                return None
        try:
            win32pdh.CollectQueryData(self._pdh)
        except Exception:
            self._pdh = None
            return None
        per_adapter: dict[str, float] = {}
        for path, c in self._pdh_counters:
            try:
                v = win32pdh.GetFormattedCounterValue(c, win32pdh.PDH_FMT_DOUBLE)[1]
            except Exception:
                continue
            m = re.search(r"luid_(\w+?)_(\w+?)_phys_(\d+)", path)
            key = m.group(0) if m else "gpu"
            per_adapter[key] = per_adapter.get(key, 0.0) + v
        mem = 0.0
        for c in self._mem_counters:
            try:
                mem = max(mem, win32pdh.GetFormattedCounterValue(c, win32pdh.PDH_FMT_LARGE)[1])
            except Exception:
                pass
        if not per_adapter:
            return {"util": 0.0, "temp": None, "mem_used": mem, "mem_total": None}
        return {"util": min(100.0, max(per_adapter.values())), "temp": None, "mem_used": mem, "mem_total": None}

    def read(self):
        if not IS_WINDOWS:
            return None
        if self.nvsmi:
            r = self._nvidia()
            if r:
                return r
        return self._pdh_read()


class TempProbe:
    def __init__(self):
        self._wmi = None
        self._ns = None
        self._pdh = None
        self._pdh_counters = []
        self.source = ""

    def _init_wmi(self):
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            for ns in ("root\\LibreHardwareMonitor", "root\\OpenHardwareMonitor"):
                try:
                    svc = win32com.client.GetObject(f"winmgmts:{ns}")
                    if len(list(svc.ExecQuery("SELECT * FROM Sensor WHERE SensorType='Temperature'"))):
                        self._wmi, self._ns = svc, ns
                        self.source = ns.split("\\")[-1]
                        return
                except Exception:
                    continue
        except Exception:
            pass

    def read(self) -> dict:
        if not IS_WINDOWS:
            return {}
        if self._wmi is None and self._ns is None:
            self._ns = ""
            self._init_wmi()
        if self._wmi is not None:
            try:
                cpu, gpu = [], []
                for s in self._wmi.ExecQuery("SELECT Name,Value,Identifier FROM Sensor WHERE SensorType='Temperature'"):
                    ident = str(s.Identifier).lower()
                    if "cpu" in ident:
                        cpu.append(float(s.Value))
                    elif "gpu" in ident:
                        gpu.append(float(s.Value))
                return {"cpu": max(cpu) if cpu else None, "gpu": max(gpu) if gpu else None}
            except Exception:
                self._wmi = None
        # Contador de zona térmica do Windows (Kelvin), não exige administrador
        try:
            import win32pdh
            if self._pdh is None:
                self._pdh = win32pdh.OpenQuery()
                paths = win32pdh.ExpandCounterPath(r"\Thermal Zone Information(*)\Temperature")
                self._pdh_counters = [win32pdh.AddCounter(self._pdh, p) for p in paths]
                self.source = "Zona térmica ACPI"
            win32pdh.CollectQueryData(self._pdh)
            vals = []
            for c in self._pdh_counters:
                try:
                    k = win32pdh.GetFormattedCounterValue(c, win32pdh.PDH_FMT_DOUBLE)[1]
                    if 250 < k < 400:
                        vals.append(k - 273.15)
                except Exception:
                    pass
            return {"cpu": max(vals) if vals else None}
        except Exception:
            return {}


class SystemMonitor(threading.Thread):
    def __init__(self, interval: float = 1.0):
        super().__init__(daemon=True, name="SystemMonitor")
        self.interval = interval
        self._halt = threading.Event()
        self.lock = threading.Lock()
        self.gpu = GpuProbe()
        self.temps = TempProbe()
        self.history = {k: deque([0.0] * HISTORY, maxlen=HISTORY) for k in ("cpu", "ram", "gpu", "disk")}
        self.snapshot: dict = {}
        self.listeners: list = []
        self.cpu_name = _cpu_name()
        self._tick = 0

    def stop(self):
        self._halt.set()

    def run(self):
        if IS_WINDOWS:
            try:
                import pythoncom
                pythoncom.CoInitialize()
            except Exception:
                pass
        psutil.cpu_percent(None)
        last_disk = psutil.disk_io_counters()
        last_net = psutil.net_io_counters()
        last_t = time.time()
        gpu_data, temp_data = None, {}
        while not self._halt.wait(self.interval):
            now = time.time()
            dt = max(0.1, now - last_t)
            last_t = now
            cpu = psutil.cpu_percent(None)
            per_core = psutil.cpu_percent(None, percpu=True)
            freq = psutil.cpu_freq()
            vm = psutil.virtual_memory()
            disk = psutil.disk_io_counters()
            net = psutil.net_io_counters()
            d_read = (disk.read_bytes - last_disk.read_bytes) / dt if disk and last_disk else 0
            d_write = (disk.write_bytes - last_disk.write_bytes) / dt if disk and last_disk else 0
            if disk and last_disk and hasattr(disk, "busy_time"):
                busy = (disk.busy_time - last_disk.busy_time) / (dt * 10)
            elif disk and last_disk:
                busy = ((disk.read_time - last_disk.read_time) + (disk.write_time - last_disk.write_time)) / (dt * 10)
            else:
                busy = 0
            busy = max(0.0, min(100.0, busy))
            n_up = (net.bytes_sent - last_net.bytes_sent) / dt
            n_down = (net.bytes_recv - last_net.bytes_recv) / dt
            last_disk, last_net = disk, net
            if self._tick % 2 == 0:
                gpu_data = self.gpu.read()
            if self._tick % 3 == 0:
                temp_data = self.temps.read()
            self._tick += 1
            gpu_util = gpu_data["util"] if gpu_data else None
            cpu_temp = temp_data.get("cpu")
            gpu_temp = (gpu_data or {}).get("temp") or temp_data.get("gpu")
            sys_drive = os.environ.get("SystemDrive", "C:") + os.sep if IS_WINDOWS else "/"
            du = psutil.disk_usage(sys_drive)
            snap = {
                "cpu": cpu, "per_core": per_core, "freq": freq.current if freq else None,
                "freq_max": freq.max if freq else None, "cores": psutil.cpu_count(False),
                "threads": psutil.cpu_count(), "cpu_name": self.cpu_name,
                "ram": vm.percent, "ram_used": vm.total - vm.available, "ram_total": vm.total,
                "gpu": gpu_util, "gpu_name": self.gpu.name, "gpu_mem": (gpu_data or {}).get("mem_used"),
                "gpu_mem_total": (gpu_data or {}).get("mem_total"),
                "disk": busy, "disk_read": d_read, "disk_write": d_write,
                "disk_free": du.free, "disk_total": du.total, "disk_pct": du.percent,
                "net_up": n_up, "net_down": n_down, "cpu_temp": cpu_temp, "gpu_temp": gpu_temp,
                "temp_source": self.temps.source, "time": now,
            }
            snap["score"] = performance_score(snap)
            with self.lock:
                self.snapshot = snap
                self.history["cpu"].append(cpu)
                self.history["ram"].append(vm.percent)
                self.history["gpu"].append(gpu_util or 0)
                self.history["disk"].append(busy)

    def get(self) -> dict:
        with self.lock:
            return dict(self.snapshot)

    def get_history(self, key: str) -> list[float]:
        with self.lock:
            return list(self.history[key])


def performance_score(s: dict) -> int:
    """Índice de desempenho 0-100: quanto de folga o PC tem agora (carga, RAM, disco, temperatura)."""
    score = 100.0
    score -= max(0, s["cpu"] - 50) * 0.6
    score -= max(0, s["ram"] - 60) * 0.9
    score -= max(0, s["disk"] - 50) * 0.3
    score -= max(0, s["disk_pct"] - 85) * 1.0
    t = s.get("cpu_temp")
    if t:
        score -= max(0, t - 80) * 2
    gt = s.get("gpu_temp")
    if gt:
        score -= max(0, gt - 83) * 2
    return int(max(0, min(100, round(score))))


def score_label(score: int) -> str:
    return "EXCELENTE" if score >= 85 else "BOM" if score >= 65 else "REGULAR" if score >= 40 else "CRÍTICO"


def _cpu_name() -> str:
    if IS_WINDOWS:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    import platform
    return platform.processor() or "CPU"
