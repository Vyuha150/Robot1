"""Speech and speaker diarization scenarios (family 10).

Exercises `speech_assertions.transcript_matches` (word-error-rate budget)
and `emergency_phrase_escalated` directly, plus the Behavior Oracle for
the dashboard/logging side of every generated scenario.
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
from bonbon_behavior_validation.expected_outcomes import CheckStatus, derive_expected_outcome
from bonbon_behavior_validation.speech_assertions import (
    emergency_phrase_escalated,
    transcript_matches,
)

pytestmark = [pytest.mark.speech, pytest.mark.safety]

_SCENARIOS = load_generated("speech_and_speaker_diarization")


def test_transcript_within_wer_budget_passes():
    check = transcript_matches("please bring me some water", "please bring me some water")
    assert check.status == CheckStatus.PASS


def test_transcript_far_outside_wer_budget_fails():
    check = transcript_matches("completely different sentence here", "please bring me some water")
    assert check.status == CheckStatus.FAIL


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s.scenario_id for s in _SCENARIOS])
def test_speech_event_is_logged_and_dashboarded(scenario):
    observed = simulate_correct_behavior(scenario)
    verdict = BehaviorOracle().evaluate(scenario, observed)
    assert verdict.status == OracleStatus.PASS, verdict.failed_checks


def test_emergency_phrase_is_always_escalated():
    emergency = [s for s in _SCENARIOS if s.input_conditions.speech == "emergency_phrase"]
    assert emergency
    for scenario in emergency:
        expected = derive_expected_outcome(scenario)
        observed = simulate_correct_behavior(scenario)
        check = emergency_phrase_escalated(expected, observed)
        assert check.status == CheckStatus.PASS


def test_oracle_catches_unescalated_emergency_phrase():
    emergency = [s for s in _SCENARIOS if s.input_conditions.speech == "emergency_phrase"][0]
    observed = break_check(simulate_correct_behavior(emergency), "emergency_phrase_escalated")
    verdict = BehaviorOracle().evaluate(emergency, observed)
    assert verdict.status == OracleStatus.FAIL
    assert "emergency_phrase_escalated" in {c.name for c in verdict.failed_checks}
