from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Dict, List


@dataclass
class SimulationMetricsCollector:
    navigation_attempts: int = 0
    navigation_successes: int = 0
    collisions: int = 0
    near_misses: int = 0
    path_deviation_samples_m: List[float] = field(default_factory=list)
    estop_reaction_ms: List[float] = field(default_factory=list)
    obstacle_detection_latency_ms: List[float] = field(default_factory=list)
    replanning_latency_ms: List[float] = field(default_factory=list)
    recovery_attempts: int = 0
    recovery_successes: int = 0
    cpu_usage_pct: List[float] = field(default_factory=list)
    memory_usage_mb: List[float] = field(default_factory=list)
    task_completion_times_sec: List[float] = field(default_factory=list)
    battery_usage_pct: float = 0.0
    false_positive_safety_stops: int = 0
    false_negative_safety_events: int = 0
    docking_attempts: int = 0
    docking_successes: int = 0

    def as_dict(self) -> Dict[str, float | int]:
        return {
            "navigation_success_rate": self._rate(self.navigation_successes, self.navigation_attempts),
            "collision_count": self.collisions,
            "near_miss_count": self.near_misses,
            "average_path_deviation_m": self._avg(self.path_deviation_samples_m),
            "emergency_stop_reaction_time_ms": self._avg(self.estop_reaction_ms),
            "obstacle_detection_latency_ms": self._avg(self.obstacle_detection_latency_ms),
            "replanning_latency_ms": self._avg(self.replanning_latency_ms),
            "recovery_success_rate": self._rate(self.recovery_successes, self.recovery_attempts),
            "cpu_usage_pct": self._avg(self.cpu_usage_pct),
            "memory_usage_mb": self._avg(self.memory_usage_mb),
            "average_task_completion_time_sec": self._avg(self.task_completion_times_sec),
            "battery_usage_estimate_pct": self.battery_usage_pct,
            "false_positive_safety_stops": self.false_positive_safety_stops,
            "false_negative_safety_events": self.false_negative_safety_events,
            "docking_success_rate": self._rate(self.docking_successes, self.docking_attempts),
        }

    @staticmethod
    def _avg(values: List[float]) -> float:
        return float(mean(values)) if values else 0.0

    @staticmethod
    def _rate(successes: int, attempts: int) -> float:
        return 1.0 if attempts == 0 else successes / attempts
