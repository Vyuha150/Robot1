"""Lightweight CPU / memory / disk resource monitor for edge devices.

Uses ``psutil`` when available; otherwise degrades to safe zero readings so it
never crashes a node on a minimal image. Designed to be polled at ~1 Hz from a
node timer and to drive load-shedding decisions (System failures 41/42/43 in the
failure catalogue) and the ModuleHealth cpu_percent / memory_mb fields.

Pure Python, dependency-optional → unit-testable with an injected reader.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

_logger = logging.getLogger(__name__)

try:  # psutil is optional — present on the robot, often absent in CI/sim.
    import psutil  # type: ignore
    _HAS_PSUTIL = True
except Exception:  # noqa: BLE001
    _HAS_PSUTIL = False


@dataclass
class ResourceSnapshot:
    """One sample of system resource usage."""

    cpu_percent: float          # 0–100 (system-wide)
    memory_percent: float       # 0–100
    memory_mb: float            # process RSS, MB
    disk_free_percent: float    # 0–100 free on the data partition
    available: bool             # True when real metrics were read

    # ── derived load-shedding flags ──────────────────────────────────────────
    @property
    def cpu_overloaded(self) -> bool:
        return self.cpu_percent >= 90.0

    @property
    def memory_pressure(self) -> bool:
        return self.memory_percent >= 85.0

    @property
    def disk_low(self) -> bool:
        return self.available and self.disk_free_percent <= 10.0


# Reader signature: () -> (cpu%, mem%, rss_mb, disk_free%)
ResourceReader = Callable[[], tuple]


def _psutil_reader(path: str) -> tuple:
    cpu = psutil.cpu_percent(interval=None)
    vm = psutil.virtual_memory()
    rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
    try:
        du = psutil.disk_usage(path)
        disk_free = 100.0 - du.percent
    except Exception:  # noqa: BLE001
        disk_free = 100.0
    return (cpu, vm.percent, rss_mb, disk_free)


class ResourceMonitor:
    """Polls system resources and exposes the latest snapshot.

    Args:
        data_path: Partition to check for free disk space.
        reader: Optional injected reader (for tests). Defaults to psutil, or a
            zero reader when psutil is unavailable.
    """

    def __init__(self, data_path: str = "/", reader: Optional[ResourceReader] = None) -> None:
        self._path = data_path
        if reader is not None:
            self._reader = reader
            self._real = True
        elif _HAS_PSUTIL:
            self._reader = lambda: _psutil_reader(self._path)
            self._real = True
        else:
            self._reader = lambda: (0.0, 0.0, 0.0, 100.0)
            self._real = False
            _logger.info("psutil unavailable — ResourceMonitor returns zero readings")
        self._last = ResourceSnapshot(0.0, 0.0, 0.0, 100.0, self._real)

    def sample(self) -> ResourceSnapshot:
        """Read and cache the current resource snapshot."""
        try:
            cpu, mem, rss, disk = self._reader()
            self._last = ResourceSnapshot(
                cpu_percent=float(cpu), memory_percent=float(mem),
                memory_mb=float(rss), disk_free_percent=float(disk),
                available=self._real,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning("ResourceMonitor read failed: %s", exc)
            self._last = ResourceSnapshot(0.0, 0.0, 0.0, 100.0, False)
        return self._last

    @property
    def last(self) -> ResourceSnapshot:
        return self._last

    def recommended_load_shed(self) -> float:
        """Suggested processing-rate multiplier in (0,1] based on current load.

        1.0 = full rate; lower when CPU/memory are under pressure. Lets nodes
        adaptively reduce inference/publish rates (System failures 41/42).
        """
        s = self._last
        scale = 1.0
        if s.cpu_overloaded:
            scale = min(scale, 0.5)
        elif s.cpu_percent >= 75.0:
            scale = min(scale, 0.75)
        if s.memory_pressure:
            scale = min(scale, 0.5)
        return scale
