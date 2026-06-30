"""Human-state fusion scenarios (family 11).

Confirms the fused state's confidence gates how strongly it's allowed to
drive behavior: a low/conflicting-confidence fusion must never produce a
strong (unsafe-movement-equivalent) behavior change, only damped/no-op
behavior -- exercised via `perception_assertions.low_confidence_handled_correctly`
and the oracle.
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
from bonbon_behavior_validation.expected_outcomes import CheckStatus, derive_expected_outcome
from bonbon_behavior_validation.perception_assertions import low_confidence_handled_correctly

pytestmark = [pytest.mark.hri, pytest.mark.simulation]

_SCENARIOS = load_generated("human_state_fusion")

# Conflicting cues (e.g. calm voice + distressed face) collapse fusion
# confidence; otherwise a single coherent cue is high-confidence.
_CONFLICTING_GESTURES = {"conflicting_gestures"}


def _reference_fusion_confidence(scenario) -> float:
    ic = scenario.input_conditions
    if ic.gesture in _CONFLICTING_GESTURES:
        return 0.3
    return 0.85


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s.scenario_id for s in _SCENARIOS])
def test_low_confidence_fusion_is_damped_not_asserted(scenario):
    confidence = _reference_fusion_confidence(scenario)
    expected = derive_expected_outcome(scenario)
    observed = simulate_correct_behavior(scenario, detection_confidence=confidence)
    check = low_confidence_handled_correctly(expected, observed)
    assert check.status != CheckStatus.FAIL, check.reason


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s.scenario_id for s in _SCENARIOS])
def test_fusion_event_is_logged_and_dashboarded(scenario):
    confidence = _reference_fusion_confidence(scenario)
    observed = simulate_correct_behavior(scenario, detection_confidence=confidence)
    verdict = BehaviorOracle().evaluate(scenario, observed)
    assert verdict.status == OracleStatus.PASS, verdict.failed_checks


def test_oracle_catches_low_confidence_asserted_as_fact():
    conflicting = [s for s in _SCENARIOS if s.input_conditions.gesture == "conflicting_gestures"][0]
    from dataclasses import replace

    observed = replace(
        simulate_correct_behavior(conflicting, detection_confidence=0.3),
        unsafe_movement_executed=True,
        asked_clarification=False,
    )
    verdict = BehaviorOracle().evaluate(conflicting, observed)
    assert verdict.status == OracleStatus.FAIL
