"""bonbon_distributed_network_monitor.core.network_thresholds -- reads
the time_sync thresholds FROM config/distributed/robot_network.yaml,
the single source of truth that file's own header already claims for
this package, rather than re-declaring max_offset_ms/alert_offset_ms as
independent numbers anywhere in this package.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_NETWORK_CONFIG_PATH = _REPO_ROOT / "config" / "distributed" / "robot_network.yaml"


@dataclass(frozen=True)
class TimeSyncThresholds:
    max_offset_ms: float = 50.0
    alert_offset_ms: float = 200.0
    server: str = "pi3"
    poll_interval_sec: float = 30.0

    @classmethod
    def defaults(cls) -> "TimeSyncThresholds":
        return cls()

    @classmethod
    def load(cls, path: str | Path | None = None) -> "TimeSyncThresholds":
        p = Path(path) if path is not None else DEFAULT_NETWORK_CONFIG_PATH
        if not p.exists():
            return cls.defaults()
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        time_sync = raw.get("time_sync") or {}
        return cls(
            max_offset_ms=float(time_sync.get("max_offset_ms", cls.max_offset_ms)),
            alert_offset_ms=float(time_sync.get("alert_offset_ms", cls.alert_offset_ms)),
            server=str(time_sync.get("server", cls.server)),
            poll_interval_sec=float(time_sync.get("poll_interval_sec", cls.poll_interval_sec)),
        )
