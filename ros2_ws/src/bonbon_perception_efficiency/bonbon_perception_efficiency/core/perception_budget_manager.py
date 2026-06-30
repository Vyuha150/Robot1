"""PerceptionBudgetManager — the central orchestrator.

Owns one instance of each coordination primitive and combines their outputs
into a single consolidated budget per cycle. This is the only class the ROS2
node needs to drive every cycle; everything else in core/ is composable on
its own (for unit testing and for any future consumer that only needs one
piece).

This module performs zero detection/inference itself — it only combines
already-computed signals (resource usage, safety state, person tracks) into
a recommendation. It never issues a command to any other node.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bonbon_perception_efficiency.core.active_person_focus_manager import (
    ActivePersonFocusManager,
    PersonFocusWeight,
)
from bonbon_perception_efficiency.core.confidence_policy_manager import (
    ConfidencePolicyManager,
    PolicyRecommendation,
)
from bonbon_perception_efficiency.core.degraded_mode_manager import (
    DegradedModeManager,
    DegradedModeStatus,
)
from bonbon_perception_efficiency.core.frame_sampling_manager import (
    FrameSamplingManager,
    SampleRateRecommendation,
)
from bonbon_perception_efficiency.core.load_shedding_controller import (
    LoadSheddingController,
    LoadSheddingDecision,
)


@dataclass
class PerceptionBudget:
    load: LoadSheddingDecision
    degraded: DegradedModeStatus
    sample_rates: list[SampleRateRecommendation]
    confidence_policy: list[PolicyRecommendation]
    person_focus: list[PersonFocusWeight]


@dataclass
class BudgetInputs:
    cpu_overloaded: bool = False
    memory_pressure: bool = False
    resource_unavailable: bool = True
    safety_caution_or_above: bool = False
    safety_fault_or_above: bool = False
    thermal_overloaded: bool = False
    focus_person_track_id: str = ""
    person_track_ids: list[str] = field(default_factory=list)
    new_candidate_ids: set = field(default_factory=set)


class PerceptionBudgetManager:
    def __init__(
        self,
        load_shedding: LoadSheddingController | None = None,
        frame_sampling: FrameSamplingManager | None = None,
        confidence_policy: ConfidencePolicyManager | None = None,
        person_focus: ActivePersonFocusManager | None = None,
        degraded_mode: DegradedModeManager | None = None,
    ) -> None:
        self._load_shedding = load_shedding or LoadSheddingController()
        self._frame_sampling = frame_sampling or FrameSamplingManager()
        self._confidence_policy = confidence_policy or ConfidencePolicyManager()
        self._person_focus = person_focus or ActivePersonFocusManager()
        self._degraded_mode = degraded_mode or DegradedModeManager()

    def update(self, inputs: BudgetInputs) -> PerceptionBudget:
        load = self._load_shedding.update(
            cpu_overloaded=inputs.cpu_overloaded,
            memory_pressure=inputs.memory_pressure,
            resource_unavailable=inputs.resource_unavailable,
            safety_caution_or_above=inputs.safety_caution_or_above,
            thermal_overloaded=inputs.thermal_overloaded,
        )
        degraded = self._degraded_mode.update(
            load_level=load.level, safety_fault_or_above=inputs.safety_fault_or_above
        )
        sample_rates = self._frame_sampling.recommend(load_shed_scale=load.scale)
        confidence_policy = self._confidence_policy.recommend(
            degraded=degraded.is_degraded, safety_caution_or_above=inputs.safety_caution_or_above
        )
        person_focus = self._person_focus.compute_weights(
            inputs.focus_person_track_id, inputs.person_track_ids, inputs.new_candidate_ids
        )
        return PerceptionBudget(
            load=load,
            degraded=degraded,
            sample_rates=sample_rates,
            confidence_policy=confidence_policy,
            person_focus=person_focus,
        )
