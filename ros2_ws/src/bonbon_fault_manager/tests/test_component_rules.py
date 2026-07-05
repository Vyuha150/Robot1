"""Tests for bonbon_fault_manager.core.component_rules."""

from __future__ import annotations

import pytest
from bonbon_fault_manager.core.component_rules import (
    DEVICE_INFO,
    classify,
    component_info,
)
from bonbon_fault_manager.core.fault_taxonomy import FaultLevel


class TestComponentInfo:
    def test_known_device_returns_real_subsystem_and_pi(self):
        info = component_info("stepper")
        assert info.subsystem == "actuation"
        assert info.affected_pi == "pi3"

    def test_unknown_device_returns_unknown(self):
        info = component_info("teleporter")
        assert info.subsystem == "unknown"
        assert info.affected_pi == "unknown"

    def test_every_bom_device_is_registered(self):
        # The 7 real BOM component categories this workstream targets.
        for device in ("microphone", "camera", "speaker", "motor", "lidar", "stepper", "servo"):
            assert device in DEVICE_INFO


class TestClassifyKnownRules:
    def test_mic_usb_disconnect_is_critical(self):
        level, action = classify("microphone", "USB_DISCONNECTED", severity=2)
        assert level == FaultLevel.CRITICAL
        assert "ReSpeaker" in action

    def test_camera_sdk_missing_is_blocked(self):
        level, action = classify("camera", "SDK_MISSING", severity=3)
        assert level == FaultLevel.BLOCKED
        assert "depthai" in action

    def test_speaker_pam8610_gpio_fail_is_warning_not_fatal(self):
        # PAM8610 mute-pin failure must not be treated as severely as a
        # total playback failure -- ALSA audio still works.
        level, action = classify("speaker", "PAM8610_GPIO_INIT_FAILED", severity=2)
        assert level == FaultLevel.WARNING
        assert "mute" in action.lower()

    def test_motor_serial_open_failed_is_critical(self):
        level, _ = classify("motor", "SERIAL_OPEN_FAILED", severity=2)
        assert level == FaultLevel.CRITICAL

    def test_lidar_health_error_is_fault(self):
        level, _ = classify("lidar", "HEALTH_ERROR", severity=2)
        assert level == FaultLevel.FAULT

    def test_stepper_stalled_is_fault_with_clear_stall_guidance(self):
        level, action = classify("stepper", "STALLED", severity=2)
        assert level == FaultLevel.FAULT
        assert "clear_stall" in action

    def test_servo_i2c_init_failed_is_critical(self):
        level, action = classify("servo", "I2C_INIT_FAILED", severity=2)
        assert level == FaultLevel.CRITICAL
        assert "0x40" in action

    def test_estop_gpio_init_failed_is_blocked(self):
        # Safety-critical component: any fault here must be at least BLOCKED.
        level, action = classify("estop", "GPIO_INIT_FAILED", severity=2)
        assert level == FaultLevel.BLOCKED
        assert "SAFETY CRITICAL" in action


class TestClassifyRecovery:
    def test_is_recovered_always_wins_over_error_code(self):
        level, action = classify("microphone", "USB_DISCONNECTED", severity=2, is_recovered=True)
        assert level == FaultLevel.OK
        assert "Recovered" in action


class TestClassifyFallback:
    def test_unknown_device_error_pair_uses_severity_fallback(self):
        level, action = classify("camera", "SOME_NEW_ERROR_CODE", severity=3)
        assert level == FaultLevel.FAULT  # FATAL -> FAULT
        assert "No component-specific rule" in action

    def test_fallback_never_auto_escalates_past_fault(self):
        # Even FATAL severity should not silently become CRITICAL/BLOCKED
        # without an explicit rule -- those levels are a judgment call.
        level, _ = classify("unknown_device", "UNKNOWN_CODE", severity=3)
        assert level <= FaultLevel.FAULT

    @pytest.mark.parametrize(
        "severity,expected",
        [
            (0, FaultLevel.OK),
            (1, FaultLevel.WARNING),
            (2, FaultLevel.DEGRADED),
            (3, FaultLevel.FAULT),
        ],
    )
    def test_severity_mapping(self, severity, expected):
        level, _ = classify("unmapped_device", "UNMAPPED_CODE", severity=severity)
        assert level == expected


if __name__ == "__main__":
    pytest.main([__file__])
