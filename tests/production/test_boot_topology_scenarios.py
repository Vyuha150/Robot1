"""Boot and deployment topology scenarios (family 1).

Drives the REAL `devops/scripts/boot_topology.py` classifier (not a mock)
against every generated boot/topology scenario, then runs the Behavior
Oracle over the logging/dashboard side of the event.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "devops" / "scripts"))
import boot_topology as bt  # noqa: E402
from reference_behaviors import break_check, simulate_correct_behavior
from scenario_generator import load_generated

from bonbon_behavior_validation import BehaviorOracle
from bonbon_behavior_validation.behavior_oracle import OracleStatus

pytestmark = [pytest.mark.integration, pytest.mark.safety]

_SCENARIOS = load_generated("boot_and_deployment_topology")


def _enabled_units_for(topology: str) -> set[str]:
    if topology == "monolithic":
        return {bt.MONOLITHIC_UNIT}
    if topology == "modular_pi":
        return set(bt.MODULAR_SUBSYSTEM_UNITS)
    if topology == "mixed_invalid":
        return {bt.MONOLITHIC_UNIT} | set(bt.MODULAR_SUBSYSTEM_UNITS)
    raise ValueError(topology)


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s.scenario_id for s in _SCENARIOS])
def test_topology_classification_matches_expected(scenario):
    topology = scenario.input_conditions.extra["topology"]
    result = bt.classify_topology(_enabled_units_for(topology))

    if topology == "mixed_invalid":
        assert result.mode == bt.TopologyMode.INVALID
        assert result.valid is False
    else:
        assert result.mode == bt.TopologyMode(topology)
        assert result.valid is True
        assert result.observed_safety_supervisors is None or result.observed_safety_supervisors == 1


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s.scenario_id for s in _SCENARIOS])
def test_topology_event_is_logged_and_dashboarded(scenario):
    observed = simulate_correct_behavior(scenario)
    verdict = BehaviorOracle().evaluate(scenario, observed)
    assert verdict.status == OracleStatus.PASS, verdict.failed_checks


def test_oracle_catches_missing_dashboard_update():
    scenario = _SCENARIOS[0]
    observed = break_check(simulate_correct_behavior(scenario), "dashboard_updated")
    verdict = BehaviorOracle().evaluate(scenario, observed)
    assert verdict.status == OracleStatus.FAIL
    assert "dashboard_updated" in {c.name for c in verdict.failed_checks}


def test_duplicate_safety_supervisor_is_invalid_even_with_observed_count():
    # Mirrors devops/tests/test_boot_topology.py's runtime-override case:
    # two live safety_supervisor_node processes must force INVALID even if
    # the static unit set alone would look fine.
    result = bt.classify_topology({bt.SAFETY_UNIT}, observed_safety_supervisors=2)
    assert result.mode == bt.TopologyMode.INVALID
    assert result.valid is False
