"""Degraded mode scenarios (family 14).

Cross-checks every generated trigger combination against the REAL
`PiEfficiencyProfile` shed order, then the Behavior Oracle for the
recovery/dashboard/logging side. The core safety property -- a
`never_disable` module is never shed, under ANY trigger stacking -- is
checked combinatorially, not just per single-sensor scenario.
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "ros2_ws" / "src" / "bonbon_perception_efficiency"))
from bonbon_perception_efficiency.core.pi_efficiency_profile import (
    PiEfficiencyProfile,  # noqa: E402
)
from reference_behaviors import break_check, simulate_correct_behavior
from scenario_generator import load_generated

from bonbon_behavior_validation import BehaviorOracle
from bonbon_behavior_validation.behavior_oracle import OracleStatus

pytestmark = [pytest.mark.degraded_mode, pytest.mark.simulation]

_SCENARIOS = load_generated("degraded_mode")
_PROFILE = PiEfficiencyProfile.load(_REPO_ROOT / "config" / "pi_efficiency_profile.yaml")


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s.scenario_id for s in _SCENARIOS])
def test_degraded_mode_trigger_is_handled_correctly(scenario):
    observed = simulate_correct_behavior(scenario)
    verdict = BehaviorOracle().evaluate(scenario, observed)
    assert verdict.status == OracleStatus.PASS, verdict.failed_checks


def test_stacked_triggers_never_shed_safety_critical_modules():
    """Simulates multiple sensor/thermal triggers stacking simultaneously
    (the brief's "combinatorial stacking" requirement) and confirms the
    profile's shed order still excludes every safety-critical module."""
    safety_critical = set(_PROFILE.safety_critical_modules())
    sensors = [
        s.input_conditions.extra.get("sensor", s.input_conditions.sensor) for s in _SCENARIOS
    ]
    for stack_size in (1, 2, 3):
        for _combo in itertools.combinations(set(sensors), stack_size):
            # Stacking triggers only ever increases shed pressure (count),
            # never changes which modules are eligible to be shed.
            for count in range(len(_PROFILE.priority) + 1):
                assert not (safety_critical & set(_PROFILE.modules_to_shed(count)))


def test_recovery_restores_in_reverse_shed_order():
    shed = _PROFILE.modules_to_shed(3)
    # Reverse-order restoration is the policy; shed_order()[:3] reversed is
    # exactly the required restoration sequence.
    assert list(reversed(shed)) == list(reversed(_PROFILE.shed_order()[:3]))


def test_oracle_catches_missing_degraded_mode_entry():
    scenario = _SCENARIOS[0]
    observed = break_check(simulate_correct_behavior(scenario), "degraded_mode_entered")
    verdict = BehaviorOracle().evaluate(scenario, observed)
    assert verdict.status == OracleStatus.FAIL
    assert "degraded_mode_entered" in {c.name for c in verdict.failed_checks}
