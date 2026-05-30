"""Unit tests for bonbon_safety.core.fault_levels."""

from __future__ import annotations

from bonbon_safety.core.fault_levels import (
    FallbackLevel,
    escalate,
    fallback_to_safety_level,
    is_self_recoverable,
    requires_operator,
)
from bonbon_safety.core.safety_state_machine import SafetyLevel


class TestOrdering:
    def test_levels_are_monotonic(self):
        assert FallbackLevel.NORMAL < FallbackLevel.DEGRADED < FallbackLevel.SAFE_PAUSE
        assert FallbackLevel.SAFE_STOP < FallbackLevel.EMERGENCY_STOP < FallbackLevel.HUMAN_REQUIRED

    def test_escalate_returns_more_severe(self):
        assert escalate(FallbackLevel.DEGRADED, FallbackLevel.SAFE_STOP) == FallbackLevel.SAFE_STOP
        assert escalate(FallbackLevel.SAFE_PAUSE, FallbackLevel.NORMAL) == FallbackLevel.SAFE_PAUSE


class TestSafetyMapping:
    def test_normal_maps_to_normal(self):
        assert fallback_to_safety_level(FallbackLevel.NORMAL) == SafetyLevel.NORMAL

    def test_emergency_maps_to_safe_stop(self):
        assert fallback_to_safety_level(FallbackLevel.EMERGENCY_STOP) == SafetyLevel.SAFE_STOP

    def test_human_required_maps_to_fault(self):
        assert fallback_to_safety_level(FallbackLevel.HUMAN_REQUIRED) == SafetyLevel.FAULT

    def test_every_level_maps(self):
        for lvl in FallbackLevel:
            assert isinstance(fallback_to_safety_level(lvl), SafetyLevel)


class TestPolicies:
    def test_operator_required_at_safe_stop_and_above(self):
        assert requires_operator(FallbackLevel.SAFE_STOP) is True
        assert requires_operator(FallbackLevel.EMERGENCY_STOP) is True
        assert requires_operator(FallbackLevel.HUMAN_REQUIRED) is True

    def test_operator_not_required_below_safe_stop(self):
        assert requires_operator(FallbackLevel.NORMAL) is False
        assert requires_operator(FallbackLevel.DEGRADED) is False
        assert requires_operator(FallbackLevel.SAFE_PAUSE) is False

    def test_self_recoverable_up_to_safe_stop(self):
        assert is_self_recoverable(FallbackLevel.SAFE_STOP) is True
        assert is_self_recoverable(FallbackLevel.EMERGENCY_STOP) is False
        assert is_self_recoverable(FallbackLevel.HUMAN_REQUIRED) is False
