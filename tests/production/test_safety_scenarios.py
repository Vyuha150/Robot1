"""Safety and emergency-stop scenarios (family 3).

Drives the REAL `SafetyPolicy` (loaded from the production
safety_policy.yaml) to confirm SAFE_STOP always prescribes `trigger_estop`
+ `log_incident`, then runs every generated scenario through the Behavior
Oracle for the dashboard/logging/no-unsafe-movement side.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SAFETY_PKG = Path(__file__).resolve().parents[2] / "ros2_ws" / "src" / "bonbon_safety"
sys.path.insert(0, str(_SAFETY_PKG))
from _hardware_gates import pi_gated
from bonbon_safety.core.safety_policy import PolicyAction, SafetyPolicy  # noqa: E402
from reference_behaviors import break_check, simulate_correct_behavior
from scenario_generator import load_generated

from bonbon_behavior_validation import BehaviorOracle
from bonbon_behavior_validation.behavior_oracle import OracleStatus

pytestmark = [pytest.mark.safety]

_SCENARIOS = load_generated("safety_and_emergency_stop")
_POLICY = SafetyPolicy.from_yaml(_SAFETY_PKG / "bonbon_safety" / "config" / "safety_policy.yaml")


def test_safe_stop_policy_always_triggers_estop_and_logs():
    actions = _POLICY.on_enter_actions("SAFE_STOP")
    assert PolicyAction.trigger_estop in actions
    assert PolicyAction.log_incident in actions


def test_danger_policy_zeroes_velocity_and_disables_actuation():
    actions = _POLICY.on_enter_actions("DANGER")
    assert PolicyAction.zero_velocity in actions
    assert PolicyAction.disable_actuation in actions


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s.scenario_id for s in _SCENARIOS])
def test_safety_event_is_handled_correctly(scenario):
    observed = simulate_correct_behavior(scenario)
    verdict = BehaviorOracle().evaluate(scenario, observed)
    assert verdict.status == OracleStatus.PASS, verdict.failed_checks


def test_oracle_catches_unsafe_movement():
    scenario = _SCENARIOS[0]
    observed = break_check(simulate_correct_behavior(scenario), "no_unsafe_movement")
    verdict = BehaviorOracle().evaluate(scenario, observed)
    assert verdict.status == OracleStatus.FAIL
    assert "no_unsafe_movement" in {c.name for c in verdict.failed_checks}


def test_oracle_catches_slow_estop():
    halting = [
        s for s in _SCENARIOS if s.input_conditions.extra["trigger"] == "unsafe_command_proposed"
    ]
    assert halting, "catalog should include at least one unsafe-command-proposed scenario"
    observed = break_check(simulate_correct_behavior(halting[0]), "estop_latency")
    verdict = BehaviorOracle().evaluate(halting[0], observed)
    assert verdict.status == OracleStatus.FAIL
    assert "estop_latency" in {c.name for c in verdict.failed_checks}


@pi_gated
def test_real_estop_latency_under_full_ai_load():
    import os

    log_path = os.environ.get("BONBON_ESTOP_LATENCY_LOG")
    if not log_path or not Path(log_path).exists():
        pytest.skip(
            "set BONBON_ESTOP_LATENCY_LOG to a real GPIO e-stop latency measurement "
            "(ms, one float per line) captured under full AI load on this Pi"
        )
    latencies_ms = [float(x) for x in Path(log_path).read_text().split()]
    assert max(latencies_ms) <= 500.0
