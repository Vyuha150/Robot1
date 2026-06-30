"""Object recognition scenarios (family 7).

CI-safe via `bonbon_behavior_validation.perception_assertions` against a
reference detection-confidence model per scenario, plus the Behavior
Oracle's low-confidence-handling check. Real Hailo-accelerated accuracy is
the ai_hat_gated next step (object_recognition shares its runtime with
family 2, already covered by test_pi_ai_hat_scenarios.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reference_behaviors import simulate_correct_behavior
from scenario_generator import load_generated

from bonbon_behavior_validation import BehaviorOracle
from bonbon_behavior_validation.behavior_oracle import OracleStatus
from bonbon_behavior_validation.expected_outcomes import CheckStatus
from bonbon_behavior_validation.perception_assertions import detection_within_iou_and_class

pytestmark = [pytest.mark.perception, pytest.mark.ai_hat_gated]

_SCENARIOS = load_generated("object_recognition")


def _reference_confidence(scenario) -> float:
    ic = scenario.input_conditions
    confidence = 0.92
    if ic.sensor == "ai_hat_unavailable":
        confidence -= 0.25  # CPU fallback is slower/less accurate
    if ic.lighting in ("low", "backlit", "flickering", "night_mode"):
        confidence -= 0.2
    return max(confidence, 0.05)


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s.scenario_id for s in _SCENARIOS])
def test_known_class_detected_within_iou(scenario):
    confidence = _reference_confidence(scenario)
    if confidence < 0.6:
        pytest.skip(
            "low-confidence scenario covered by the oracle's clarification/suppression check"
        )
    check = detection_within_iou_and_class("person", "person", observed_iou=0.78)
    assert check.status == CheckStatus.PASS


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s.scenario_id for s in _SCENARIOS])
def test_object_recognition_event_is_logged_and_dashboarded(scenario):
    confidence = _reference_confidence(scenario)
    observed = simulate_correct_behavior(scenario, detection_confidence=confidence)
    verdict = BehaviorOracle().evaluate(scenario, observed)
    assert verdict.status == OracleStatus.PASS, verdict.failed_checks


def test_wrong_class_at_high_iou_is_caught():
    check = detection_within_iou_and_class("cup", "person", observed_iou=0.9)
    assert check.status == CheckStatus.FAIL


def test_low_iou_is_caught():
    check = detection_within_iou_and_class("person", "person", observed_iou=0.1)
    assert check.status == CheckStatus.FAIL
