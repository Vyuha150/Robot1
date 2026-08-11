"""bonbon_edge_ai_runtime.degraded_mode_manager -- Edge AI Runtime brief
Phase 2. Per docs/DUPLICATE_PIPELINE_AUDIT.md, a real
DegradedModeManager already exists under this exact name in
bonbon_perception_efficiency.core.degraded_mode_manager, backed by
config/runtime/degraded_mode.yaml, with correctly-scoped
never_disable/shed_order semantics and its own test suite. Building a
second one here would be a literal duplicate, not just a near-miss --
this module is a thin bridge that constructs and delegates to the real
one (lazy-imported, same cross-cutting-aggregation-layer exception
documented in resource_guard.py), adding only the piece that doesn't
exist yet: reporting degraded status alongside
bonbon_ai_model_registry's own, separate `FallbackDecision.degraded`
concept (per-capability model exhaustion) in one combined view, since
those are two different meanings of "degraded" that a dashboard caller
needs to distinguish, not conflate.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CombinedDegradedStatus:
    perception_degraded: bool
    perception_reason: str
    perception_duration_sec: float
    capabilities_degraded: dict[str, str]  # capability -> reason, only for exhausted fallback chains

    def to_dict(self) -> dict:
        return {
            "perceptionDegraded": self.perception_degraded,
            "perceptionReason": self.perception_reason,
            "perceptionDurationSec": self.perception_duration_sec,
            "capabilitiesDegraded": self.capabilities_degraded,
            "anyDegraded": self.perception_degraded or bool(self.capabilities_degraded),
        }


class EdgeDegradedModeManager:
    def __init__(self, *, sustained_threshold_sec: float = 10.0) -> None:
        from bonbon_perception_efficiency.core.degraded_mode_manager import DegradedModeManager

        self._perception_manager = DegradedModeManager(sustained_threshold_sec=sustained_threshold_sec)

    def update(
        self,
        load_level,  # bonbon_perception_efficiency.core.load_shedding_controller.LoadLevel
        safety_fault_or_above: bool,
        capability_fallback_decisions: dict | None = None,
    ) -> CombinedDegradedStatus:
        """`capability_fallback_decisions` is a dict of capability ->
        FallbackDecision (from bonbon_ai_model_registry / this package's
        runtime_selector), used to report which capabilities have
        exhausted their fallback chain -- separate from, and combined
        with, the perception-layer sustained-pressure signal."""
        perception_status = self._perception_manager.update(load_level, safety_fault_or_above)
        capability_fallback_decisions = capability_fallback_decisions or {}
        capabilities_degraded = {
            capability: decision.reason
            for capability, decision in capability_fallback_decisions.items()
            if getattr(decision, "degraded", False)
        }
        return CombinedDegradedStatus(
            perception_degraded=perception_status.is_degraded,
            perception_reason=perception_status.reason,
            perception_duration_sec=perception_status.duration_sec,
            capabilities_degraded=capabilities_degraded,
        )
