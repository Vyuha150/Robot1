"""DistributedStatusTracker — Pi-1's live view of the other two Pis.

Pure Python, no rclpy dependency (fully unit-testable, unlike most of
ros2_bridge.py which requires a real ROS2 install). Holds what the
dashboard needs to answer "is Pi-2/Pi-3 alive, and what did Pi-3's motion
approval gateway most recently decide" — fed by `_DashboardNode`'s
subscriptions to /bonbon/pi{2,3}/heartbeat, /bonbon/safety/approval,
/bonbon/safety/rejection, and /bonbon/system/degraded_mode.

Deliberately reimplements a minimal heartbeat-staleness check rather than
importing bonbon_distributed_safety.core.heartbeat_monitor — Pi-1's
dashboard package has no reason to depend on a Pi-3-navigation-safety
package for a five-line staleness comparison, and keeping them decoupled
means a bonbon_distributed_safety change can never accidentally break the
dashboard build. The threshold values are intentionally the same defaults
as config/distributed/robot_network.yaml's heartbeat.* keys.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class LinkState(StrEnum):
    ONLINE = "online"
    STALE = "stale"
    LOST = "lost"
    UNKNOWN = "unknown"  # no heartbeat AND no bridge connection at all


_STALE_AFTER_SEC = 1.5
_LOST_AFTER_SEC = 5.0

_MONITORED_PIS = ("pi1", "pi2", "pi3")


@dataclass
class DistributedStatusTracker:
    _last_heartbeat: dict[str, float] = field(default_factory=dict)
    _last_approval: dict[str, Any] | None = None
    _last_rejection: dict[str, Any] | None = None
    _last_degraded_mode: dict[str, Any] | None = None
    _approval_count: int = 0
    _rejection_count: int = 0

    def record_heartbeat(self, pi_id: str, now: float | None = None) -> None:
        if pi_id not in _MONITORED_PIS:
            raise ValueError(f"unknown pi_id {pi_id!r}")
        self._last_heartbeat[pi_id] = now if now is not None else time.monotonic()

    def record_approval(self, decision: dict[str, Any]) -> None:
        self._last_approval = decision
        self._approval_count += 1

    def record_rejection(self, decision: dict[str, Any]) -> None:
        self._last_rejection = decision
        self._rejection_count += 1

    def record_degraded_mode(self, payload: dict[str, Any]) -> None:
        self._last_degraded_mode = payload

    def link_state(self, pi_id: str, now: float | None = None) -> LinkState:
        last = self._last_heartbeat.get(pi_id)
        if last is None:
            return LinkState.LOST
        age = (now if now is not None else time.monotonic()) - last
        if age >= _LOST_AFTER_SEC:
            return LinkState.LOST
        if age >= _STALE_AFTER_SEC:
            return LinkState.STALE
        return LinkState.ONLINE

    def snapshot(self, now: float | None = None) -> dict[str, Any]:
        now = now if now is not None else time.monotonic()
        return {
            "pi_links": {pi: self.link_state(pi, now).value for pi in _MONITORED_PIS},
            "last_approval": self._last_approval,
            "last_rejection": self._last_rejection,
            "last_degraded_mode": self._last_degraded_mode,
            "approval_count": self._approval_count,
            "rejection_count": self._rejection_count,
        }
