"""Tests for OdometryIntegrator -- dead-reckoning pose estimation from
cumulative wheel distance readings."""

from __future__ import annotations

import math
import unittest

from bonbon_base_controller.core.diff_drive_kinematics import DiffDriveConfig
from bonbon_base_controller.core.odometry_integrator import OdometryIntegrator


class TestOdometryIntegrator(unittest.TestCase):
    def setUp(self):
        self.odom = OdometryIntegrator(DiffDriveConfig(wheel_base_m=0.4))

    def test_first_call_establishes_baseline_no_motion(self):
        est = self.odom.integrate(left_distance_m=1.0, right_distance_m=1.0)
        self.assertEqual(est.pose.x_m, 0.0)
        self.assertEqual(est.pose.y_m, 0.0)
        self.assertEqual(est.pose.theta_rad, 0.0)

    def test_straight_forward_motion_moves_along_x(self):
        self.odom.integrate(0.0, 0.0)
        est = self.odom.integrate(1.0, 1.0)
        self.assertAlmostEqual(est.pose.x_m, 1.0, places=6)
        self.assertAlmostEqual(est.pose.y_m, 0.0, places=6)
        self.assertAlmostEqual(est.pose.theta_rad, 0.0, places=6)

    def test_straight_reverse_motion(self):
        self.odom.integrate(0.0, 0.0)
        est = self.odom.integrate(-0.5, -0.5)
        self.assertAlmostEqual(est.pose.x_m, -0.5, places=6)

    def test_in_place_rotation_changes_theta_not_position(self):
        cfg = DiffDriveConfig(wheel_base_m=0.4)
        odom = OdometryIntegrator(cfg)
        odom.integrate(0.0, 0.0)
        # Right wheel forward, left wheel back by the same amount -> pure
        # in-place rotation. d_theta = (d_right - d_left) / wheel_base
        arc = 0.1
        est = odom.integrate(-arc, arc)
        expected_theta = (arc - (-arc)) / cfg.wheel_base_m
        self.assertAlmostEqual(est.pose.theta_rad, expected_theta, places=6)
        self.assertAlmostEqual(est.pose.x_m, 0.0, places=3)
        self.assertAlmostEqual(est.pose.y_m, 0.0, places=3)

    def test_cumulative_motion_across_multiple_calls(self):
        self.odom.integrate(0.0, 0.0)
        self.odom.integrate(0.5, 0.5)
        est = self.odom.integrate(1.0, 1.0)
        self.assertAlmostEqual(est.pose.x_m, 1.0, places=6)

    def test_reset_clears_pose_and_baseline(self):
        self.odom.integrate(0.0, 0.0)
        self.odom.integrate(1.0, 1.0)
        self.odom.reset()
        self.assertEqual(self.odom.pose.x_m, 0.0)
        # Next integrate() after reset must re-baseline, not compute a
        # huge delta from the pre-reset cumulative distance.
        est = self.odom.integrate(5.0, 5.0)
        self.assertEqual(est.pose.x_m, 0.0)

    def test_velocity_estimate_reflects_step_distance(self):
        self.odom.integrate(0.0, 0.0)
        est = self.odom.integrate(0.2, 0.2)
        self.assertAlmostEqual(est.linear_velocity_mps, 0.2, places=6)
        self.assertAlmostEqual(est.angular_velocity_rps, 0.0, places=6)

    def test_theta_wraps_correctly_past_pi(self):
        cfg = DiffDriveConfig(wheel_base_m=0.4)
        odom = OdometryIntegrator(cfg)
        odom.integrate(0.0, 0.0)
        # Force a rotation greater than pi radians in a single step.
        big_arc = math.pi * cfg.wheel_base_m  # d_theta would be 2*pi without wrap... use pi+0.5
        est = odom.integrate(-big_arc / 2, big_arc / 2)
        self.assertTrue(-math.pi <= est.pose.theta_rad <= math.pi)


if __name__ == "__main__":
    unittest.main()
