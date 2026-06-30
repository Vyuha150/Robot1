"""Reference ("correct robot") behavior model used by tests/production/.

`simulate_correct_behavior` is a deterministic, pure-Python stand-in for
"what a correctly-behaving BonBon would have done" for a given scenario,
derived from the same `derive_expected_outcome` the Behavior Oracle itself
uses. It is not a mock of a single module -- it is the specification the
Behavior Oracle checks against, made executable, so the production suite
can run fully CI-safe today.

Honest scope: wiring these reference outcomes to the real ROS2 nodes
(behavior_engine, safety, perception, etc.) end-to-end is the documented
next integration step, same as bonbon_vision's `_build_detector()` adapter
in HAILO_RUNTIME_INTEGRATION_REPORT.md. Until then, this module is what
keeps the 459 generated scenarios CI-safe and meaningfully assert-able: it
encodes the *rule*, and the oracle is what would catch a real module
violating it once the wiring lands.

`break_check` mutates a correct ObservedOutcome to deliberately violate one
oracle check, for the negative-path "the oracle actually catches this"
tests every production file carries.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scenarios"))
from scenario_schema import Scenario  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bonbon_behavior_validation.expected_outcomes import (  # noqa: E402
    ObservedOutcome,
    derive_expected_outcome,
)


def simulate_correct_behavior(scenario: Scenario, **overrides: object) -> ObservedOutcome:
    expected = derive_expected_outcome(scenario)

    base = ObservedOutcome(
        safety_decision=("blocked" if expected.requires_safety_halt else "approved"),
        estop_triggered=expected.requires_safety_halt,
        estop_latency_ms=(120.0 if expected.requires_safety_halt else None),
        unsafe_movement_executed=False,
        identity_mixup_detected=False,
        asked_clarification=expected.requires_clarification,
        dashboard_updated=True,
        event_logged=True,
        degraded_mode_entered=expected.requires_degraded_mode,
        never_disable_modules_active=True,
        llm_proposed_direct_action=False,
        llm_action_authorized_through_gate=True,
    )
    if overrides:
        from dataclasses import replace

        base = replace(base, **overrides)
    return base


def break_check(observed: ObservedOutcome, check_name: str) -> ObservedOutcome:
    """Flip exactly the field(s) needed to make oracle check `check_name`
    fail, leaving everything else correct -- isolates the negative-path
    assertion to the one behavior under test."""
    from dataclasses import replace

    mutations: dict[str, dict[str, object]] = {
        "safety_supervisor_decision": {"safety_decision": "approved", "estop_triggered": False},
        "estop_latency": {"estop_latency_ms": 900.0},
        "no_unsafe_movement": {"unsafe_movement_executed": True},
        "no_identity_mixup": {"identity_mixup_detected": True},
        "clarification_when_needed": {"asked_clarification": False},
        "dashboard_updated": {"dashboard_updated": False},
        "event_logged": {"event_logged": False},
        "degraded_mode_entered": {"degraded_mode_entered": False},
        "llm_no_direct_action": {
            "llm_proposed_direct_action": True,
            "llm_action_authorized_through_gate": False,
        },
        "emergency_phrase_escalated": {
            "safety_decision": "approved",
            "estop_triggered": False,
            "event_logged": False,
        },
    }
    if check_name not in mutations:
        raise ValueError(f"no known mutation for check {check_name!r}")
    return replace(observed, **mutations[check_name])
