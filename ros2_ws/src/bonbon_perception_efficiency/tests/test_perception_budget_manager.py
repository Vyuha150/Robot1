"""Tests for PerceptionBudgetManager — the central per-cycle orchestrator."""

from __future__ import annotations

from bonbon_perception_efficiency.core.degraded_mode_manager import DegradedModeManager
from bonbon_perception_efficiency.core.load_shedding_controller import (
    LoadLevel,
    LoadSheddingController,
)
from bonbon_perception_efficiency.core.perception_budget_manager import (
    BudgetInputs,
    PerceptionBudgetManager,
)


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class TestNominalCycle:
    def test_nominal_inputs_produce_full_budget(self):
        mgr = PerceptionBudgetManager()
        budget = mgr.update(BudgetInputs(resource_unavailable=False))
        assert budget.load.level == LoadLevel.NORMAL
        assert budget.degraded.is_degraded is False
        assert len(budget.sample_rates) > 0
        assert len(budget.confidence_policy) > 0

    def test_empty_person_list_produces_no_focus_weights(self):
        mgr = PerceptionBudgetManager()
        budget = mgr.update(BudgetInputs(resource_unavailable=False))
        assert budget.person_focus == []


class TestOverloadPropagatesThroughEveryComponent:
    def test_cpu_overload_raises_confidence_thresholds_via_degraded_eventually(self):
        clock = _Clock()
        mgr = PerceptionBudgetManager(
            load_shedding=LoadSheddingController(),
            degraded_mode=DegradedModeManager(sustained_threshold_sec=1.0, clock=clock),
        )
        mgr.update(BudgetInputs(cpu_overloaded=True, resource_unavailable=False))
        clock.advance(2.0)
        budget = mgr.update(BudgetInputs(cpu_overloaded=True, resource_unavailable=False))
        assert budget.degraded.is_degraded is True
        gesture_policy = next(p for p in budget.confidence_policy if p.signal == "gesture")
        assert gesture_policy.recommended_threshold > 0.65  # raised above nominal

    def test_cpu_overload_increases_sample_interval(self):
        mgr = PerceptionBudgetManager()
        nominal = mgr.update(BudgetInputs(resource_unavailable=False))
        mgr2 = PerceptionBudgetManager()
        overloaded = mgr2.update(BudgetInputs(cpu_overloaded=True, resource_unavailable=False))
        nominal_rate = next(r for r in nominal.sample_rates if r.consumer == "gesture")
        overloaded_rate = next(r for r in overloaded.sample_rates if r.consumer == "gesture")
        assert overloaded_rate.sample_every_n_frames > nominal_rate.sample_every_n_frames


class TestPersonFocusIntegration:
    def test_focus_person_gets_full_weight_in_consolidated_budget(self):
        mgr = PerceptionBudgetManager()
        budget = mgr.update(
            BudgetInputs(
                resource_unavailable=False,
                focus_person_track_id="ptrk_1",
                person_track_ids=["ptrk_1", "ptrk_2"],
            )
        )
        focus = next(w for w in budget.person_focus if w.person_track_id == "ptrk_1")
        bg = next(w for w in budget.person_focus if w.person_track_id == "ptrk_2")
        assert focus.weight > bg.weight


class TestSafetyFaultCascades:
    def test_safety_fault_immediately_degrades_the_whole_budget(self):
        mgr = PerceptionBudgetManager()
        budget = mgr.update(BudgetInputs(resource_unavailable=False, safety_fault_or_above=True))
        assert budget.degraded.is_degraded is True


class TestThermalPropagatesThroughBudget:
    def test_thermal_overload_reduces_load_level(self):
        mgr = PerceptionBudgetManager()
        budget = mgr.update(BudgetInputs(resource_unavailable=False, thermal_overloaded=True))
        assert budget.load.level == LoadLevel.MINIMAL

    def test_thermal_overload_increases_sample_interval(self):
        mgr = PerceptionBudgetManager()
        nominal = mgr.update(BudgetInputs(resource_unavailable=False))
        mgr2 = PerceptionBudgetManager()
        hot = mgr2.update(BudgetInputs(resource_unavailable=False, thermal_overloaded=True))
        nominal_rate = next(r for r in nominal.sample_rates if r.consumer == "gesture")
        hot_rate = next(r for r in hot.sample_rates if r.consumer == "gesture")
        assert hot_rate.sample_every_n_frames > nominal_rate.sample_every_n_frames
