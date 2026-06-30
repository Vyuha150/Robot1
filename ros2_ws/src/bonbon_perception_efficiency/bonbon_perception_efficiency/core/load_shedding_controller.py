"""LoadSheddingController — escalates/de-escalates a perception-layer load
level based on /bonbon/system/resource_usage, with hysteresis so it doesn't
flap at a threshold boundary.

Conceptually parallel to bonbon_safety's SafetyLevel FSM (hysteresis-gated
state escalation) but deliberately NOT importing bonbon_safety's internals —
no package in this project imports another's core Python classes directly,
only their ROS2 messages (SafetyState, ResourceUsage); this keeps that
convention rather than introducing a new kind of cross-package coupling.

This never touches actuation, navigation, or anything safety-gated — it only
recommends a perception-layer processing scale. The Safety Supervisor's own
SafetyState is consumed as an additional escalation input (a CAUTION+ safety
level also triggers shedding, since perception load competes with safety
processing for the same CPU), never the other way around.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LoadLevel(StrEnum):
    NORMAL = "normal"
    REDUCED = "reduced"
    MINIMAL = "minimal"
    CRITICAL = "critical"


_SCALE_BY_LEVEL = {
    LoadLevel.NORMAL: 1.0,
    LoadLevel.REDUCED: 0.7,
    LoadLevel.MINIMAL: 0.4,
    LoadLevel.CRITICAL: 0.15,
}
_ORDER = [LoadLevel.NORMAL, LoadLevel.REDUCED, LoadLevel.MINIMAL, LoadLevel.CRITICAL]


@dataclass
class LoadSheddingDecision:
    level: LoadLevel
    scale: float
    reason: str


class LoadSheddingController:
    def __init__(self, hysteresis_cycles: int = 3) -> None:
        self._hysteresis = max(1, hysteresis_cycles)
        self._level = LoadLevel.NORMAL
        self._pending_level: LoadLevel | None = None
        self._pending_count = 0

    def update(
        self,
        cpu_overloaded: bool,
        memory_pressure: bool,
        resource_unavailable: bool,
        safety_caution_or_above: bool,
        thermal_overloaded: bool = False,
    ) -> LoadSheddingDecision:
        target, reason = self._evaluate_target(
            cpu_overloaded,
            memory_pressure,
            resource_unavailable,
            safety_caution_or_above,
            thermal_overloaded,
        )

        if target == self._level:
            self._pending_level = None
            self._pending_count = 0
        else:
            # Escalation (more shedding) is immediate — never delay backing
            # off load under real pressure. De-escalation requires
            # hysteresis_cycles of consistent improvement before committing,
            # to avoid flapping back and forth at a threshold boundary.
            is_escalation = _ORDER.index(target) > _ORDER.index(self._level)
            if is_escalation:
                self._level = target
                self._pending_level = None
                self._pending_count = 0
            else:
                if self._pending_level == target:
                    self._pending_count += 1
                else:
                    self._pending_level = target
                    self._pending_count = 1
                if self._pending_count >= self._hysteresis:
                    self._level = target
                    self._pending_level = None
                    self._pending_count = 0

        return LoadSheddingDecision(self._level, _SCALE_BY_LEVEL[self._level], reason)

    @staticmethod
    def _evaluate_target(
        cpu_overloaded: bool,
        memory_pressure: bool,
        resource_unavailable: bool,
        safety_elevated: bool,
        thermal_overloaded: bool = False,
    ) -> tuple[LoadLevel, str]:
        if resource_unavailable:
            # No real metrics (sim/CI) — never shed load on missing data.
            return LoadLevel.NORMAL, "resource metrics unavailable — assuming nominal"
        # Thermal is treated the same severity as CPU overload — sustained
        # high SoC temperature is itself a consequence of sustained high CPU
        # load, and reducing perception throughput is a direct, immediate
        # lever to bring it back down before bonbon_safety's own
        # cpu_temp_fault_c threshold (90°C) is reached and a SAFE_STOP is
        # forced. The 75°C trigger mirrors bonbon_safety's SafetyStateMachine
        # cpu_temp_caution_c default exactly, so this acts preventively,
        # strictly before the Safety Supervisor itself has to intervene.
        if cpu_overloaded and memory_pressure:
            return LoadLevel.CRITICAL, "CPU and memory both overloaded"
        if thermal_overloaded and (cpu_overloaded or memory_pressure):
            return LoadLevel.CRITICAL, "thermal overload combined with CPU/memory pressure"
        if cpu_overloaded:
            return LoadLevel.MINIMAL, "CPU overloaded"
        if memory_pressure:
            return LoadLevel.MINIMAL, "memory pressure"
        if thermal_overloaded:
            return LoadLevel.MINIMAL, "thermal overload (SoC temperature elevated)"
        if safety_elevated:
            return LoadLevel.REDUCED, "safety level elevated — perception competing for CPU"
        return LoadLevel.NORMAL, "nominal"

    @property
    def current_level(self) -> LoadLevel:
        return self._level
