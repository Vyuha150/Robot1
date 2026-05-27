from __future__ import annotations

from bonbon_simulation.core.config import ValidationTargets
from bonbon_simulation.validation.navigation_validator import ValidationResult


class SafetyScenarioValidator:
    def __init__(self, targets: ValidationTargets) -> None:
        self.targets = targets

    def validate(
        self, metrics: dict[str, float | int], criteria: dict[str, float | int | bool]
    ) -> ValidationResult:
        if metrics["emergency_stop_reaction_time_ms"] > criteria.get(
            "max_estop_reaction_ms", self.targets.max_estop_reaction_ms
        ):
            return ValidationResult(False, "emergency stop reaction exceeded target")
        if metrics["false_negative_safety_events"] > criteria.get(
            "max_false_negative_safety_events", 0
        ):
            return ValidationResult(False, "false negative safety events detected")
        if metrics["false_positive_safety_stops"] > criteria.get(
            "max_false_positive_safety_stops", 0
        ):
            return ValidationResult(False, "false positive safety stops exceeded target")
        return ValidationResult(True, "safety criteria satisfied")
