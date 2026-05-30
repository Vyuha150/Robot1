"""Unit tests for bonbon_behavior_engine.core.operator_alerter."""

from __future__ import annotations

from bonbon_behavior_engine.core.operator_alerter import (
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    SEVERITY_CRITICAL,
    OperatorAlerter,
)


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class TestDedup:
    def test_first_alert_sends(self):
        a = OperatorAlerter()
        d = a.request("medical_emergency", SEVERITY_CRITICAL, "p1", "fell")
        assert d.should_send is True
        assert d.severity_label == "critical"

    def test_duplicate_within_cooldown_suppressed(self):
        clock = _Clock()
        a = OperatorAlerter(cooldown_sec=10.0, clock=clock)
        assert a.request("collision_risk", SEVERITY_MEDIUM, "p1", "x").should_send
        clock.t = 5.0
        d = a.request("collision_risk", SEVERITY_MEDIUM, "p1", "x")
        assert d.should_send is False
        assert "cooldown" in d.suppressed_reason

    def test_after_cooldown_sends_again(self):
        clock = _Clock()
        a = OperatorAlerter(cooldown_sec=10.0, clock=clock)
        a.request("collision_risk", SEVERITY_MEDIUM, "p1", "x")
        clock.t = 11.0
        assert a.request("collision_risk", SEVERITY_MEDIUM, "p1", "x").should_send is True

    def test_different_subject_not_deduped(self):
        a = OperatorAlerter(cooldown_sec=100.0)
        assert a.request("collision_risk", SEVERITY_MEDIUM, "p1", "x").should_send
        assert a.request("collision_risk", SEVERITY_MEDIUM, "p2", "y").should_send

    def test_different_type_not_deduped(self):
        a = OperatorAlerter(cooldown_sec=100.0)
        assert a.request("collision_risk", SEVERITY_MEDIUM, "p1", "x").should_send
        assert a.request("restricted_zone", SEVERITY_MEDIUM, "p1", "y").should_send


class TestEscalation:
    def test_escalation_bypasses_cooldown(self):
        clock = _Clock()
        a = OperatorAlerter(cooldown_sec=100.0, clock=clock)
        a.request("collision_risk", SEVERITY_LOW, "p1", "x")
        clock.t = 1.0
        # Higher severity for the same key fires immediately.
        d = a.request("collision_risk", SEVERITY_HIGH, "p1", "x")
        assert d.should_send is True

    def test_lower_severity_still_suppressed(self):
        clock = _Clock()
        a = OperatorAlerter(cooldown_sec=100.0, clock=clock)
        a.request("collision_risk", SEVERITY_HIGH, "p1", "x")
        clock.t = 1.0
        d = a.request("collision_risk", SEVERITY_LOW, "p1", "x")
        assert d.should_send is False


class TestTelemetry:
    def test_counters(self):
        a = OperatorAlerter(cooldown_sec=100.0)
        a.request("t", SEVERITY_MEDIUM, "s", "d")   # sent
        a.request("t", SEVERITY_MEDIUM, "s", "d")   # suppressed
        assert a.total_requested == 2
        assert a.total_sent == 1
        assert a.total_suppressed == 1

    def test_reset_clears_history(self):
        a = OperatorAlerter(cooldown_sec=100.0)
        a.request("t", SEVERITY_MEDIUM, "s", "d")
        a.reset()
        # After reset the same alert fires again.
        assert a.request("t", SEVERITY_MEDIUM, "s", "d").should_send is True
