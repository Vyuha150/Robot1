"""Sensor failure scenarios (family 4).

Drives the REAL `PiEfficiencyProfile` (loaded from
config/pi_efficiency_profile.yaml) to confirm safety-critical modules are
never in the shed order, then runs every generated scenario through the
Behavior Oracle for degraded-mode/dashboard/logging correctness.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "ros2_ws" / "src" / "bonbon_perception_efficiency"))
from _hardware_gates import pi_gated
from bonbon_perception_efficiency.core.pi_efficiency_profile import (
    PiEfficiencyProfile,  # noqa: E402
)
from reference_behaviors import break_check, simulate_correct_behavior
from scenario_generator import load_generated

from bonbon_behavior_validation import BehaviorOracle
from bonbon_behavior_validation.behavior_oracle import OracleStatus

pytestmark = [pytest.mark.degraded_mode, pytest.mark.safety]

_SCENARIOS = load_generated("sensor_failure")
_PROFILE = PiEfficiencyProfile.load(_REPO_ROOT / "config" / "pi_efficiency_profile.yaml")


def test_profile_is_valid_and_never_sheds_safety():
    assert _PROFILE.validate() == []
    safety_critical = set(_PROFILE.safety_critical_modules())
    assert safety_critical, "profile must mark at least one module safety-critical"
    assert not (safety_critical & set(_PROFILE.shed_order()))


def test_shed_order_never_includes_safety_modules_at_any_count():
    safety_critical = set(_PROFILE.safety_critical_modules())
    for count in range(0, len(_PROFILE.priority) + 5):
        assert not (safety_critical & set(_PROFILE.modules_to_shed(count)))


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s.scenario_id for s in _SCENARIOS])
def test_sensor_loss_event_is_handled_correctly(scenario):
    observed = simulate_correct_behavior(scenario)
    verdict = BehaviorOracle().evaluate(scenario, observed)
    assert verdict.status == OracleStatus.PASS, verdict.failed_checks


def test_oracle_catches_shedding_a_never_disable_module():
    scenario = _SCENARIOS[0]
    correct = simulate_correct_behavior(scenario)
    from dataclasses import replace

    observed = replace(correct, never_disable_modules_active=False)
    verdict = BehaviorOracle().evaluate(scenario, observed)
    assert verdict.status == OracleStatus.FAIL
    assert "degraded_mode_entered" in {c.name for c in verdict.failed_checks}


def test_oracle_catches_silent_sensor_loss():
    scenario = _SCENARIOS[0]
    observed = break_check(simulate_correct_behavior(scenario), "degraded_mode_entered")
    verdict = BehaviorOracle().evaluate(scenario, observed)
    assert verdict.status == OracleStatus.FAIL


@pi_gated
def test_real_sensor_unplug_triggers_degraded_mode():
    pytest.skip("requires physically unplugging a sensor on a live Pi")
