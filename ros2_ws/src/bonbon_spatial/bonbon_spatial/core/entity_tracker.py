"""EntityTracker — maintains a dict of tracked entities with timeout cleanup.

Entities are keyed by entity_id (e.g. "person_3"). The tracker is designed
to be called from a ROS2 node's subscription callback. All mutation must be
protected by the caller's threading.Lock.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

_logger = logging.getLogger(__name__)

# Default lifetime before a silent entity is evicted.
ENTITY_TIMEOUT_SEC: float = 5.0


@dataclass
class TrackedEntity:
    """Snapshot of a single tracked entity in robot-centric coordinates."""

    entity_id: str
    entity_type: str        # 'person', 'object', 'robot', 'unknown'
    person_id: str
    tracking_id: int
    x: float
    y: float
    z: float
    vx: float = 0.0
    vy: float = 0.0
    zone_id: str = ""
    person_category: str = "unknown"
    is_approaching_robot: bool = False
    is_moving_away: bool = False
    approach_speed_mps: float = 0.0
    confidence: float = 1.0
    last_seen: float = field(default_factory=time.monotonic)

    @property
    def distance_to_robot(self) -> float:
        """Euclidean distance from entity to robot (robot at frame origin)."""
        return math.sqrt(self.x ** 2 + self.y ** 2)


class EntityTracker:
    """Thread-safe registry of spatially-tracked entities.

    Callers are responsible for acquiring their own lock before mutating the
    tracker so that the lock scope can span multi-step operations.
    """

    def __init__(self, timeout_sec: float = ENTITY_TIMEOUT_SEC) -> None:
        """Initialise the tracker.

        Args:
            timeout_sec: Seconds of silence after which an entity is removed.
        """
        self._entities: Dict[str, TrackedEntity] = {}
        self._timeout_sec: float = timeout_sec

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def update_person(self, person_state: object) -> TrackedEntity:
        """Create or update a :class:`TrackedEntity` from a PersonState message.

        PersonState fields used:
            track_id (str), face_id (str), distance_m (float),
            bearing_deg (float), velocity_mps (float), facing_robot (bool),
            age_group (str), position (geometry_msgs/Point).

        We derive the entity_id from ``track_id`` so that the same person
        keeps the same key across updates.

        Args:
            person_state: A ``bonbon_msgs/PersonState`` message (or any object
                with the same attributes — useful in unit tests).

        Returns:
            The newly created or updated :class:`TrackedEntity`.
        """
        track_id: str = getattr(person_state, "track_id", "")
        # Derive a numeric tracking_id by stripping the "person_" prefix if
        # present, so we stay compatible with the numeric tracking_id field on
        # SpatialEntity.
        if track_id.startswith("person_"):
            try:
                numeric_id = int(track_id[len("person_"):])
            except ValueError:
                numeric_id = abs(hash(track_id)) % (2 ** 31)
        else:
            try:
                numeric_id = int(track_id)
            except ValueError:
                numeric_id = abs(hash(track_id)) % (2 ** 31)

        entity_id = f"person_{numeric_id}"

        position = getattr(person_state, "position", None)
        px: float = getattr(position, "x", 0.0) if position is not None else 0.0
        py: float = getattr(position, "y", 0.0) if position is not None else 0.0
        pz: float = getattr(position, "z", 0.0) if position is not None else 0.0

        # PersonState carries a scalar velocity_mps and bearing_deg; decompose
        # into Cartesian components relative to the robot's forward axis (x).
        speed: float = float(getattr(person_state, "velocity_mps", 0.0))
        bearing_rad: float = math.radians(
            float(getattr(person_state, "bearing_deg", 0.0))
        )
        # Velocity components in robot frame (x forward, y left).
        vx: float = speed * math.cos(bearing_rad)
        vy: float = speed * math.sin(bearing_rad)

        # Approach speed: positive when entity moves toward origin (robot).
        dist: float = math.sqrt(px ** 2 + py ** 2) or 1e-6
        approach_speed: float = -(px * vx + py * vy) / dist

        face_id: str = getattr(person_state, "face_id", "")
        age_group: str = getattr(person_state, "age_group", "unknown")

        entity = TrackedEntity(
            entity_id=entity_id,
            entity_type="person",
            person_id=face_id,
            tracking_id=numeric_id,
            x=px,
            y=py,
            z=pz,
            vx=vx,
            vy=vy,
            person_category=age_group,
            is_approaching_robot=approach_speed > 0.1,
            is_moving_away=approach_speed < -0.1,
            approach_speed_mps=approach_speed,
            confidence=1.0,
            last_seen=time.monotonic(),
        )
        self._entities[entity_id] = entity
        _logger.debug("Updated entity %s at (%.2f, %.2f)", entity_id, px, py)
        return entity

    def cleanup_stale(self) -> List[str]:
        """Remove entities that have not been updated within the timeout.

        Returns:
            List of entity_ids that were removed.
        """
        now = time.monotonic()
        stale = [
            eid
            for eid, e in self._entities.items()
            if now - e.last_seen > self._timeout_sec
        ]
        for eid in stale:
            del self._entities[eid]
            _logger.debug("Evicted stale entity %s", eid)
        return stale

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_all(self) -> List[TrackedEntity]:
        """Return a snapshot list of all currently tracked entities."""
        return list(self._entities.values())

    def get_by_id(self, entity_id: str) -> Optional[TrackedEntity]:
        """Look up an entity by its string entity_id."""
        return self._entities.get(entity_id)

    def get_by_tracking_id(self, tracking_id: int) -> Optional[TrackedEntity]:
        """Look up an entity by numeric tracking_id."""
        for e in self._entities.values():
            if e.tracking_id == tracking_id:
                return e
        return None

    def count(self) -> int:
        """Return the number of currently tracked entities."""
        return len(self._entities)
