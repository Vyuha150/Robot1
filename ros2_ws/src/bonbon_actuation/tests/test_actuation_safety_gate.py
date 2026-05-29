"""Tests for bonbon_actuation.core.actuation_safety_gate."""

from __future__ import annotations

import pytest

from bonbon_actuation.core.actuation_safety_gate import (
    ActuationSafetyGate,
    LEVEL_INITIALIZING,
    LEVEL_NORMAL,
    LEVEL_CAUTION,
    LEVEL_DANGER,
    LEVEL_DOCKING,
    LEVEL_DEGRADED,
    LEVEL_FAULT,
    LEVEL_SAFE_STOP,
)


class TestInitialState:
    def test_starts_in_initializing_state(self):
        gate = ActuationSafetyGate()
        assert gate.safety_level == LEVEL_INITIALIZING

    def test_actuation_disabled_at_startup(self):
        gate = ActuationSafetyGate()
        assert gate.actuation_enabled is False

    def test_all_gestures_blocked_at_startup(self):
        gate = ActuationSafetyGate()
        allowed, reason = gate.is_allowed("wave", priority=20)
        assert allowed is False
        assert len(reason) > 0


class TestNormalLevel:
    def setup_method(self):
        self.gate = ActuationSafetyGate()
        self.gate.update_safety_state(LEVEL_NORMAL, actuation_enabled=True)

    def test_low_priority_allowed(self):
        allowed, _ = self.gate.is_allowed("idle_scan", priority=0)
        assert allowed is True

    def test_high_priority_allowed(self):
        allowed, _ = self.gate.is_allowed("wave", priority=10)
        assert allowed is True

    def test_emergency_priority_allowed(self):
        allowed, _ = self.gate.is_allowed("stop_gesture", priority=20)
        assert allowed is True

    def test_actuation_disabled_blocks_all(self):
        self.gate.update_safety_state(LEVEL_NORMAL, actuation_enabled=False)
        allowed, reason = self.gate.is_allowed("wave", priority=20)
        assert allowed is False
        assert "disabled" in reason.lower()


class TestCautionLevel:
    def setup_method(self):
        self.gate = ActuationSafetyGate()
        self.gate.update_safety_state(LEVEL_CAUTION, actuation_enabled=True)

    def test_low_priority_blocked(self):
        allowed, _ = self.gate.is_allowed("idle_scan", priority=0)
        assert allowed is False

    def test_normal_priority_allowed(self):
        allowed, _ = self.gate.is_allowed("nod_yes", priority=5)
        assert allowed is True

    def test_high_priority_allowed(self):
        allowed, _ = self.gate.is_allowed("stop_gesture", priority=10)
        assert allowed is True


class TestDangerLevel:
    def setup_method(self):
        self.gate = ActuationSafetyGate()
        self.gate.update_safety_state(LEVEL_DANGER, actuation_enabled=True)

    def test_low_priority_blocked(self):
        allowed, _ = self.gate.is_allowed("wave", priority=0)
        assert allowed is False

    def test_normal_priority_blocked(self):
        allowed, _ = self.gate.is_allowed("wave", priority=5)
        assert allowed is False

    def test_high_priority_allowed(self):
        allowed, _ = self.gate.is_allowed("stop_gesture", priority=10)
        assert allowed is True

    def test_emergency_priority_allowed(self):
        allowed, _ = self.gate.is_allowed("emergency_attention_pose", priority=20)
        assert allowed is True


class TestFaultAndSafeStop:
    @pytest.mark.parametrize("level", [LEVEL_FAULT, LEVEL_SAFE_STOP])
    def test_high_priority_blocked(self, level):
        gate = ActuationSafetyGate()
        gate.update_safety_state(level, actuation_enabled=True)
        allowed, _ = gate.is_allowed("stop_gesture", priority=10)
        assert allowed is False

    @pytest.mark.parametrize("level", [LEVEL_FAULT, LEVEL_SAFE_STOP])
    def test_emergency_priority_allowed(self, level):
        gate = ActuationSafetyGate()
        gate.update_safety_state(level, actuation_enabled=True)
        allowed, _ = gate.is_allowed("emergency_attention_pose", priority=20)
        assert allowed is True


class TestDockingLevel:
    def test_docking_allows_normal_priority(self):
        gate = ActuationSafetyGate()
        gate.update_safety_state(LEVEL_DOCKING, actuation_enabled=True)
        allowed, _ = gate.is_allowed("safe_folded_pose", priority=5)
        assert allowed is True

    def test_docking_blocks_low_priority(self):
        gate = ActuationSafetyGate()
        gate.update_safety_state(LEVEL_DOCKING, actuation_enabled=True)
        allowed, _ = gate.is_allowed("idle_scan", priority=0)
        assert allowed is False


class TestStateUpdate:
    def test_state_update_reflected_immediately(self):
        gate = ActuationSafetyGate()
        gate.update_safety_state(LEVEL_NORMAL, actuation_enabled=True)
        assert gate.is_allowed("wave", priority=0)[0] is True

        gate.update_safety_state(LEVEL_FAULT, actuation_enabled=True)
        assert gate.is_allowed("wave", priority=0)[0] is False

    def test_level_name_stored(self):
        gate = ActuationSafetyGate()
        gate.update_safety_state(LEVEL_CAUTION, actuation_enabled=True, level_name="CAUTION")
        assert gate.safety_level == LEVEL_CAUTION
