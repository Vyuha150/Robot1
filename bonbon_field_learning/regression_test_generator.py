"""Turns an approved, human-labeled failure case into a new generated
Scenario, appended to tests/scenarios/generated_scenarios/regression_scenarios.yaml
-- so it is asserted on every future `pytest tests/production` run via
test_field_pilot_learning_scenarios.py, not just remembered in a ticket.

This is the literal "every failure must become a regression test" rule
made executable: a reviewed case that doesn't produce a new scenario here
is the bug `test_field_pilot_learning_scenarios.py` is written to catch.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

_SCENARIOS_DIR = Path(__file__).resolve().parents[1] / "tests" / "scenarios"
sys.path.insert(0, str(_SCENARIOS_DIR))
from scenario_schema import (  # noqa: E402
    HardwareRequirement,
    InputConditions,
    MockStrategy,
    RiskLevel,
    Scenario,
)

from bonbon_field_learning.annotation_exporter import LabeledExample

_REGRESSION_FAMILY = "regression_scenarios"
_OUT_PATH = _SCENARIOS_DIR / "generated_scenarios" / f"{_REGRESSION_FAMILY}.yaml"


def _next_index(existing: list[Scenario]) -> int:
    return len(existing) + 1


def _load_existing(path: Path = _OUT_PATH) -> list[Scenario]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return [Scenario.from_dict(d) for d in data.get("scenarios", [])]


def _save(scenarios: list[Scenario], path: Path = _OUT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            {"family": _REGRESSION_FAMILY, "scenarios": [s.to_dict() for s in scenarios]},
            f,
            sort_keys=False,
        )


class RegressionTestGenerator:
    def __init__(self, out_path: Path = _OUT_PATH) -> None:
        self._out_path = out_path

    def generate(self, example: LabeledExample) -> Scenario:
        if example.review.status.value != "approved":
            raise ValueError(
                f"refusing to generate a regression test from a {example.review.status} review"
            )

        existing = _load_existing(self._out_path)
        idx = _next_index(existing)
        corrected = example.review.corrected_expected_outcome

        scenario = Scenario(
            scenario_id=f"BB-REG-{example.event.failure_category.value.upper()[:8]}-{idx:04d}",
            family=_REGRESSION_FAMILY,
            category=corrected.get("category", "field_pilot"),
            risk_level=RiskLevel(corrected.get("risk_level", "HIGH")),
            input_conditions=InputConditions(extra={"source_event_id": example.event.event_id}),
            expected_behavior=corrected.get(
                "expected_behavior",
                f"correct handling of the field failure: {example.event.oracle_reason}",
            ),
            required_safety_response=corrected.get(
                "required_safety_response", "no unsafe action taken"
            ),
            dashboard_update=corrected.get("dashboard_update", "regression coverage updated"),
            pass_criteria=corrected.get(
                "pass_criteria", "the originally-failed oracle check now passes"
            ),
            fail_criteria=corrected.get(
                "fail_criteria", "the same oracle check fails again (regression)"
            ),
            mock_strategy=MockStrategy(corrected.get("mock_strategy", "full_mock")),
            hardware_requirement=HardwareRequirement(corrected.get("hardware_requirement", "none")),
            metrics_to_capture=("regression_pass_rate", "field_failure_rate"),
        )

        existing.append(scenario)
        _save(existing, self._out_path)
        return scenario

    def all_regression_scenarios(self) -> list[Scenario]:
        return _load_existing(self._out_path)
