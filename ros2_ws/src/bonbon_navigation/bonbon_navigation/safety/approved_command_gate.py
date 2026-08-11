"""Pure decision logic for whether an approved BehaviorDecision should
result in a Nav2 goal dispatch -- GAP-E2 fix
(docs/SAFETY_SEPARATION_AUDIT.md Finding 2). Extracted out of
navigation_node.py's _on_approved_command so it's unit-testable without
rclpy (navigation_node.py imports rclpy at module level, so nothing
inside it can be imported in this dev sandbox -- see every other
pure-core/rclpy-node split already established in this package,
e.g. safety_stop_bridge.py vs navigation_node.py)."""

from __future__ import annotations

_DISPATCHABLE_APPROVED_ACTIONS = frozenset({"navigate", "approach"})


def should_dispatch_navigation(decision: str, approved_action: str) -> bool:
    """True only for a genuinely approved navigation/approach decision.
    Rejected, escalated, deferred, or non-navigation-type approvals
    (e.g. "speak", "gesture") must never reach goal dispatch."""
    return decision == "approved" and approved_action in _DISPATCHABLE_APPROVED_ACTIONS
