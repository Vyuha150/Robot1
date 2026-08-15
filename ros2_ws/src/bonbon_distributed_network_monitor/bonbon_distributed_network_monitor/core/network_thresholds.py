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


@dataclass(frozen=True)
class NetworkQualityThresholds:
    """3-Pi Phase 7 remainder -- reads network_quality FROM
    config/distributed/robot_network.yaml, same single-source-of-truth
    rule as TimeSyncThresholds above."""

    probe_port: int = 22
    probes_per_check: int = 5
    rtt_warn_ms: float = 50.0
    rtt_alert_ms: float = 200.0
    packet_loss_warn_pct: float = 10.0
    packet_loss_alert_pct: float = 30.0
    poll_interval_sec: float = 30.0

    @classmethod
    def defaults(cls) -> "NetworkQualityThresholds":
        return cls()

    @classmethod
    def load(cls, path: str | Path | None = None) -> "NetworkQualityThresholds":
        p = Path(path) if path is not None else DEFAULT_NETWORK_CONFIG_PATH
        if not p.exists():
            return cls.defaults()
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        nq = raw.get("network_quality") or {}
        return cls(
            probe_port=int(nq.get("probe_port", cls.probe_port)),
            probes_per_check=int(nq.get("probes_per_check", cls.probes_per_check)),
            rtt_warn_ms=float(nq.get("rtt_warn_ms", cls.rtt_warn_ms)),
            rtt_alert_ms=float(nq.get("rtt_alert_ms", cls.rtt_alert_ms)),
            packet_loss_warn_pct=float(nq.get("packet_loss_warn_pct", cls.packet_loss_warn_pct)),
            packet_loss_alert_pct=float(
                nq.get("packet_loss_alert_pct", cls.packet_loss_alert_pct)
            ),
            poll_interval_sec=float(nq.get("poll_interval_sec", cls.poll_interval_sec)),
        )


@dataclass(frozen=True)
class PeerTarget:
    """One other Pi to probe -- role name + reachable host."""

    role: str
    hostname: str


def load_peer_targets(self_role: str, path: str | Path | None = None) -> list[PeerTarget]:
    """Reads the `pis` section of robot_network.yaml and returns every Pi
    EXCEPT `self_role` -- a Pi never probes itself for network quality
    (loopback RTT is meaningless as a link-quality signal)."""
    p = Path(path) if path is not None else DEFAULT_NETWORK_CONFIG_PATH
    if not p.exists():
        return []
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    pis = raw.get("pis") or {}
    targets: list[PeerTarget] = []
    for key, entry in pis.items():
        role = str((entry or {}).get("role", key))
        if key == self_role or role == self_role:
            continue
        hostname = str((entry or {}).get("hostname", "")) or key
        targets.append(PeerTarget(role=role, hostname=hostname))
    return targets
