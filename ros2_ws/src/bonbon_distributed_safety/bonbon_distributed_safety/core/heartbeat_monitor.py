"""HeartbeatMonitor — tracks per-Pi liveness for the three-Pi deployment.

Pure Python, no rclpy dependency, so it is fully unit-testable in any
environment. The ROS2 node wrapper (nodes/distributed_safety_node.py) feeds
it real /bonbon/pi{1,2,3}/heartbeat message timestamps; tests feed it
synthetic clock values.

Thresholds default to config/distributed/robot_network.yaml's
heartbeat.stale_after_sec / heartbeat.lost_after_sec — kept as constructor
defaults here so this module has no file-I/O dependency, with the node
wrapper responsible for loading the real YAML and passing values in.

Honesty rule: a peer that has never sent a heartbeat is reported LOST, not
ONLINE — there is no "assume healthy until proven otherwise" default,
matching this repo's established no-fake-PASS posture.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PiId(StrEnum):
    PI1 = "pi1"
    PI2 = "pi2"
    PI3 = "pi3"


class PiLinkState(StrEnum):
    ONLINE = "online"
    STALE = "stale"
    LOST = "lost"


@dataclass(frozen=True)
class HeartbeatConfig:
    stale_after_sec: float = 1.5
    lost_after_sec: float = 5.0

    def __post_init__(self) -> None:
        if self.stale_after_sec <= 0 or self.lost_after_sec <= 0:
            raise ValueError("heartbeat thresholds must be positive")
        if self.lost_after_sec <= self.stale_after_sec:
            raise ValueError("lost_after_sec must be greater than stale_after_sec")


@dataclass(frozen=True)
class LinkTransition:
    pi: PiId
    previous_state: PiLinkState
    new_state: PiLinkState
    at: float


class HeartbeatMonitor:
    """Tracks liveness of every OTHER Pi from the perspective of `self_id`."""

    def __init__(
        self,
        self_id: PiId,
        peers: list[PiId] | None = None,
        config: HeartbeatConfig | None = None,
    ) -> None:
        self._self_id = self_id
        self._peers = list(peers) if peers is not None else [p for p in PiId if p != self_id]
        self._config = config or HeartbeatConfig()
        self._last_seen: dict[PiId, float | None] = {p: None for p in self._peers}
        self._last_state: dict[PiId, PiLinkState] = {p: PiLinkState.LOST for p in self._peers}

    @property
    def self_id(self) -> PiId:
        return self._self_id

    @property
    def peers(self) -> list[PiId]:
        return list(self._peers)

    def on_heartbeat(self, pi: PiId, now: float) -> None:
        if pi not in self._last_seen:
            raise ValueError(f"{pi} is not a monitored peer of {self._self_id}")
        self._last_seen[pi] = now

    def _classify(self, pi: PiId, now: float) -> PiLinkState:
        last = self._last_seen[pi]
        if last is None:
            return PiLinkState.LOST
        age = now - last
        if age >= self._config.lost_after_sec:
            return PiLinkState.LOST
        if age >= self._config.stale_after_sec:
            return PiLinkState.STALE
        return PiLinkState.ONLINE

    def state_of(self, pi: PiId, now: float) -> PiLinkState:
        return self._classify(pi, now)

    def snapshot(self, now: float) -> dict[PiId, PiLinkState]:
        return {pi: self._classify(pi, now) for pi in self._peers}

    def evaluate(self, now: float) -> list[LinkTransition]:
        """Classify every peer at `now` and return only the transitions
        (state changes since the last `evaluate()` call). Call this once
        per monitoring tick — repeated calls at the same `now` with no new
        heartbeats produce no new transitions."""
        transitions: list[LinkTransition] = []
        for pi in self._peers:
            new_state = self._classify(pi, now)
            previous = self._last_state[pi]
            if new_state != previous:
                transitions.append(LinkTransition(pi, previous, new_state, now))
                self._last_state[pi] = new_state
        return transitions
