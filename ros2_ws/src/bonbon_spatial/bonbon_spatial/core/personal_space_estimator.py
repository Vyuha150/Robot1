"""PersonalSpaceEstimator — Hall's proxemic zones for social robot navigation.

Implements Edward Hall's four-zone model of personal space and maps it to
robot navigation hints (stop, slow_down, keep_distance, approach_allowed).
Vulnerable categories (children, elderly, wheelchair users) receive a 1.3×
safety margin on all distances.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Tuple

_logger = logging.getLogger(__name__)


@dataclass
class ProxemicZones:
    """Distance thresholds (metres) defining Hall's proxemic zones.

    All distances are the *outer* boundary of the named zone (i.e. the zone
    extends from the previous threshold up to this value).
    """

    intimate_m: float = 0.45       # 0 – 0.45 m  : intimate zone
    personal_m: float = 1.2        # 0.45 – 1.2 m: personal zone
    social_m: float = 3.6          # 1.2 – 3.6 m : social zone
    public_m: float = 7.6          # 3.6 – 7.6 m : public zone
    # Robot-specific operational distances
    stop_distance_m: float = 0.6   # must stop when closer than this
    slow_distance_m: float = 1.5   # reduce speed when closer than this
    approach_target_m: float = 1.0  # ideal robot–person interaction distance


@dataclass
class SpaceEstimate:
    """Result of a personal-space estimation for a single observed distance."""

    distance_m: float
    zone_name: str            # 'intimate', 'personal', 'social', 'public', 'distant'
    is_too_close: bool
    should_slow: bool
    recommended_approach_dist_m: float
    hint_type: str            # 'stop', 'slow_down', 'keep_distance', 'approach_allowed'


# Multiplier applied to all thresholds for vulnerable person categories.
_VULNERABLE_MULTIPLIER: float = 1.3
_VULNERABLE_CATEGORIES = frozenset({"child", "elderly", "wheelchair"})


class PersonalSpaceEstimator:
    """Evaluate social distance and emit navigation hints based on proxemics.

    Usage::

        estimator = PersonalSpaceEstimator()
        result = estimator.estimate(distance_m=1.8, person_category="adult")
        # result.hint_type → 'keep_distance'
    """

    def __init__(self, zones: ProxemicZones | None = None) -> None:
        """Initialise with optional custom zone thresholds.

        Args:
            zones: A :class:`ProxemicZones` instance.  Defaults to Hall's
                   standard values with BonBon safety additions.
        """
        self._zones: ProxemicZones = zones or ProxemicZones()

    def estimate(
        self, distance_m: float, person_category: str = "adult"
    ) -> SpaceEstimate:
        """Classify a robot–person distance and produce a navigation hint.

        Args:
            distance_m: Euclidean distance between robot and person (metres).
            person_category: One of 'adult', 'child', 'elderly', 'wheelchair',
                             'staff', or 'unknown'.

        Returns:
            A :class:`SpaceEstimate` describing the zone, flags and hint.
        """
        multiplier = (
            _VULNERABLE_MULTIPLIER
            if person_category in _VULNERABLE_CATEGORIES
            else 1.0
        )
        stop_d = self._zones.stop_distance_m * multiplier
        slow_d = self._zones.slow_distance_m * multiplier
        approach_d = self._zones.approach_target_m * multiplier

        # Classify zone using scaled intimate/personal boundaries; social and
        # public thresholds are not scaled because they represent ambient space
        # rather than personal proximity.
        if distance_m < self._zones.intimate_m * multiplier:
            zone = "intimate"
        elif distance_m < self._zones.personal_m * multiplier:
            zone = "personal"
        elif distance_m < self._zones.social_m:
            zone = "social"
        elif distance_m < self._zones.public_m:
            zone = "public"
        else:
            zone = "distant"

        is_too_close = distance_m < stop_d
        should_slow = distance_m < slow_d

        if is_too_close:
            hint = "stop"
        elif should_slow:
            hint = "slow_down"
        elif zone == "social":
            hint = "keep_distance"
        else:
            hint = "approach_allowed"

        _logger.debug(
            "Proxemics: dist=%.2f zone=%s hint=%s (category=%s)",
            distance_m, zone, hint, person_category,
        )
        return SpaceEstimate(
            distance_m=distance_m,
            zone_name=zone,
            is_too_close=is_too_close,
            should_slow=should_slow,
            recommended_approach_dist_m=approach_d,
            hint_type=hint,
        )

    def compute_approach_pose(
        self,
        person_x: float,
        person_y: float,
        target_dist_m: float,
    ) -> Tuple[float, float, float]:
        """Compute a robot pose to approach a person at the specified distance.

        The returned pose is placed on the straight line between the robot
        (assumed at the frame origin) and the person, ``target_dist_m``
        metres short of the person's position.  The yaw faces the person.

        Args:
            person_x: Person's x position in the robot's reference frame.
            person_y: Person's y position in the robot's reference frame.
            target_dist_m: Desired approach distance from the person (metres).

        Returns:
            A tuple ``(x, y, yaw)`` for the approach pose.  Returns
            ``(0.0, 0.0, 0.0)`` when the person is at the origin.
        """
        dist = math.sqrt(person_x ** 2 + person_y ** 2)
        if dist < 1e-6:
            _logger.debug("compute_approach_pose: person at origin, returning fallback")
            return (0.0, 0.0, 0.0)

        # Unit vector from robot toward person.
        ux = person_x / dist
        uy = person_y / dist

        # Step back from person by target_dist_m along that direction.
        target_x = person_x - ux * target_dist_m
        target_y = person_y - uy * target_dist_m

        # Yaw such that the robot faces the person from target_x, target_y.
        yaw = math.atan2(person_y - target_y, person_x - target_x)

        _logger.debug(
            "Approach pose: person=(%.2f,%.2f) target_dist=%.2f -> pose=(%.2f,%.2f,%.3f rad)",
            person_x, person_y, target_dist_m, target_x, target_y, yaw,
        )
        return (target_x, target_y, yaw)
