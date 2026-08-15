"""FlapDetector -- tracks how often a peer Pi's link state has changed
recently (3-Pi Phase 7 remainder: HeartbeatMonitor reports discrete
ONLINE/STALE/LOST transitions but nothing tracks flap RATE as a distinct
signal, so a peer bouncing STALE<->ONLINE repeatedly looks the same as one
that transitioned once and stayed put -- both simply "have transitions").

Pure Python, no rclpy dependency, fed real LinkTransition objects from
HeartbeatMonitor.evaluate() by the node wrapper; tests feed synthetic ones.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .heartbeat_monitor import LinkTransition, PiId


@dataclass(frozen=True)
class FlapConfig:
    window_sec: float = 60.0
    flap_threshold: int = 3  # this many transitions within window_sec counts as flapping

    def __post_init__(self) -> None:
        if self.window_sec <= 0:
            raise ValueError("window_sec must be positive")
        if self.flap_threshold < 2:
            raise ValueError("flap_threshold must be at least 2 (a single transition is never a flap)")


class FlapDetector:
    """Tracks recent link-state-transition timestamps per peer and reports
    whether a peer is currently "flapping" (more transitions than
    `flap_threshold` within the trailing `window_sec`)."""

    def __init__(self, peers: list[PiId], config: FlapConfig | None = None) -> None:
        self._config = config or FlapConfig()
        self._history: dict[PiId, deque[float]] = {p: deque() for p in peers}

    @property
    def window_sec(self) -> float:
        return self._config.window_sec

    def record_transition(self, transition: LinkTransition) -> None:
        if transition.pi not in self._history:
            self._history[transition.pi] = deque()
        self._history[transition.pi].append(transition.at)

    def _prune(self, pi: PiId, now: float) -> None:
        history = self._history.get(pi)
        if history is None:
            return
        cutoff = now - self._config.window_sec
        while history and history[0] < cutoff:
            history.popleft()

    def flap_count(self, pi: PiId, now: float) -> int:
        self._prune(pi, now)
        return len(self._history.get(pi, ()))

    def is_flapping(self, pi: PiId, now: float) -> bool:
        return self.flap_count(pi, now) >= self._config.flap_threshold

    def flapping_peers(self, now: float) -> list[PiId]:
        return [pi for pi in self._history if self.is_flapping(pi, now)]
