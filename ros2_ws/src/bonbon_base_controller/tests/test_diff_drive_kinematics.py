"""Tests for DiffDriveKinematics -- Twist<->wheel-speed conversion, with
particular attention to the clamp-preserves-turn-ratio correctness
property (independently clamping each wheel would silently distort a
requested turn)."""

from __future__ import annotations

import unittest

from bonbon_base_controller.core.diff_drive_kinematics import (
    DiffDriveConfig,
    DiffDriveKinematics,
    Twist2D,
    WheelSpeeds,
)


class TestDiffDriveConfig(unittest.TestCase):
    def test_rejects_nonpositive_wheel_base(self):
        with self.assertRaises(ValueError):
            DiffDriveConfig(wheel_base_m=0.0)

    def test_rejects_nonpositive_max_speed(self):
        with self.assertRaises(ValueError):
            DiffDriveConfig(max_wheel_speed_mps=-1.0)


class TestTwistToWheelSpeeds(unittest.TestCase):
    def setUp(self):
        self.kin = DiffDriveKinematics(DiffDriveConfig(wheel_base_m=0.4, max_wheel_speed_mps=1.0))

    def test_pure_forward_both_wheels_equal(self):
        w = self.kin.twist_to_wheel_speeds(Twist2D(linear_x_mps=0.5, angular_z_rps=0.0))
        self.assertAlmostEqual(w.left_mps, 0.5)
        self.assertAlmostEqual(w.right_mps, 0.5)

    def test_pure_reverse_both_wheels_equal_negative(self):
        w = self.kin.twist_to_wheel_speeds(Twist2D(linear_x_mps=-0.3, angular_z_rps=0.0))
        self.assertAlmostEqual(w.left_mps, -0.3)
        self.assertAlmostEqual(w.right_mps, -0.3)

    def test_in_place_left_turn_opposite_signs(self):
        w = self.kin.twist_to_wheel_speeds(Twist2D(linear_x_mps=0.0, angular_z_rps=1.0))
        self.assertLess(w.left_mps, 0.0)
        self.assertGreater(w.right_mps, 0.0)
        self.assertAlmostEqual(w.left_mps, -w.right_mps)

    def test_in_place_right_turn_opposite_signs(self):
        w = self.kin.twist_to_wheel_speeds(Twist2D(linear_x_mps=0.0, angular_z_rps=-1.0))
        self.assertGreater(w.left_mps, 0.0)
        self.assertLess(w.right_mps, 0.0)

    def test_forward_arc_right_wheel_faster_when_turning_left(self):
        w = self.kin.twist_to_wheel_speeds(Twist2D(linear_x_mps=0.3, angular_z_rps=0.5))
        self.assertGreater(w.right_mps, w.left_mps)

    def test_clamping_preserves_turn_ratio(self):
        # Request a fast in-place turn that would exceed max_wheel_speed_mps
        # on both wheels equally -- both must scale down by the SAME
        # factor, keeping the ratio (and therefore the turning radius)
        # intact rather than independently clipping.
        fast_turn = Twist2D(linear_x_mps=0.0, angular_z_rps=10.0)
        w = self.kin.twist_to_wheel_speeds(fast_turn)
        self.assertLessEqual(abs(w.left_mps), 1.0 + 1e-9)
        self.assertLessEqual(abs(w.right_mps), 1.0 + 1e-9)
        self.assertAlmostEqual(w.left_mps, -w.right_mps)

    def test_clamping_preserves_arc_ratio(self):
        cfg = DiffDriveConfig(wheel_base_m=0.4, max_wheel_speed_mps=1.0)
        kin = DiffDriveKinematics(cfg)
        # Unclamped: left=0.3-1.0=-0.7, right=0.3+1.0=1.3 -> ratio right/left = -1.857...
        requested = Twist2D(linear_x_mps=0.3, angular_z_rps=5.0)
        unclamped_left = requested.linear_x_mps - requested.angular_z_rps * (cfg.wheel_base_m / 2)
        unclamped_right = requested.linear_x_mps + requested.angular_z_rps * (cfg.wheel_base_m / 2)
        expected_ratio = unclamped_right / unclamped_left

        w = kin.twist_to_wheel_speeds(requested)
        actual_ratio = w.right_mps / w.left_mps
        self.assertAlmostEqual(actual_ratio, expected_ratio, places=6)

    def test_within_limits_not_clamped(self):
        w = self.kin.twist_to_wheel_speeds(Twist2D(linear_x_mps=0.1, angular_z_rps=0.1))
        self.assertLess(abs(w.left_mps), 1.0)
        self.assertLess(abs(w.right_mps), 1.0)


class TestWheelSpeedsToTwist(unittest.TestCase):
    def setUp(self):
        self.kin = DiffDriveKinematics(DiffDriveConfig(wheel_base_m=0.4, max_wheel_speed_mps=1.0))

    def test_equal_wheel_speeds_pure_forward(self):
        t = self.kin.wheel_speeds_to_twist(WheelSpeeds(left_mps=0.5, right_mps=0.5))
        self.assertAlmostEqual(t.linear_x_mps, 0.5)
        self.assertAlmostEqual(t.angular_z_rps, 0.0)

    def test_opposite_wheel_speeds_pure_rotation(self):
        t = self.kin.wheel_speeds_to_twist(WheelSpeeds(left_mps=-0.5, right_mps=0.5))
        self.assertAlmostEqual(t.linear_x_mps, 0.0)
        self.assertGreater(t.angular_z_rps, 0.0)

    def test_roundtrip_within_speed_limits(self):
        original = Twist2D(linear_x_mps=0.2, angular_z_rps=0.3)
        wheels = self.kin.twist_to_wheel_speeds(original)
        recovered = self.kin.wheel_speeds_to_twist(wheels)
        self.assertAlmostEqual(recovered.linear_x_mps, original.linear_x_mps, places=6)
        self.assertAlmostEqual(recovered.angular_z_rps, original.angular_z_rps, places=6)


if __name__ == "__main__":
    unittest.main()
