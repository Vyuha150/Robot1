"""Multi-person tracking scenarios (family 8).

Exercises `perception_assertions.no_identity_mixup` directly plus the
Behavior Oracle's identity-disambiguation check, which is keyed off
exactly the same multi-person/identity-sensitive `people` values this
family varies (see bonbon_behavior_validation.expected_outcomes).
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
from bonbon_behavior_validation.expected_outcomes import derive_expected_outcome
from bonbon_behavior_validation.perception_assertions import no_identity_mixup

pytestmark = [pytest.mark.perception, pytest.mark.hri]

_SCENARIOS = load_generated("multi_person_tracking")


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s.scenario_id for s in _SCENARIOS])
def test_no_identity_mixup_for_correct_tracking(scenario):
    observed = simulate_correct_behavior(scenario)
    expected = derive_expected_outcome(scenario)
    check = no_identity_mixup(expected, observed)
    assert check.status.value != "fail", check.reason


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s.scenario_id for s in _SCENARIOS])
def test_tracking_event_is_logged_and_dashboarded(scenario):
    observed = simulate_correct_behavior(scenario)
    verdict = BehaviorOracle().evaluate(scenario, observed)
    assert verdict.status == OracleStatus.PASS, verdict.failed_checks


def test_every_multi_person_scenario_requires_disambiguation():
    multi_person_people = {
        "two_people",
        "five_people",
        "crowd",
        "unknown_person",
        "known_person",
        "off_camera_speaker",
    }
    flagged = [s for s in _SCENARIOS if s.input_conditions.people in multi_person_people]
    assert len(flagged) == len(
        _SCENARIOS
    ), "this family should only generate multi-person/identity scenarios"
    for s in flagged:
        assert derive_expected_outcome(s).requires_identity_disambiguation is True


def test_oracle_catches_identity_mixup():
    scenario = _SCENARIOS[0]
    from dataclasses import replace

    observed = replace(simulate_correct_behavior(scenario), identity_mixup_detected=True)
    verdict = BehaviorOracle().evaluate(scenario, observed)
    assert verdict.status == OracleStatus.FAIL
    assert "no_identity_mixup" in {c.name for c in verdict.failed_checks}
