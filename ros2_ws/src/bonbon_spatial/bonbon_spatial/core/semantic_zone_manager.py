"""SemanticZoneManager — named semantic zones with polygon-in-zone lookup.

Zones can be pre-loaded from a YAML configuration list or added / removed at
runtime via ROS2 service calls.  Point-in-polygon queries use the standard
ray-casting algorithm.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_logger = logging.getLogger(__name__)


@dataclass
class SemanticZone:
    """A named, polygonal semantic zone in the world frame.

    Attributes:
        zone_id: Unique identifier for this zone (e.g. "kitchen", "lobby").
        zone_type: One of 'restricted', 'interaction', 'docking', 'waiting',
                   'public', 'staff_only'.
        polygon: Ordered list of ``(x, y)`` vertices (world frame, metres).
        min_clearance_m: Minimum clearance the robot should maintain from the
                         zone boundary (used by navigation planner).
        reason: Human-readable note on why this zone exists.
        is_dynamic: ``True`` when the zone was added via service at runtime
                    (as opposed to loaded from static YAML config).
    """

    zone_id: str
    zone_type: str
    polygon: List[Tuple[float, float]]
    min_clearance_m: float = 0.5
    reason: str = ""
    is_dynamic: bool = False


class SemanticZoneManager:
    """Registry of semantic zones supporting point-in-polygon queries.

    Thread safety: callers must hold an external lock when multiple threads
    share the same instance.
    """

    def __init__(self) -> None:
        """Initialise an empty zone registry."""
        self._zones: Dict[str, SemanticZone] = {}

    # ------------------------------------------------------------------
    # Loading / mutation
    # ------------------------------------------------------------------

    def load_from_config(self, zones_config: List[dict]) -> None:
        """Bulk-load zones from a YAML-derived list of dicts.

        Each dict must have ``zone_id`` and may have ``zone_type``,
        ``polygon`` (list of ``{x: float, y: float}`` dicts),
        ``min_clearance_m``, and ``reason``.

        Args:
            zones_config: List of zone configuration dicts from YAML.
        """
        for zc in zones_config:
            try:
                polygon: List[Tuple[float, float]] = [
                    (float(p["x"]), float(p["y"]))
                    for p in zc.get("polygon", [])
                ]
                zone = SemanticZone(
                    zone_id=zc["zone_id"],
                    zone_type=zc.get("zone_type", "public"),
                    polygon=polygon,
                    min_clearance_m=float(zc.get("min_clearance_m", 0.5)),
                    reason=zc.get("reason", ""),
                    is_dynamic=False,
                )
                self._zones[zone.zone_id] = zone
                _logger.info("Loaded zone '%s' (%s)", zone.zone_id, zone.zone_type)
            except (KeyError, TypeError, ValueError) as exc:
                _logger.error("Failed to load zone config entry: %s — %s", zc, exc)

    def add_zone(self, zone: SemanticZone) -> None:
        """Add or replace a zone.

        Args:
            zone: The :class:`SemanticZone` to register.
        """
        self._zones[zone.zone_id] = zone
        _logger.info(
            "Zone '%s' (%s) %s",
            zone.zone_id,
            zone.zone_type,
            "updated" if zone.zone_id in self._zones else "added",
        )

    def remove_zone(self, zone_id: str) -> bool:
        """Remove a zone by ID.

        Args:
            zone_id: The ID of the zone to remove.

        Returns:
            ``True`` if the zone existed and was removed, ``False`` otherwise.
        """
        if zone_id in self._zones:
            del self._zones[zone_id]
            _logger.info("Removed zone '%s'", zone_id)
            return True
        _logger.warning("remove_zone: zone '%s' not found", zone_id)
        return False

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_zone(self, zone_id: str) -> Optional[SemanticZone]:
        """Return the :class:`SemanticZone` for a given ID, or ``None``."""
        return self._zones.get(zone_id)

    def get_all_zone_ids(self) -> List[str]:
        """Return a list of all registered zone IDs."""
        return list(self._zones.keys())

    def get_all_zones(self) -> List[SemanticZone]:
        """Return a snapshot list of all registered zones."""
        return list(self._zones.values())

    def find_zone_for_point(self, x: float, y: float) -> Optional[str]:
        """Return the ``zone_id`` of the first zone that contains ``(x, y)``.

        Zones are tested in insertion order.  Returns ``None`` when no zone
        contains the point.

        Args:
            x: World-frame x coordinate (metres).
            y: World-frame y coordinate (metres).

        Returns:
            The matching ``zone_id`` string, or ``None``.
        """
        for zone_id, zone in self._zones.items():
            if self._point_in_polygon(x, y, zone.polygon):
                return zone_id
        return None

    def is_restricted(self, zone_id: str) -> bool:
        """Return ``True`` if the named zone has type ``'restricted'``."""
        z = self._zones.get(zone_id)
        return z is not None and z.zone_type == "restricted"

    # ------------------------------------------------------------------
    # Geometry utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _point_in_polygon(
        x: float, y: float, polygon: List[Tuple[float, float]]
    ) -> bool:
        """Ray-casting point-in-polygon test.

        Handles degenerate cases gracefully: returns ``False`` for polygons
        with fewer than three vertices.

        Args:
            x: Query point x.
            y: Query point y.
            polygon: Ordered list of ``(px, py)`` vertices.

        Returns:
            ``True`` if ``(x, y)`` is inside (or on the boundary of)
            the polygon.
        """
        n = len(polygon)
        if n < 3:
            return False

        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = polygon[i]
            xj, yj = polygon[j]
            # Guard against zero-length edges.
            dy = yj - yi
            if (yi > y) != (yj > y) and dy != 0.0:
                intersect_x = (xj - xi) * (y - yi) / (dy + 1e-10) + xi
                if x < intersect_x:
                    inside = not inside
            j = i
        return inside
