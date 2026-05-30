"""SpatialResponsePlanner — maps spatial hints / alerts to safe behaviour responses.

The spatial reasoning node emits two streams the behaviour engine must react to:

* ``SocialNavigationHint`` — graded social guidance ('slow_down', 'stop',
  'maintain_distance', 'retreat', 'approach_from_front', 'announce', …).
* ``RiskEvent`` alerts — discrete events ('restricted_zone_entry',
  'path_blocked', 'collision_risk').

This planner converts either into a structured :class:`SpatialResponse` telling
the node what to do: which gesture to perform, what (if anything) to say,
whether to pause navigation, and whether to escalate to a human operator. It
never issues motion itself — the node dispatches through the normal
safety-gated path.

Pure logic, no ROS2 dependency — fully unit-testable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

_logger = logging.getLogger(__name__)


@dataclass
class SpatialResponse:
    """A planned behavioural response to a spatial signal."""

    pause_navigation: bool          # halt/pause any active navigation intent
    gesture: str                    # actuation gesture name ('' = none)
    gesture_priority: int           # priority for the gesture request
    say: str                        # TTS text ('' = stay silent)
    tts_emotion: str                # TTS emotion style
    escalate_to_operator: bool      # raise an operator alert
    operator_severity: int          # severity if escalating (RiskEvent scale)
    reason: str                     # explanation for logs / decision record


# Hint type → response template.
_HINT_RESPONSES = {
    "stop": SpatialResponse(
        pause_navigation=True, gesture="stop_gesture", gesture_priority=15,
        say="Excuse me, please.", tts_emotion="calm",
        escalate_to_operator=False, operator_severity=0,
        reason="spatial hint: stop",
    ),
    "slow_down": SpatialResponse(
        pause_navigation=False, gesture="", gesture_priority=0,
        say="", tts_emotion="neutral",
        escalate_to_operator=False, operator_severity=0,
        reason="spatial hint: slow_down",
    ),
    "retreat": SpatialResponse(
        pause_navigation=True, gesture="slight_retreat", gesture_priority=12,
        say="Sorry, I'll give you some space.", tts_emotion="calm",
        escalate_to_operator=False, operator_severity=0,
        reason="spatial hint: retreat",
    ),
    "maintain_distance": SpatialResponse(
        pause_navigation=False, gesture="", gesture_priority=0,
        say="", tts_emotion="neutral",
        escalate_to_operator=False, operator_severity=0,
        reason="spatial hint: maintain_distance",
    ),
    "approach_from_front": SpatialResponse(
        pause_navigation=False, gesture="", gesture_priority=0,
        say="", tts_emotion="neutral",
        escalate_to_operator=False, operator_severity=0,
        reason="spatial hint: approach_from_front",
    ),
    "announce": SpatialResponse(
        pause_navigation=False, gesture="", gesture_priority=0,
        say="Coming through, please.", tts_emotion="friendly",
        escalate_to_operator=False, operator_severity=0,
        reason="spatial hint: announce",
    ),
    "wait": SpatialResponse(
        pause_navigation=True, gesture="listening_pose", gesture_priority=8,
        say="", tts_emotion="neutral",
        escalate_to_operator=False, operator_severity=0,
        reason="spatial hint: wait",
    ),
}

# RiskEvent risk_type → response template.
_ALERT_RESPONSES = {
    "restricted_zone_entry": SpatialResponse(
        pause_navigation=False, gesture="", gesture_priority=0,
        say="Please be aware that area is restricted.", tts_emotion="concerned",
        escalate_to_operator=True, operator_severity=3,  # HIGH
        reason="alert: restricted_zone_entry",
    ),
    "path_blocked": SpatialResponse(
        pause_navigation=True, gesture="", gesture_priority=0,
        say="Excuse me, may I pass?", tts_emotion="friendly",
        escalate_to_operator=False, operator_severity=2,
        reason="alert: path_blocked",
    ),
    "collision_risk": SpatialResponse(
        pause_navigation=True, gesture="stop_gesture", gesture_priority=15,
        say="Watch out, please.", tts_emotion="urgent",
        escalate_to_operator=False, operator_severity=2,
        reason="alert: collision_risk",
    ),
}

_NEUTRAL = SpatialResponse(
    pause_navigation=False, gesture="", gesture_priority=0,
    say="", tts_emotion="neutral",
    escalate_to_operator=False, operator_severity=0,
    reason="no spatial response required",
)


class SpatialResponsePlanner:
    """Translate spatial hints / alerts into behavioural responses."""

    def plan_for_hint(self, hint_type: str, urgency: float = 0.0) -> SpatialResponse:
        """Return the response for a :class:`SocialNavigationHint` type."""
        resp = _HINT_RESPONSES.get(hint_type, _NEUTRAL)
        # A high-urgency stop additionally escalates to the operator.
        if hint_type == "stop" and urgency >= 0.9:
            return SpatialResponse(
                **{**resp.__dict__, "escalate_to_operator": True,
                   "operator_severity": 3,
                   "reason": resp.reason + " (high urgency → operator)"}
            )
        return resp

    def plan_for_alert(self, risk_type: str, severity: int = 2) -> SpatialResponse:
        """Return the response for a :class:`RiskEvent` alert.

        A CRITICAL-severity alert always escalates regardless of template.
        """
        resp = _ALERT_RESPONSES.get(risk_type, _NEUTRAL)
        if severity >= 4 and not resp.escalate_to_operator:  # CRITICAL
            return SpatialResponse(
                **{**resp.__dict__, "escalate_to_operator": True,
                   "operator_severity": max(resp.operator_severity, severity),
                   "reason": resp.reason + " (critical → operator)"}
            )
        return resp
