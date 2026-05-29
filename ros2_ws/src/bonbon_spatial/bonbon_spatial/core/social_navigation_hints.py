"""SocialNavigationHints — derives and aggregates social navigation hints.

Consumes :class:`~bonbon_spatial.core.entity_tracker.TrackedEntity` objects
and :class:`~bonbon_spatial.core.personal_space_estimator.PersonalSpaceEstimator`
to produce :class:`HintSummary` objects that the node converts into
``SocialNavigationHint`` ROS2 messages.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from bonbon_spatial.core.entity_tracker import TrackedEntity
from bonbon_spatial.core.personal_space_estimator import PersonalSpaceEstimator, SpaceEstimate

_logger = logging.getLogger(__name__)


@dataclass
class HintSummary:
    """Aggregated navigation hint derived from one entity observation.

    Fields mirror the ``SocialNavigationHint`` ROS2 message.
    """

    hint_type: str              # 'stop', 'slow_down', 'keep_distance', 'approach_allowed'
    urgency: float              # 0.0 = low, 1.0 = critical
    reason: str
    affected_entity_id: str
    suggested_max_vel_mps: float
    suggested_distance_m: float
    requires_navigation_replan: bool = False
    requires_behavior_response: bool = False
    requires_tts_announcement: bool = False
    suggested_tts_text: str = ""


# Speed caps for each hint level (m/s).
_SPEED_CAP: dict = {
    "stop": 0.0,
    "slow_down": 0.2,
    "keep_distance": 0.4,
    "approach_allowed": 0.6,
}

# Urgency scores for each hint level.
_URGENCY: dict = {
    "stop": 1.0,
    "slow_down": 0.7,
    "keep_distance": 0.4,
    "approach_allowed": 0.1,
}


class SocialNavigationHints:
    """Generate social navigation hints from tracked entity observations.

    Usage::

        gen = SocialNavigationHints(estimator)
        hints = gen.evaluate_all(entities)
        critical = gen.most_critical(hints)
    """

    def __init__(self, estimator: Optional[PersonalSpaceEstimator] = None) -> None:
        """Initialise the hint generator.

        Args:
            estimator: Shared :class:`PersonalSpaceEstimator`.  A default
                       instance is created when not provided.
        """
        self._estimator = estimator or PersonalSpaceEstimator()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate_entity(self, entity: TrackedEntity) -> HintSummary:
        """Derive a :class:`HintSummary` from a single :class:`TrackedEntity`.

        Args:
            entity: The entity to evaluate.

        Returns:
            A :class:`HintSummary` encoding the appropriate hint.
        """
        space: SpaceEstimate = self._estimator.estimate(
            entity.distance_to_robot, entity.person_category
        )

        hint_type = space.hint_type
        urgency = _URGENCY.get(hint_type, 0.1)
        speed_cap = _SPEED_CAP.get(hint_type, 0.6)

        reason = self._build_reason(entity, space)

        requires_replan = hint_type in ("stop", "slow_down")
        requires_behavior = hint_type in ("stop", "slow_down")
        requires_tts = hint_type == "stop" and entity.is_approaching_robot
        tts_text = ""
        if requires_tts:
            name_part = f"{entity.person_id}" if entity.person_id else "someone"
            tts_text = f"Please excuse me, {name_part} is very close."

        return HintSummary(
            hint_type=hint_type,
            urgency=urgency,
            reason=reason,
            affected_entity_id=entity.entity_id,
            suggested_max_vel_mps=speed_cap,
            suggested_distance_m=space.recommended_approach_dist_m,
            requires_navigation_replan=requires_replan,
            requires_behavior_response=requires_behavior,
            requires_tts_announcement=requires_tts,
            suggested_tts_text=tts_text,
        )

    def evaluate_all(self, entities: List[TrackedEntity]) -> List[HintSummary]:
        """Evaluate all entities and return a list of :class:`HintSummary` objects.

        Args:
            entities: All currently tracked entities.

        Returns:
            One :class:`HintSummary` per entity, ordered by urgency descending.
        """
        summaries = [self.evaluate_entity(e) for e in entities]
        summaries.sort(key=lambda h: h.urgency, reverse=True)
        return summaries

    def most_critical(self, hints: List[HintSummary]) -> Optional[HintSummary]:
        """Return the highest-urgency hint from a pre-evaluated list.

        Args:
            hints: List of :class:`HintSummary` objects (need not be sorted).

        Returns:
            The most critical hint, or ``None`` when the list is empty.
        """
        if not hints:
            return None
        return max(hints, key=lambda h: h.urgency)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_reason(entity: TrackedEntity, space: SpaceEstimate) -> str:
        """Compose a human-readable reason string for a hint."""
        parts: List[str] = [
            f"Entity {entity.entity_id} is in {space.zone_name} zone "
            f"({space.distance_m:.2f} m)."
        ]
        if entity.is_approaching_robot:
            parts.append(
                f"Approaching at {entity.approach_speed_mps:.2f} m/s."
            )
        if entity.person_category in ("child", "elderly", "wheelchair"):
            parts.append(
                f"Vulnerable category ({entity.person_category}) — increased safety margin."
            )
        if space.is_too_close:
            parts.append("Robot must stop immediately.")
        elif space.should_slow:
            parts.append("Robot should reduce speed.")
        return " ".join(parts)
