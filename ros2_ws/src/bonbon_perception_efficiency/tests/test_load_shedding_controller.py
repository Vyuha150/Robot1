"""Tests for LoadSheddingController — hysteresis-gated load level escalation."""

from __future__ import annotations

from bonbon_perception_efficiency.core.load_shedding_controller import (
    LoadLevel,
    LoadSheddingController,
)


class TestNominal:
    def test_no_pressure_stays_normal(self):
        ctrl = LoadSheddingController()
        decision = ctrl.update(
            cpu_overloaded=False,
            memory_pressure=False,
            resource_unavailable=False,
            safety_caution_or_above=False,
        )
        assert decision.level == LoadLevel.NORMAL
        assert decision.scale == 1.0

    def test_unavailable_metrics_never_shed(self):
        """Sim/CI has no real psutil metrics — must never shed load on
        missing data (would otherwise spuriously degrade simulation)."""
        ctrl = LoadSheddingController()
        decision = ctrl.update(
            cpu_overloaded=False,
            memory_pressure=False,
            resource_unavailable=True,
            safety_caution_or_above=False,
        )
        assert decision.level == LoadLevel.NORMAL


class TestEscalationIsImmediate:
    def test_cpu_overload_escalates_to_minimal_immediately(self):
        ctrl = LoadSheddingController(hysteresis_cycles=3)
        decision = ctrl.update(
            cpu_overloaded=True,
            memory_pressure=False,
            resource_unavailable=False,
            safety_caution_or_above=False,
        )
        assert decision.level == LoadLevel.MINIMAL  # no hysteresis delay on escalation

    def test_cpu_and_memory_both_overloaded_is_critical(self):
        ctrl = LoadSheddingController()
        decision = ctrl.update(
            cpu_overloaded=True,
            memory_pressure=True,
            resource_unavailable=False,
            safety_caution_or_above=False,
        )
        assert decision.level == LoadLevel.CRITICAL
        assert decision.scale < 0.2

    def test_safety_elevated_alone_only_reduces(self):
        ctrl = LoadSheddingController()
        decision = ctrl.update(
            cpu_overloaded=False,
            memory_pressure=False,
            resource_unavailable=False,
            safety_caution_or_above=True,
        )
        assert decision.level == LoadLevel.REDUCED


class TestDeescalationRequiresHysteresis:
    def test_recovery_does_not_immediately_drop_back_to_normal(self):
        ctrl = LoadSheddingController(hysteresis_cycles=3)
        ctrl.update(True, False, False, False)  # escalate to MINIMAL
        assert ctrl.current_level == LoadLevel.MINIMAL
        # One cycle of recovery is not enough.
        decision = ctrl.update(False, False, False, False)
        assert decision.level == LoadLevel.MINIMAL

    def test_recovery_commits_after_hysteresis_cycles(self):
        ctrl = LoadSheddingController(hysteresis_cycles=3)
        ctrl.update(True, False, False, False)  # MINIMAL
        for _ in range(3):
            decision = ctrl.update(False, False, False, False)
        assert decision.level == LoadLevel.NORMAL

    def test_flapping_input_does_not_cause_flapping_output(self):
        """The core anti-flap guarantee: alternating pressure/no-pressure
        must not oscillate the committed level every single cycle."""
        ctrl = LoadSheddingController(hysteresis_cycles=3)
        ctrl.update(True, False, False, False)  # escalate to MINIMAL
        levels = []
        for i in range(4):
            pressure = i % 2 == 0  # alternates, never sustains de-escalation
            levels.append(ctrl.update(pressure, False, False, False).level)
        assert all(level == LoadLevel.MINIMAL for level in levels)


class TestScaleMonotonicity:
    def test_scale_decreases_as_level_worsens(self):
        ctrl = LoadSheddingController()
        normal = ctrl.update(False, False, False, False).scale
        ctrl2 = LoadSheddingController()
        reduced = ctrl2.update(False, False, False, True).scale
        ctrl3 = LoadSheddingController()
        critical = ctrl3.update(True, True, False, False).scale
        assert normal > reduced > critical
