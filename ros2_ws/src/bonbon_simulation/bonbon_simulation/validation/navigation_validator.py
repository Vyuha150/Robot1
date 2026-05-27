from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from bonbon_simulation.core.config import ValidationTargets


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    reason: str


class NavigationScenarioValidator:
    def __init__(self, targets: ValidationTargets) -> None:
        self.targets = targets

    def validate(self, metrics: Dict[str, float | int], criteria: Dict[str, float | int | bool]) -> ValidationResult:
        if metrics["collision_count"] > criteria.get("max_collisions", self.targets.max_collisions):
            return ValidationResult(False, "collision count exceeded")
        if metrics["navigation_success_rate"] < criteria.get("min_navigation_success_rate", self.targets.min_navigation_success_rate):
            return ValidationResult(False, "navigation success rate below target")
        if metrics["replanning_latency_ms"] > criteria.get("max_replanning_latency_ms", self.targets.max_replanning_latency_ms):
            return ValidationResult(False, "replanning latency exceeded target")
        if metrics["docking_success_rate"] < criteria.get("min_docking_success_rate", 0.0):
            return ValidationResult(False, "docking success rate below target")
        return ValidationResult(True, "navigation criteria satisfied")
