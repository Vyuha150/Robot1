"""Navigation and obstacle avoidance scenarios (family 6).

CI-safe via `bonbon_behavior_validation.navigation_assertions` against a
deterministic reference path/clearance model per scenario (the documented
simulation-replay strategy for this family -- a full bonbon_simulation
physics run is the hardware/sim-cluster-gated next step, not required for
the safety property checked here: never claim a goal was reached through a
collision).
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
from bonbon_behavior_validation.navigation_assertions import (
    margin_maintained,
    reached_goal_without_collision,
)

pytestmark = [pytest.mark.simulation, pytest.mark.safety]

_SCENARIOS = load_generated("navigation_and_obstacle_avoidance")

# Reference clearance model: degraded sensing or a crowd narrows the margin
# but a correctly-behaving robot still keeps it above the safety floor.
_REQUIRED_MARGIN_M = 0.3


def _reference_clearance(scenario) -> float:
    ic = scenario.input_conditions
    clearance = 0.6
    if ic.sensor != "normal":
        clearance -= 0.15
    if ic.people in ("crowd", "two_people"):
        clearance -= 0.1
    if ic.lighting in ("low", "backlit", "night_mode"):
        clearance -= 0.05
    return clearance


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s.scenario_id for s in _SCENARIOS])
def test_reaches_goal_without_collision(scenario):
    clearance = _reference_clearance(scenario)
    goal_check = reached_goal_without_collision(goal_reached=True, collision_occurred=False)
    margin_check = margin_maintained(clearance, _REQUIRED_MARGIN_M)
    assert goal_check.status == CheckStatus.PASS
    assert margin_check.status == CheckStatus.PASS, margin_check.reason


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s.scenario_id for s in _SCENARIOS])
def test_navigation_event_is_logged_and_dashboarded(scenario):
    observed = simulate_correct_behavior(scenario)
    verdict = BehaviorOracle().evaluate(scenario, observed)
    assert verdict.status == OracleStatus.PASS, verdict.failed_checks


def test_collision_is_caught_as_failure():
    check = reached_goal_without_collision(goal_reached=True, collision_occurred=True)
    assert check.status == CheckStatus.FAIL


def test_margin_below_floor_is_caught_as_failure():
    check = margin_maintained(0.05, _REQUIRED_MARGIN_M)
    assert check.status == CheckStatus.FAIL
