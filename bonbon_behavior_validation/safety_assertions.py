"""Safety-path checks: did the Safety Supervisor decide correctly, and was
any required halt fast enough. Feeds oracle checks #1 (supervisor decision)
and #4 (unsafe movement)."""

from __future__ import annotations

from bonbon_behavior_validation.expected_outcomes import (
    CheckResult,
    CheckStatus,
    ExpectedOutcome,
    ObservedOutcome,
)


def supervisor_decision_correct(
    expected: ExpectedOutcome, observed: ObservedOutcome
) -> CheckResult:
    if expected.requires_safety_halt:
        ok = observed.safety_decision == "blocked" or observed.estop_triggered
        return CheckResult(
            name="safety_supervisor_decision",
            status=CheckStatus.PASS if ok else CheckStatus.FAIL,
            reason=(
                "halt/blocked as required"
                if ok
                else "scenario required a safety halt but none was observed"
            ),
        )
    if observed.safety_decision is None:
        return CheckResult(
            "safety_supervisor_decision", CheckStatus.NOT_APPLICABLE, "no safety decision required"
        )
    ok = observed.safety_decision in ("approved", "blocked")
    return CheckResult(
        "safety_supervisor_decision",
        CheckStatus.PASS if ok else CheckStatus.FAIL,
        f"decision={observed.safety_decision}",
    )


def estop_within_budget(expected: ExpectedOutcome, observed: ObservedOutcome) -> CheckResult:
    if not expected.requires_safety_halt:
        return CheckResult(
            "estop_latency", CheckStatus.NOT_APPLICABLE, "no e-stop required by this scenario"
        )
    if observed.estop_latency_ms is None:
        return CheckResult(
            "estop_latency", CheckStatus.FAIL, "e-stop required but no latency was observed"
        )
    ok = observed.estop_latency_ms <= expected.estop_budget_ms
    return CheckResult(
        "estop_latency",
        CheckStatus.PASS if ok else CheckStatus.FAIL,
        f"{observed.estop_latency_ms}ms vs budget {expected.estop_budget_ms}ms",
    )


def no_unsafe_movement(observed: ObservedOutcome) -> CheckResult:
    ok = not observed.unsafe_movement_executed
    return CheckResult(
        "no_unsafe_movement",
        CheckStatus.PASS if ok else CheckStatus.FAIL,
        "no unsafe movement executed" if ok else "unsafe movement was executed",
    )


def command_was_blocked(observed: ObservedOutcome) -> bool:
    return observed.safety_decision == "blocked"
