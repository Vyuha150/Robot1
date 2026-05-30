"""BlockageDetector — detects when the robot's forward path is obstructed.

A "blockage" is one or more entities that sit inside a forward corridor in
front of the robot and stay there for a sustained period. This distinguishes a
genuine blockage (a person standing in a doorway) from transient crossings (a
person walking past), which should NOT trigger a reroute.

The detector is stateful: it tracks how long the corridor has been occupied and
only declares a blockage after ``persistence_sec`` of continuous occupancy. It
clears the moment the corridor is free.

No ROS2 dependency — pure geometry + a monotonic clock, fully unit-testable.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Callable, List, Optional, Protocol

_logger = logging.getLogger(__name__)

# Forward corridor geometry (robot faces +x).
DEFAULT_CORRIDOR_HALF_WIDTH_M = 0.5   # ± lateral half-width
DEFAULT_CORRIDOR_LENGTH_M = 2.0       # how far ahead we care about
DEFAULT_PERSISTENCE_SEC = 1.5         # occupancy must persist this long


class _EntityLike(Protocol):
    entity_id: str
    x: float
    y: float


@dataclass
class BlockageState:
    """Result of a blockage evaluation."""

    is_blocked: bool
    blocking_entity_ids: List[str]
    occupied_duration_sec: float
    nearest_blocker_m: float
    reason: str


class BlockageDetector:
    """Detects sustained occupancy of the robot's forward corridor.

    Args:
        corridor_half_width_m: Lateral half-width of the forward corridor.
        corridor_length_m: How far ahead the corridor extends.
        persistence_sec: Required continuous occupancy before declaring blocked.
        clock: Monotonic time source (injectable for tests).
    """

    def __init__(
        self,
        corridor_half_width_m: float = DEFAULT_CORRIDOR_HALF_WIDTH_M,
        corridor_length_m: float = DEFAULT_CORRIDOR_LENGTH_M,
        persistence_sec: float = DEFAULT_PERSISTENCE_SEC,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._half_w = corridor_half_width_m
        self._length = corridor_length_m
        self._persistence = persistence_sec
        import time as _time
        self._clock = clock or _time.monotonic
        self._occupied_since: Optional[float] = None

    def _in_corridor(self, entity: _EntityLike) -> bool:
        """True if the entity is inside the forward corridor (robot faces +x)."""
        return (0.0 < entity.x <= self._length) and (abs(entity.y) <= self._half_w)

    def update(self, entities: List[_EntityLike]) -> BlockageState:
        """Update the detector with the latest entities and return its state."""
        now = self._clock()
        blockers = [e for e in entities if self._in_corridor(e)]

        if not blockers:
            self._occupied_since = None
            return BlockageState(
                is_blocked=False,
                blocking_entity_ids=[],
                occupied_duration_sec=0.0,
                nearest_blocker_m=float("inf"),
                reason="corridor clear",
            )

        if self._occupied_since is None:
            self._occupied_since = now
        occupied_for = now - self._occupied_since
        nearest = min(math.hypot(e.x, e.y) for e in blockers)
        ids = [e.entity_id for e in blockers]

        if occupied_for >= self._persistence:
            return BlockageState(
                is_blocked=True,
                blocking_entity_ids=ids,
                occupied_duration_sec=round(occupied_for, 2),
                nearest_blocker_m=round(nearest, 3),
                reason=(
                    f"{len(ids)} entity(ies) in forward corridor for "
                    f"{occupied_for:.1f}s (nearest {nearest:.2f}m)"
                ),
            )

        return BlockageState(
            is_blocked=False,
            blocking_entity_ids=ids,
            occupied_duration_sec=round(occupied_for, 2),
            nearest_blocker_m=round(nearest, 3),
            reason=f"corridor occupied {occupied_for:.1f}s (< {self._persistence:.1f}s threshold)",
        )

    def reset(self) -> None:
        """Clear occupancy state (e.g. on deactivate)."""
        self._occupied_since = None
