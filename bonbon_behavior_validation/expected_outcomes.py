"""Shared check-result types plus scenario -> expectation derivation.

`derive_expected_outcome` reads a generated Scenario's `input_conditions`
and decides, structurally, which oracle checks even apply -- e.g. a
gesture of "conflicting_gestures" *requires* a clarification response;
a "stop_palm" gesture *requires* a safety-relevant halt; a `sensor` value
other than "normal" *requires* degraded mode. This keeps the 10 oracle
checks from penalizing a scenario for a behavior it never needed.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "scenarios"))
from scenario_schema import Scenario  # noqa: E402


class CheckStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    reason: str

    @property
    def is_failure(self) -> bool:
        return self.status == CheckStatus.FAIL


# Gestures that must produce an immediate safety-relevant response, never a
# guess and never an ignored input.
_SAFETY_CRITICAL_GESTURES = {"stop_palm"}
_AMBIGUOUS_GESTURES = {"conflicting_gestures"}
_AMBIGUOUS_SPEECH = {"confused_question", "overlapping_speech"}
_EMERGENCY_SPEECH = {"emergency_phrase"}
_DEGRADING_SENSORS = {
    "camera_lost",
    "lidar_lost",
    "mic_lost",
    "imu_drift",
    "ai_hat_unavailable",
    "high_temperature",
    "cpu_overload",
}
_MULTI_PERSON = {"two_people", "five_people", "crowd"}
_IDENTITY_SENSITIVE_PEOPLE = {"unknown_person", "known_person", "off_camera_speaker"}


@dataclass(frozen=True)
class ExpectedOutcome:
    """What this scenario structurally requires, derived from its inputs."""

    requires_safety_halt: bool
    requires_clarification: bool
    requires_degraded_mode: bool
    requires_identity_disambiguation: bool
    is_emergency: bool
    estop_budget_ms: float = 500.0
    confidence_threshold: float = 0.6


def derive_expected_outcome(scenario: Scenario) -> ExpectedOutcome:
    ic = scenario.input_conditions
    unsafe_command_proposed = ic.extra.get("trigger") == "unsafe_command_proposed"
    return ExpectedOutcome(
        requires_safety_halt=ic.gesture in _SAFETY_CRITICAL_GESTURES
        or ic.speech in _EMERGENCY_SPEECH
        or unsafe_command_proposed,
        requires_clarification=ic.gesture in _AMBIGUOUS_GESTURES or ic.speech in _AMBIGUOUS_SPEECH,
        requires_degraded_mode=ic.sensor in _DEGRADING_SENSORS or ic.robot_state == "degraded_mode",
        requires_identity_disambiguation=ic.people in _MULTI_PERSON | _IDENTITY_SENSITIVE_PEOPLE,
        is_emergency=ic.speech in _EMERGENCY_SPEECH
        or ic.gesture in _SAFETY_CRITICAL_GESTURES
        or unsafe_command_proposed,
    )


@dataclass(frozen=True)
class ObservedOutcome:
    """What the robot (or the mock/simulation standing in for it) actually
    did for one scenario run. Test drivers in tests/production/ fill this
    in from the real module's output; the Behavior Oracle never inspects
    module internals directly, only this normalized record."""

    # Safety
    safety_decision: str | None = None  # "approved" | "blocked" | None
    safety_block_reason: str | None = None
    estop_triggered: bool = False
    estop_latency_ms: float | None = None
    unsafe_movement_executed: bool = False

    # Identity / perception
    responded_to_person_id: str | None = None
    expected_person_id: str | None = None
    identity_mixup_detected: bool = False
    detection_confidence: float | None = None

    # Dialogue / clarification
    asked_clarification: bool = False

    # Dashboard / logging
    dashboard_updated: bool = False
    event_logged: bool = False

    # Degraded mode
    degraded_mode_entered: bool = False
    never_disable_modules_active: bool = True

    # LLM / authorization
    llm_proposed_direct_action: bool = False
    llm_action_authorized_through_gate: bool = True

    # Domain-specific payloads (transcript, IoU, path points, etc.)
    extra: dict[str, object] | None = None
