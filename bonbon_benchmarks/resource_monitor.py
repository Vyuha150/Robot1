"""Resource benchmarking: CPU/RAM/disk (reused as-is from bonbon_safety)
plus CPU temperature and thermal-throttle detection, which nothing in the
repo samples today (confirmed: bonbon_hardware_telemetry's pi_metrics.py
takes temperature as an externally-supplied argument; bonbon_edge_ai_runtime's
ResourceGuard.evaluate(temp_c=...) does too -- neither reads it).
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path

from bonbon_safety.core.resource_monitor import ResourceMonitor, ResourceSnapshot

import bonbon_benchmarks  # noqa: F401 -- triggers the sys.path bootstrap

_KNOWN_EDGE_ARCHITECTURES = frozenset({"aarch64", "armv7l", "armv6l"})
_THERMAL_ZONE_PATHS = tuple(Path(f"/sys/class/thermal/thermal_zone{i}/temp") for i in range(4))
_RPI_THROTTLE_PATH = Path("/sys/devices/platform/soc/soc:firmware/get_throttled")


def is_edge_device(machine: str | None = None) -> bool:
    """Same rule bonbon_data_pipeline.dataset_downloader.is_edge_device
    uses -- architecture-based, not a hostname/env-var guess."""
    return (machine or platform.machine()).lower() in _KNOWN_EDGE_ARCHITECTURES


def read_cpu_temperature_c() -> float | None:
    """Real CPU temperature via the standard Linux thermal_zone sysfs path
    (same technique as scripts/data/benchmark_candidate_on_pi.py). Tries
    each thermal_zone index in turn since which index maps to the CPU
    varies by board. Returns None -- never a guess -- when unreadable
    (this dev environment: Windows, no such path)."""
    for path in _THERMAL_ZONE_PATHS:
        try:
            raw = path.read_text(encoding="utf-8").strip()
            return float(raw) / 1000.0
        except (OSError, ValueError):
            continue
    return None


def read_throttle_status() -> dict | None:
    """Raspberry Pi's own throttling bitmask (vcgencmd get_throttled /
    the equivalent sysfs path) -- bit 0 = currently under-voltage, bit 1 =
    currently throttled, bit 2 = currently thermal-throttled; bits 16-19
    are the sticky "has happened since boot" versions. Returns None when
    unreadable (not a real Pi), never a fabricated "not throttled"."""
    try:
        raw = _RPI_THROTTLE_PATH.read_text(encoding="utf-8").strip()
        value = int(raw, 16) if raw.startswith("0x") else int(raw)
    except (OSError, ValueError):
        return None
    return {
        "raw": hex(value),
        "under_voltage_now": bool(value & 0x1),
        "throttled_now": bool(value & 0x2),
        "thermal_throttled_now": bool(value & 0x4),
        "under_voltage_since_boot": bool(value & 0x10000),
        "throttled_since_boot": bool(value & 0x20000),
        "thermal_throttled_since_boot": bool(value & 0x40000),
    }


@dataclass
class FullResourceSnapshot:
    cpu_percent: float
    memory_percent: float
    memory_mb: float
    disk_free_percent: float
    temperature_c: float | None
    throttled: bool | None
    available: bool
    on_edge_device: bool

    def to_dict(self) -> dict:
        return {
            "cpuPercent": self.cpu_percent,
            "memoryPercent": self.memory_percent,
            "memoryMb": self.memory_mb,
            "diskFreePercent": self.disk_free_percent,
            "temperatureC": self.temperature_c,
            "throttled": self.throttled,
            "available": self.available,
            "onEdgeDevice": self.on_edge_device,
        }


class FullResourceMonitor:
    """Wraps bonbon_safety.core.resource_monitor.ResourceMonitor (CPU/RAM/
    disk, unchanged) and adds temperature + throttle sampling."""

    def __init__(self, data_path: str = "/") -> None:
        self._base = ResourceMonitor(data_path=data_path)

    def sample(self) -> FullResourceSnapshot:
        base: ResourceSnapshot = self._base.sample()
        throttle = read_throttle_status()
        return FullResourceSnapshot(
            cpu_percent=base.cpu_percent,
            memory_percent=base.memory_percent,
            memory_mb=base.memory_mb,
            disk_free_percent=base.disk_free_percent,
            temperature_c=read_cpu_temperature_c(),
            throttled=throttle["thermal_throttled_now"] if throttle else None,
            available=base.available,
            on_edge_device=is_edge_device(),
        )
