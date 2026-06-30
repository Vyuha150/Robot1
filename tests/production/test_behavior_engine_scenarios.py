"""Behavior engine decision scenarios (family 12) -- the LLM-never-acts-
directly guarantee.

Drives the REAL `CommandAuthorizer` (bonbon_llm.safety.authorization) with
an LLM proposing a physical action (`navigate_to`) under every scenario's
derived safety state, confirming the authorizer -- not the LLM -- is what
decides whether anything physical happens.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_LLM_PKG = Path(__file__).resolve().parents[2] / "ros2_ws" / "src" / "bonbon_llm"
sys.path.insert(0, str(_LLM_PKG))
from bonbon_llm.config.llm_config import AuthorizationConfig  # noqa: E402
from bonbon_llm.safety.authorization import (  # noqa: E402
    SAFETY_NORMAL,
    SAFETY_SAFE_STOP,
    CommandAuthorizer,
    SafetySnapshot,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from reference_behaviors import simulate_correct_behavior
from scenario_generator import load_generated

from bonbon_behavior_validation import BehaviorOracle
from bonbon_behavior_validation.behavior_oracle import OracleStatus

pytestmark = [pytest.mark.safety, pytest.mark.hri]

_SCENARIOS = load_generated("behavior_engine_decisions")
_AUTHORIZER = CommandAuthorizer(AuthorizationConfig())


def _safety_state_for(scenario) -> SafetySnapshot:
    if scenario.input_conditions.gesture == "stop_palm":
        return SafetySnapshot(
            state_id=SAFETY_SAFE_STOP, state_name="SAFE_STOP", requires_manual_reset=True
        )
    return SafetySnapshot(state_id=SAFETY_NORMAL, state_name="NORMAL")


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s.scenario_id for s in _SCENARIOS])
def test_llm_proposed_navigation_is_gated_by_real_authorizer(scenario):
    safety = _safety_state_for(scenario)
    result = _AUTHORIZER.authorize("navigate_to", safety)

    if safety.state_id == SAFETY_SAFE_STOP:
        assert result.granted is False
    else:
        assert result.granted is True

    observed = simulate_correct_behavior(
        scenario,
        llm_proposed_direct_action=True,
        llm_action_authorized_through_gate=True,  # the gate decided either way -- never bypassed
    )
    verdict = BehaviorOracle().evaluate(scenario, observed)
    assert verdict.status == OracleStatus.PASS, verdict.failed_checks


def test_authorizer_denies_actuation_during_estop():
    safety = SafetySnapshot(
        state_id=SAFETY_SAFE_STOP, state_name="SAFE_STOP", requires_manual_reset=True
    )
    result = _AUTHORIZER.authorize("serve_item", safety)
    assert result.granted is False


def test_speech_is_always_granted_regardless_of_safety_state():
    safety = SafetySnapshot(
        state_id=SAFETY_SAFE_STOP, state_name="SAFE_STOP", requires_manual_reset=True
    )
    result = _AUTHORIZER.authorize("speak_response", safety)
    assert result.granted is True


def test_oracle_catches_llm_action_that_bypasses_the_gate():
    scenario = _SCENARIOS[0]
    observed = simulate_correct_behavior(
        scenario, llm_proposed_direct_action=True, llm_action_authorized_through_gate=False
    )
    verdict = BehaviorOracle().evaluate(scenario, observed)
    assert verdict.status == OracleStatus.FAIL
    assert "llm_no_direct_action" in {c.name for c in verdict.failed_checks}
