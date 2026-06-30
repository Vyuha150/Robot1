"""Gesture understanding scenarios (family 9).

The Behavior Oracle's safety-halt and clarification checks are keyed
directly off `stop_palm` / `conflicting_gestures`, so this family is
exercised almost entirely through the oracle; the two negative tests
prove a missed stop-palm and a guessed (un-clarified) conflicting gesture
are both caught.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reference_behaviors import break_check, simulate_correct_behavior
from scenario_generator import load_generated

from bonbon_behavior_validation import BehaviorOracle
from bonbon_behavior_validation.behavior_oracle import OracleStatus

pytestmark = [pytest.mark.hri, pytest.mark.safety]

_SCENARIOS = load_generated("gesture_understanding")


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s.scenario_id for s in _SCENARIOS])
def test_correct_gesture_response_passes_oracle(scenario):
    observed = simulate_correct_behavior(scenario)
    verdict = BehaviorOracle().evaluate(scenario, observed)
    assert verdict.status == OracleStatus.PASS, verdict.failed_checks


def test_stop_palm_always_present_in_catalog():
    assert any(s.input_conditions.gesture == "stop_palm" for s in _SCENARIOS)


def test_oracle_catches_ignored_stop_palm():
    halting = [s for s in _SCENARIOS if s.input_conditions.gesture == "stop_palm"]
    for scenario in halting:
        observed = break_check(simulate_correct_behavior(scenario), "safety_supervisor_decision")
        verdict = BehaviorOracle().evaluate(scenario, observed)
        assert verdict.status == OracleStatus.FAIL


def test_oracle_catches_unclarified_conflicting_gesture():
    ambiguous = [s for s in _SCENARIOS if s.input_conditions.gesture == "conflicting_gestures"]
    for scenario in ambiguous:
        observed = break_check(simulate_correct_behavior(scenario), "clarification_when_needed")
        verdict = BehaviorOracle().evaluate(scenario, observed)
        assert verdict.status == OracleStatus.FAIL
