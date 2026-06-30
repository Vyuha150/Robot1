"""Navigation checks: goal reached without collision, safety margin held.
Used by the navigation/obstacle-avoidance family; folds into oracle check
#4 (no unsafe movement) for that family's scenarios."""

from __future__ import annotations

from bonbon_behavior_validation.expected_outcomes import CheckResult, CheckStatus


def reached_goal_without_collision(goal_reached: bool, collision_occurred: bool) -> CheckResult:
    ok = goal_reached and not collision_occurred
    reason = (
        "goal reached, no collision"
        if ok
        else f"goal_reached={goal_reached} collision={collision_occurred}"
    )
    return CheckResult(
        "reached_goal_without_collision", CheckStatus.PASS if ok else CheckStatus.FAIL, reason
    )


def margin_maintained(
    min_observed_clearance_m: float, required_margin_m: float = 0.3
) -> CheckResult:
    ok = min_observed_clearance_m >= required_margin_m
    return CheckResult(
        "margin_maintained",
        CheckStatus.PASS if ok else CheckStatus.FAIL,
        f"clearance={min_observed_clearance_m}m required={required_margin_m}m",
    )
