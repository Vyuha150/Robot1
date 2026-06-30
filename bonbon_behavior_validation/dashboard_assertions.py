"""Dashboard/logging checks: did the event reach the dashboard and the
log. Feeds oracle checks #7 and #8."""

from __future__ import annotations

from bonbon_behavior_validation.expected_outcomes import CheckResult, CheckStatus, ObservedOutcome


def dashboard_was_updated(observed: ObservedOutcome) -> CheckResult:
    ok = observed.dashboard_updated
    return CheckResult(
        "dashboard_updated", CheckStatus.PASS if ok else CheckStatus.FAIL, f"dashboard_updated={ok}"
    )


def event_was_logged(observed: ObservedOutcome) -> CheckResult:
    ok = observed.event_logged
    return CheckResult(
        "event_logged", CheckStatus.PASS if ok else CheckStatus.FAIL, f"event_logged={ok}"
    )


def endpoint_reflects_backend_state(endpoint_value: object, backend_value: object) -> CheckResult:
    ok = endpoint_value == backend_value
    return CheckResult(
        "endpoint_reflects_backend_state",
        CheckStatus.PASS if ok else CheckStatus.FAIL,
        f"endpoint={endpoint_value!r} backend={backend_value!r}",
    )
