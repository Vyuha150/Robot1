"""Tests for DegradedModeManager — sustained-pressure escalation."""

from __future__ import annotations

from bonbon_perception_efficiency.core.degraded_mode_manager import DegradedModeManager
from bonbon_perception_efficiency.core.load_shedding_controller import LoadLevel


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class TestNominal:
    def test_normal_load_never_degraded(self):
        mgr = DegradedModeManager()
        status = mgr.update(LoadLevel.NORMAL, safety_fault_or_above=False)
        assert status.is_degraded is False


class TestSustainedPressureRequired:
    def test_brief_pressure_does_not_trigger_degraded(self):
        clock = _Clock()
        mgr = DegradedModeManager(sustained_threshold_sec=10.0, clock=clock)
        status = mgr.update(LoadLevel.CRITICAL, safety_fault_or_above=False)
        assert status.is_degraded is False  # just started, not sustained yet

    def test_sustained_pressure_triggers_degraded(self):
        clock = _Clock()
        mgr = DegradedModeManager(sustained_threshold_sec=5.0, clock=clock)
        mgr.update(LoadLevel.CRITICAL, safety_fault_or_above=False)
        clock.advance(6.0)
        status = mgr.update(LoadLevel.CRITICAL, safety_fault_or_above=False)
        assert status.is_degraded is True
        assert "sustained" in status.reason

    def test_pressure_clearing_resets_the_sustained_timer(self):
        clock = _Clock()
        mgr = DegradedModeManager(sustained_threshold_sec=5.0, clock=clock)
        mgr.update(LoadLevel.CRITICAL, safety_fault_or_above=False)
        clock.advance(3.0)
        mgr.update(LoadLevel.NORMAL, safety_fault_or_above=False)  # pressure clears
        clock.advance(3.0)
        status = mgr.update(LoadLevel.CRITICAL, safety_fault_or_above=False)
        # Only 0s of new sustained pressure (just restarted) — not degraded.
        assert status.is_degraded is False

    def test_recovering_from_degraded_clears_the_flag(self):
        clock = _Clock()
        mgr = DegradedModeManager(sustained_threshold_sec=5.0, clock=clock)
        mgr.update(LoadLevel.CRITICAL, safety_fault_or_above=False)
        clock.advance(6.0)
        assert mgr.update(LoadLevel.CRITICAL, safety_fault_or_above=False).is_degraded is True
        status = mgr.update(LoadLevel.NORMAL, safety_fault_or_above=False)
        assert status.is_degraded is False


class TestSafetyFaultImmediate:
    def test_safety_fault_triggers_degraded_immediately_no_wait(self):
        mgr = DegradedModeManager(sustained_threshold_sec=100.0)
        status = mgr.update(LoadLevel.NORMAL, safety_fault_or_above=True)
        assert status.is_degraded is True
        assert "safety" in status.reason.lower()

    def test_degraded_duration_increases_while_in_fault(self):
        clock = _Clock()
        mgr = DegradedModeManager(clock=clock)
        mgr.update(LoadLevel.NORMAL, safety_fault_or_above=True)
        clock.advance(5.0)
        status = mgr.update(LoadLevel.NORMAL, safety_fault_or_above=True)
        assert abs(status.duration_sec - 5.0) < 1e-6
