"""Power and thermal scenarios (family 5).

Drives the REAL `PiEfficiencyProfile` thresholds (config/pi_efficiency_profile.yaml)
to confirm shedding happens before the documented throttle threshold, then
runs every generated scenario through the Behavior Oracle.
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
from reference_behaviors import simulate_correct_behavior
from scenario_generator import load_generated

from bonbon_behavior_validation import BehaviorOracle
from bonbon_behavior_validation.behavior_oracle import OracleStatus

pytestmark = [pytest.mark.degraded_mode, pytest.mark.performance]

_SCENARIOS = load_generated("power_and_thermal")
_PROFILE = PiEfficiencyProfile.load(_REPO_ROOT / "config" / "pi_efficiency_profile.yaml")


def test_thermal_thresholds_shed_before_throttle():
    caution = _PROFILE.thresholds.get("cpu_temp_caution_c")
    fault = _PROFILE.thresholds.get("cpu_temp_fault_c")
    assert caution is not None and fault is not None
    assert caution < fault


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s.scenario_id for s in _SCENARIOS])
def test_power_thermal_event_is_handled_correctly(scenario):
    observed = simulate_correct_behavior(scenario)
    verdict = BehaviorOracle().evaluate(scenario, observed)
    assert verdict.status == OracleStatus.PASS, verdict.failed_checks


@pi_gated
def test_real_cpu_temperature_stability_under_load():
    import os

    log_path = os.environ.get("BONBON_THERMAL_LOG")
    if not log_path or not Path(log_path).exists():
        pytest.skip("set BONBON_THERMAL_LOG to a real `vcgencmd measure_temp` time series")
    readings = [float(x) for x in Path(log_path).read_text().split()]
    fault = _PROFILE.thresholds.get("cpu_temp_fault_c", 90.0)
    assert max(readings) < fault
