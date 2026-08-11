"""bonbon_behavior_engine.core.behavior_recommendation_bridge -- GAP-E2
fix (docs/SAFETY_SEPARATION_AUDIT.md Finding 2).

`bonbon_behavior_engine`'s node already creates a lifecycle publisher
for `BehaviorProposal` on `/bonbon/behavior/proposal` -- the topic
`bonbon_motion_approval_gateway` subscribes to as its sole navigation
approval input -- but nothing in this repo ever actually called
`.publish()` on it. Meanwhile `bonbon_navigation`'s `navigation_node.py`
subscribed directly to `/perception/behavior` (`BehaviorRecommendation`,
published by both `bonbon_perception_ai` and
`bonbon_llm.llm_orchestrator_node`) and dispatched real Nav2 goals
straight from it, with no approval step at all (this was the concrete
mechanism behind GAP-E1).

This module is the pure, unit-testable conversion logic for the fix:
translate a `BehaviorRecommendation`'s `behavior_class` +
`param_names`/`param_values` parallel arrays into the fields a real
`BehaviorProposal` ROS2 message needs. The thin ROS2 node wrapper
(`behavior_engine_node.py`) copies these fields onto a real message and
publishes it -- this function never touches rclpy so it's directly
testable without a ROS2 environment.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# behavior_class -> BehaviorProposal.proposal_type. Only navigation-
# relevant classes are bridged -- "stop_navigation" is a de-escalation
# (reduces risk) that bonbon_navigation still handles directly, and
# non-navigation classes (idle, wait_for_input, alert_safety, speak_*)
# were never part of this gap (see docs/SAFETY_SEPARATION_AUDIT.md,
# rule 2 only concerns navigation/motor/servo/emergency-override).
_BEHAVIOR_CLASS_TO_PROPOSAL_TYPE = {
    "navigate_to_goal": "navigate",
    "approach_person": "approach",
}


@dataclass
class ProposalFields:
    """Plain-data mirror of the BehaviorProposal fields this bridge
    populates -- the node wrapper copies these onto a real ROS2 message,
    nothing here constructs one."""

    proposal_type: str
    proposal_content: str
    nav_goal_x: float
    nav_goal_y: float
    nav_goal_yaw: float
    nav_goal_label: str
    urgency: float
    safety_check_required: bool = True
    justification: str = ""


def recommendation_to_proposal(
    behavior_class: str,
    param_names: list[str],
    param_values: list[str],
    confidence: float,
    priority: int = 1,
) -> ProposalFields | None:
    """Returns None for any behavior_class this bridge doesn't handle --
    the caller must not publish a proposal in that case, not guess one.
    `priority` mirrors BehaviorRecommendation.PRIORITY_* constants
    (0=LOW..3=URGENT); mapped to urgency 0.0-1.0 for the gateway."""
    proposal_type = _BEHAVIOR_CLASS_TO_PROPOSAL_TYPE.get(behavior_class)
    if proposal_type is None:
        return None

    params = dict(zip(param_names, param_values))
    named_location = params.get("named_location", params.get("destination", ""))
    try:
        goal_x = float(params.get("goal_x", 0.0))
        goal_y = float(params.get("goal_y", 0.0))
        goal_yaw = float(params.get("goal_yaw", 0.0))
    except (TypeError, ValueError):
        # Malformed goal params must never silently become (0, 0, 0) --
        # that's a real location (the origin), not "no goal given".
        return None

    urgency = min(1.0, max(0.0, priority / 3.0))
    return ProposalFields(
        proposal_type=proposal_type,
        proposal_content=named_location or f"({goal_x:.2f}, {goal_y:.2f})",
        nav_goal_x=goal_x,
        nav_goal_y=goal_y,
        nav_goal_yaw=goal_yaw,
        nav_goal_label=named_location,
        urgency=urgency,
        safety_check_required=True,
        justification=f"behavior_class={behavior_class!r} confidence={confidence:.2f}",
    )
