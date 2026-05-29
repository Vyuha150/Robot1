"""ApproachPosePlanner — selects the best approach pose for a tracked entity.

Wraps :class:`~bonbon_spatial.core.personal_space_estimator.PersonalSpaceEstimator`
with awareness of semantic zones and a configurable approach style
(``'front'``, ``'side'``, ``'any'``).
"""

from __future__ import annotations

import logging
import math
from typing import Optional, Tuple

from bonbon_spatial.core.personal_space_estimator import PersonalSpaceEstimator, ProxemicZones
from bonbon_spatial.core.semantic_zone_manager import SemanticZoneManager
from bonbon_spatial.core.entity_tracker import TrackedEntity

_logger = logging.getLogger(__name__)

# Offset angle (radians) used for 'side' approach relative to person heading.
_SIDE_APPROACH_OFFSET_RAD: float = math.pi / 3.0  # 60°


class ApproachPosePlanner:
    """High-level approach-pose selection integrating proxemics and zones.

    The planner first checks that the desired approach position is not inside
    a restricted semantic zone.  If the first candidate is blocked it tries
    the mirrored side-approach.  If both candidates are blocked it falls back
    to the closest non-restricted candidate.
    """

    def __init__(
        self,
        zone_manager: SemanticZoneManager,
        estimator: Optional[PersonalSpaceEstimator] = None,
    ) -> None:
        """Initialise the planner.

        Args:
            zone_manager: Shared :class:`SemanticZoneManager` instance.
            estimator: Optional custom :class:`PersonalSpaceEstimator`.
                       Defaults to standard proxemic zones.
        """
        self._zones = zone_manager
        self._estimator = estimator or PersonalSpaceEstimator()

    def plan(
        self,
        entity: TrackedEntity,
        desired_distance_m: float = 0.0,
        approach_style: str = "front",
    ) -> Tuple[bool, float, float, float, str]:
        """Compute an approach pose for *entity*.

        Args:
            entity: The target :class:`TrackedEntity`.
            desired_distance_m: Desired robot–person distance.  When ≤ 0 the
                                 estimator's recommended approach distance is
                                 used (adjusted for person category).
            approach_style: One of ``'front'``, ``'side'``, ``'any'``.

        Returns:
            A 5-tuple ``(success, x, y, yaw, message)`` where:
            - ``success``: ``True`` if a valid pose was found.
            - ``x``, ``y``, ``yaw``: Target pose.
            - ``message``: Diagnostic or error string.
        """
        # Determine effective approach distance.
        if desired_distance_m <= 0.0:
            space_est = self._estimator.estimate(
                entity.distance_to_robot, entity.person_category
            )
            effective_dist = space_est.recommended_approach_dist_m
        else:
            effective_dist = desired_distance_m

        px, py = entity.x, entity.y

        if approach_style == "front":
            candidates = [self._front_pose(px, py, effective_dist)]
        elif approach_style == "side":
            candidates = [
                self._side_pose(px, py, effective_dist, _SIDE_APPROACH_OFFSET_RAD),
                self._side_pose(px, py, effective_dist, -_SIDE_APPROACH_OFFSET_RAD),
            ]
        else:  # 'any' — try front first, then both sides
            candidates = [
                self._front_pose(px, py, effective_dist),
                self._side_pose(px, py, effective_dist, _SIDE_APPROACH_OFFSET_RAD),
                self._side_pose(px, py, effective_dist, -_SIDE_APPROACH_OFFSET_RAD),
            ]

        for cx, cy, cyaw in candidates:
            zone_id = self._zones.find_zone_for_point(cx, cy)
            if zone_id is None or not self._zones.is_restricted(zone_id):
                _logger.debug(
                    "Approach pose for entity %s: (%.2f, %.2f, %.3f rad)",
                    entity.entity_id, cx, cy, cyaw,
                )
                return (True, cx, cy, cyaw, "Approach pose computed successfully.")

        # All candidates fell inside restricted zones — return the first anyway
        # with a warning.
        cx, cy, cyaw = candidates[0]
        msg = (
            f"All approach candidates for entity {entity.entity_id} are inside "
            "restricted zones; returning first candidate with warning."
        )
        _logger.warning(msg)
        return (False, cx, cy, cyaw, msg)

    # ------------------------------------------------------------------
    # Internal pose generators
    # ------------------------------------------------------------------

    def _front_pose(
        self, person_x: float, person_y: float, dist_m: float
    ) -> Tuple[float, float, float]:
        """Return a pose directly in front of the person (robot-frame origin)."""
        return self._estimator.compute_approach_pose(person_x, person_y, dist_m)

    def _side_pose(
        self,
        person_x: float,
        person_y: float,
        dist_m: float,
        angle_offset_rad: float,
    ) -> Tuple[float, float, float]:
        """Return an approach pose offset by *angle_offset_rad* from the direct line."""
        base_angle = math.atan2(person_y, person_x)
        approach_angle = base_angle + math.pi + angle_offset_rad
        tx = person_x + dist_m * math.cos(approach_angle)
        ty = person_y + dist_m * math.sin(approach_angle)
        # Yaw: face the person from the side position.
        yaw = math.atan2(person_y - ty, person_x - tx)
        return (tx, ty, yaw)
