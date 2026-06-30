"""Data model for generated production scenarios.

Pure Python, no ROS2/pytest import — importable from the generator, from
every `tests/production/test_*_scenarios.py` file, and from
`bonbon_behavior_validation` without pulling in a workspace.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class RiskLevel(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class MockStrategy(StrEnum):
    """How a scenario's inputs are supplied when it runs."""

    FULL_MOCK = "full_mock"
    PARTIAL_MOCK = "partial_mock"
    SIMULATION_REPLAY = "simulation_replay"
    REAL_HARDWARE = "real_hardware"


class HardwareRequirement(StrEnum):
    """What the scenario needs to actually execute (not just be defined)."""

    NONE = "none"
    SIMULATION = "simulation"
    PI = "pi"
    AI_HAT = "ai_hat"


# Default value used for any axis a family does not vary.
DEFAULT_AXIS_VALUE: dict[str, str] = {
    "environment": "office_reception",
    "lighting": "bright",
    "people": "one_person",
    "gesture": "none",
    "speech": "silent",
    "robot_state": "idle",
    "sensor": "normal",
}


@dataclass(frozen=True)
class InputConditions:
    """The combination of variables a concrete scenario exercises.

    Only axes a family declared as relevant differ from
    ``DEFAULT_AXIS_VALUE``; everything else is held at baseline so the
    scenario isolates the variable(s) actually under test.
    """

    environment: str = DEFAULT_AXIS_VALUE["environment"]
    lighting: str = DEFAULT_AXIS_VALUE["lighting"]
    people: str = DEFAULT_AXIS_VALUE["people"]
    gesture: str = DEFAULT_AXIS_VALUE["gesture"]
    speech: str = DEFAULT_AXIS_VALUE["speech"]
    robot_state: str = DEFAULT_AXIS_VALUE["robot_state"]
    sensor: str = DEFAULT_AXIS_VALUE["sensor"]
    extra: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InputConditions:
        known = {k: v for k, v in data.items() if k != "extra"}
        return cls(**known, extra=dict(data.get("extra", {})))


@dataclass(frozen=True)
class Scenario:
    """One concrete, individually-IDed production scenario."""

    scenario_id: str
    family: str
    category: str
    risk_level: RiskLevel
    input_conditions: InputConditions
    expected_behavior: str
    required_safety_response: str
    dashboard_update: str
    pass_criteria: str
    fail_criteria: str
    mock_strategy: MockStrategy
    hardware_requirement: HardwareRequirement
    metrics_to_capture: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["risk_level"] = self.risk_level.value
        d["mock_strategy"] = self.mock_strategy.value
        d["hardware_requirement"] = self.hardware_requirement.value
        d["metrics_to_capture"] = list(self.metrics_to_capture)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Scenario:
        return cls(
            scenario_id=data["scenario_id"],
            family=data["family"],
            category=data["category"],
            risk_level=RiskLevel(data["risk_level"]),
            input_conditions=InputConditions.from_dict(data["input_conditions"]),
            expected_behavior=data["expected_behavior"],
            required_safety_response=data["required_safety_response"],
            dashboard_update=data["dashboard_update"],
            pass_criteria=data["pass_criteria"],
            fail_criteria=data["fail_criteria"],
            mock_strategy=MockStrategy(data["mock_strategy"]),
            hardware_requirement=HardwareRequirement(data["hardware_requirement"]),
            metrics_to_capture=tuple(data.get("metrics_to_capture", [])),
        )

    @property
    def is_hardware_gated(self) -> bool:
        return self.hardware_requirement in (HardwareRequirement.PI, HardwareRequirement.AI_HAT)
