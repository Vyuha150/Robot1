"""Tests for bonbon_actuation.core.servo_validator."""

from __future__ import annotations

import pytest

from bonbon_actuation.core.gesture_library import (
    SERVO_HEAD_PAN, SERVO_HEAD_TILT, SERVO_HEAD_ROLL,
    SERVO_RIGHT_SHOULDER, SERVO_RIGHT_ELBOW,
    ServoTarget,
)
from bonbon_actuation.core.servo_validator import (
    ServoValidator,
    MIN_VEL_DPS,
    MAX_VEL_DPS,
    ValidationResult,
)


def _target(servo_id: int, pos: float, vel: float = 30.0) -> ServoTarget:
    return ServoTarget(servo_id, pos, vel)


class TestValidPosition:
    def test_in_range_position_passes(self):
        val = ServoValidator()
        result = val.validate([_target(SERVO_HEAD_PAN, 0.0)])
        assert result.valid is True
        assert len(result.errors) == 0
        assert abs(result.clamped_targets[0].position_deg) < 1e-6

    def test_at_exact_limit_passes(self):
        val = ServoValidator()
        # HEAD_PAN max = 90
        result = val.validate([_target(SERVO_HEAD_PAN, 90.0)])
        assert result.valid is True
        assert result.clamped_targets[0].position_deg == 90.0

    def test_multiple_valid_servos(self):
        val = ServoValidator()
        targets = [
            _target(SERVO_HEAD_PAN,    45.0),
            _target(SERVO_HEAD_TILT,   10.0),
            _target(SERVO_HEAD_ROLL,    5.0),
        ]
        result = val.validate(targets)
        assert result.valid is True
        assert len(result.clamped_targets) == 3

    def test_empty_list_is_valid(self):
        val = ServoValidator()
        result = val.validate([])
        assert result.valid is True
        assert result.clamped_targets == []


class TestPositionClamping:
    def test_above_max_clamped_to_max(self):
        val = ServoValidator()
        # HEAD_PAN max = 90
        result = val.validate([_target(SERVO_HEAD_PAN, 150.0)])
        assert result.valid is True  # clamped, not error
        assert result.clamped_targets[0].position_deg == 90.0
        assert len(result.warnings) > 0

    def test_below_min_clamped_to_min(self):
        val = ServoValidator()
        # HEAD_PAN min = -90
        result = val.validate([_target(SERVO_HEAD_PAN, -120.0)])
        assert result.clamped_targets[0].position_deg == -90.0

    def test_within_range_not_clamped(self):
        val = ServoValidator()
        result = val.validate([_target(SERVO_HEAD_TILT, 10.0)])
        assert abs(result.clamped_targets[0].position_deg - 10.0) < 1e-6
        assert len(result.warnings) == 0  # no warning needed


class TestVelocityClamping:
    def test_velocity_above_max_clamped(self):
        val = ServoValidator()
        result = val.validate([_target(SERVO_HEAD_PAN, 0.0, 999.0)])
        assert result.clamped_targets[0].velocity_dps == MAX_VEL_DPS
        assert len(result.warnings) > 0

    def test_velocity_below_min_clamped(self):
        val = ServoValidator()
        result = val.validate([_target(SERVO_HEAD_PAN, 0.0, 0.1)])
        assert result.clamped_targets[0].velocity_dps == MIN_VEL_DPS

    def test_valid_velocity_unchanged(self):
        val = ServoValidator()
        result = val.validate([_target(SERVO_HEAD_PAN, 0.0, 60.0)])
        assert abs(result.clamped_targets[0].velocity_dps - 60.0) < 1e-6
        assert not any("velocity" in w for w in result.warnings)


class TestUnknownServo:
    def test_unknown_servo_id_is_error(self):
        val = ServoValidator()
        result = val.validate([_target(99, 45.0)])
        assert result.valid is False
        assert len(result.errors) > 0
        assert len(result.clamped_targets) == 0  # discarded

    def test_unknown_mixed_with_valid(self):
        val = ServoValidator()
        result = val.validate([
            _target(99, 45.0),           # unknown
            _target(SERVO_HEAD_PAN, 0.0),  # valid
        ])
        assert result.valid is False
        assert len(result.clamped_targets) == 1  # valid one kept


class TestCustomLimits:
    def test_add_limit_affects_validation(self):
        val = ServoValidator()
        val.add_limit(servo_id=50, min_deg=0.0, max_deg=45.0)
        result = val.validate([_target(50, 30.0)])
        assert result.valid is True

    def test_add_limit_invalid_raises(self):
        val = ServoValidator()
        with pytest.raises(ValueError):
            val.add_limit(50, 90.0, 0.0)  # min >= max
