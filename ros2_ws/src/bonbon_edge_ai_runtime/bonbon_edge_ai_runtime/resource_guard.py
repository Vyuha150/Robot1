"""bonbon_edge_ai_runtime.resource_guard -- Edge AI Runtime brief Phase
8. A thin, read-only facade unifying the three resource-guarding
mechanisms that already exist and are already tested:
bonbon_safety.core.resource_monitor.ResourceMonitor (CPU/RAM/disk),
bonbon_perception_efficiency.core.load_shedding_controller.LoadSheddingController
(hysteresis-gated load level), and bonbon_llm.core.pi2_llm_guard.Pi2LLMGuard
(LLM-specific CPU/temp/safety-state disable). See
docs/DUPLICATE_PIPELINE_AUDIT.md -- none of that threshold logic is
reimplemented here.

Cross-package Python imports here are a deliberate exception, not a
violation of this repo's "packages talk only via ROS2 messages, never
direct Python imports" convention documented in
load_shedding_controller.py's own docstring: that convention protects
the live control loop from tight coupling between domain packages
running independently on the same Pi. This module is the same class of
cross-cutting, read-only, dashboard/routing-decision aggregation layer
bonbon_ai_model_registry already establishes precedent for (it directly
imports bonbon_ai_runtime, bonbon_sarvam_adapter, etc.) -- it never
feeds a control loop, only a routing decision (inference_scheduler.py)
and a dashboard view (dashboard_publisher.py). Every import is lazy, so
importing this module never requires bonbon_safety/
bonbon_perception_efficiency/bonbon_llm's own dependencies to be
installed if the caller only wants, say, the CPU/RAM numbers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ResourceGuardStatus:
    cpu_percent: float
    memory_percent: float
    disk_free_percent: float
    temp_c: float
    metrics_available: bool
    load_level: str  # "normal" | "reduced" | "minimal" | "critical"
    load_scale: float  # 0.0-1.0, perception processing scale recommendation
    load_reason: str
    llm_disabled: bool
    llm_disable_reason: str

    def to_dict(self) -> dict:
        return {
            "cpuPercent": self.cpu_percent,
            "memoryPercent": self.memory_percent,
            "diskFreePercent": self.disk_free_percent,
            "tempC": self.temp_c,
            "metricsAvailable": self.metrics_available,
            "loadLevel": self.load_level,
            "loadScale": self.load_scale,
            "loadReason": self.load_reason,
            "llmDisabled": self.llm_disabled,
            "llmDisableReason": self.llm_disable_reason,
        }


# Mirrors config/pi_efficiency_profile.yaml's cpu_temp_fault_c -- the
# single source of truth for this threshold across bonbon_safety,
# bonbon_perception_efficiency, and bonbon_llm (verified consistent in
# docs/THREE_PI_RUNTIME_AUDIT.md). Duplicated here as a constant rather
# than re-parsing the YAML on every evaluate() call; config_loader.py
# reads the authoritative value at startup for callers that need it.
DEFAULT_THERMAL_FAULT_C = 90.0


class ResourceGuard:
    """Call evaluate() once per cycle (dashboard poll, task_router
    decision, inference_scheduler tick) rather than constructing new
    monitor/controller instances each time -- all three underlying
    components carry state (hysteresis, in-flight LLM count) that must
    persist across calls."""

    def __init__(
        self,
        *,
        data_path: str = "/",
        hysteresis_cycles: int = 3,
        thermal_fault_c: float = DEFAULT_THERMAL_FAULT_C,
    ) -> None:
        from bonbon_llm.core.pi2_llm_guard import Pi2LLMGuard
        from bonbon_perception_efficiency.core.load_shedding_controller import (
            LoadSheddingController,
        )
        from bonbon_safety.core.resource_monitor import ResourceMonitor

        self._monitor = ResourceMonitor(data_path=data_path)
        self._shedding = LoadSheddingController(hysteresis_cycles=hysteresis_cycles)
        self._llm_guard = Pi2LLMGuard()
        self._thermal_fault_c = thermal_fault_c

    def evaluate(
        self,
        temp_c: float,
        safety_state_name: str,
        safety_caution_or_above: bool,
    ) -> ResourceGuardStatus:
        snap = self._monitor.sample()
        thermal_overloaded = temp_c >= self._thermal_fault_c
        decision = self._shedding.update(
            cpu_overloaded=snap.cpu_overloaded,
            memory_pressure=snap.memory_pressure,
            resource_unavailable=not snap.available,
            safety_caution_or_above=safety_caution_or_above,
            thermal_overloaded=thermal_overloaded,
        )
        llm_decision = self._llm_guard.should_disable(snap.cpu_percent, temp_c, safety_state_name)
        return ResourceGuardStatus(
            cpu_percent=snap.cpu_percent,
            memory_percent=snap.memory_percent,
            disk_free_percent=snap.disk_free_percent,
            temp_c=temp_c,
            metrics_available=snap.available,
            load_level=decision.level.value,
            load_scale=decision.scale,
            load_reason=decision.reason,
            llm_disabled=llm_decision.disabled,
            llm_disable_reason=llm_decision.reason,
        )

    @property
    def llm_guard(self):
        """Exposes the underlying Pi2LLMGuard so callers that need
        try_acquire()/release()/clamp_max_tokens() (not just the
        disable decision) don't have to construct a second instance
        with its own, disconnected in-flight-request counter."""
        return self._llm_guard
