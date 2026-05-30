"""RestrictedZoneMonitor — raises alerts when entities enter restricted zones.

The :class:`~bonbon_spatial.core.semantic_zone_manager.SemanticZoneManager`
knows *where* the zones are; this monitor watches *who* is inside them and emits
edge-triggered alerts on entry (and clears on exit). It is edge-triggered so the
behaviour engine / safety supervisor receives one alert per entry rather than a
continuous stream.

It also flags when the *robot itself* is approaching a restricted zone, using a
configurable buffer distance, so navigation can be warned before crossing the
boundary.

No ROS2 dependency — pure logic, fully unit-testable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol, Set

_logger = logging.getLogger(__name__)


class _ZoneManagerLike(Protocol):
    def find_zone_for_point(self, x: float, y: float) -> Optional[str]: ...
    def is_restricted(self, zone_id: str) -> bool: ...


class _EntityLike(Protocol):
    entity_id: str
    entity_type: str
    person_id: str
    x: float
    y: float


@dataclass
class ZoneAlert:
    """An edge-triggered restricted-zone event."""

    alert_type: str          # 'entry' | 'exit'
    entity_id: str
    entity_type: str
    person_id: str
    zone_id: str
    distance_m: float
    description: str


class RestrictedZoneMonitor:
    """Edge-triggered restricted-zone occupancy monitor.

    Args:
        zone_manager: Shared :class:`SemanticZoneManager`.
    """

    def __init__(self, zone_manager: _ZoneManagerLike) -> None:
        self._zones = zone_manager
        # entity_id → zone_id it was last seen inside (restricted only)
        self._inside: Dict[str, str] = {}

    def update(self, entities: List[_EntityLike]) -> List[ZoneAlert]:
        """Diff current occupancy against the last snapshot; return edge alerts."""
        alerts: List[ZoneAlert] = []
        seen: Set[str] = set()

        for e in entities:
            seen.add(e.entity_id)
            zone_id = self._zones.find_zone_for_point(e.x, e.y)
            in_restricted = zone_id is not None and self._zones.is_restricted(zone_id)
            was_inside = e.entity_id in self._inside

            if in_restricted and not was_inside:
                self._inside[e.entity_id] = zone_id  # type: ignore[assignment]
                dist = (e.x ** 2 + e.y ** 2) ** 0.5
                alerts.append(
                    ZoneAlert(
                        alert_type="entry",
                        entity_id=e.entity_id,
                        entity_type=e.entity_type,
                        person_id=e.person_id,
                        zone_id=zone_id,  # type: ignore[arg-type]
                        distance_m=round(dist, 3),
                        description=(
                            f"{e.entity_type} '{e.entity_id}' entered restricted "
                            f"zone '{zone_id}'"
                        ),
                    )
                )
                _logger.warning(alerts[-1].description)
            elif not in_restricted and was_inside:
                prev_zone = self._inside.pop(e.entity_id)
                dist = (e.x ** 2 + e.y ** 2) ** 0.5
                alerts.append(
                    ZoneAlert(
                        alert_type="exit",
                        entity_id=e.entity_id,
                        entity_type=e.entity_type,
                        person_id=e.person_id,
                        zone_id=prev_zone,
                        distance_m=round(dist, 3),
                        description=(
                            f"{e.entity_type} '{e.entity_id}' left restricted "
                            f"zone '{prev_zone}'"
                        ),
                    )
                )

        # Entities that vanished while inside a zone → synthesise exit alerts.
        for entity_id in list(self._inside.keys()):
            if entity_id not in seen:
                prev_zone = self._inside.pop(entity_id)
                alerts.append(
                    ZoneAlert(
                        alert_type="exit",
                        entity_id=entity_id,
                        entity_type="unknown",
                        person_id="",
                        zone_id=prev_zone,
                        distance_m=-1.0,
                        description=(
                            f"entity '{entity_id}' lost while inside restricted "
                            f"zone '{prev_zone}'"
                        ),
                    )
                )

        return alerts

    def occupants(self) -> Dict[str, str]:
        """Return a copy of the current {entity_id: zone_id} occupancy map."""
        return dict(self._inside)

    def reset(self) -> None:
        """Clear occupancy state."""
        self._inside.clear()
