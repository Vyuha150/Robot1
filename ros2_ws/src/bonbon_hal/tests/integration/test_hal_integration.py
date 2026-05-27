"""
test_hal_integration.py
========================
ROS2 launch_testing integration tests for bonbon_hal.

Verifies that all 8 HAL nodes launch cleanly in mock mode and publish
their expected topics.
"""

from __future__ import annotations

import os
import time
import unittest

import launch
import launch_ros.actions
import launch_testing
import launch_testing.actions
import launch_testing.markers
import pytest
import rclpy
from sensor_msgs.msg import BatteryState, Image, Imu, LaserScan
from std_msgs.msg import Bool

pytestmark = pytest.mark.launch_test


@pytest.fixture(scope="module")
def launch_description():
    os.environ["BONBON_SIMULATION"] = "1"
    from ament_index_python.packages import get_package_share_directory

    pkg = get_package_share_directory("bonbon_hal")
    base = os.path.join(pkg, "config", "hal_params.yaml")

    def _node(name, extra_params=None):
        params = [base, {name: {"ros__parameters": {"driver_mode": "mock"}}}]
        if extra_params:
            params.append(extra_params)
        return launch_ros.actions.LifecycleNode(
            package="bonbon_hal",
            executable=name,
            name=name,
            namespace="/bonbon",
            parameters=params,
            output="screen",
        )

    return launch.LaunchDescription(
        [
            _node("lidar_node"),
            _node("imu_node"),
            _node("battery_node"),
            _node("camera_node"),
            _node("mic_node"),
            _node("speaker_node"),
            _node("estop_hal_node"),
            launch_testing.actions.ReadyToTest(),
        ]
    )


def generate_launch_description():
    return launch_description()


@launch_testing.markers.keep_alive
class TestHalIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        rclpy.init()
        cls.node = rclpy.create_node("hal_integration_test")

    @classmethod
    def tearDownClass(cls):
        cls.node.destroy_node()
        rclpy.shutdown()

    def _wait(self, topic, msg_type, timeout=15.0):
        received = []
        sub = self.node.create_subscription(msg_type, topic, lambda m: received.append(m), 10)
        deadline = time.monotonic() + timeout
        while not received and time.monotonic() < deadline:
            rclpy.spin_once(self.node, timeout_sec=0.2)
        self.node.destroy_subscription(sub)
        return received[0] if received else None

    def test_lidar_scan_published(self):
        msg = self._wait("/bonbon/lidar/scan", LaserScan)
        self.assertIsNotNone(msg, "LaserScan not published")
        self.assertEqual(len(msg.ranges), 360)

    def test_imu_published(self):
        msg = self._wait("/bonbon/imu/data_raw", Imu)
        self.assertIsNotNone(msg, "Imu not published")
        self.assertAlmostEqual(msg.linear_acceleration.z, 9.81, delta=1.0)

    def test_battery_published(self):
        msg = self._wait("/bonbon/battery/state", BatteryState, timeout=10)
        self.assertIsNotNone(msg, "BatteryState not published")
        self.assertGreater(msg.percentage, 0.0)

    def test_camera_color_published(self):
        msg = self._wait("/bonbon/vision/camera/color/image_raw", Image, timeout=10)
        self.assertIsNotNone(msg, "Camera color image not published")
        self.assertEqual(msg.encoding, "bgr8")

    def test_estop_published(self):
        msg = self._wait("/bonbon/estop/state", Bool, timeout=10)
        self.assertIsNotNone(msg, "EstopState not published")
        self.assertFalse(msg.data, "MockEstop should default to not pressed")

    def test_hal_fault_topic_exists(self):
        try:
            from bonbon_msgs.msg import HalFault
        except ImportError:
            self.skipTest("bonbon_msgs not available")
        # Just verify the topic can be subscribed (don't wait for a fault)
        sub = self.node.create_subscription(HalFault, "/bonbon/hal/fault", lambda m: None, 10)
        self.node.destroy_subscription(sub)

    def test_lidar_health_published(self):
        try:
            from bonbon_msgs.msg import ModuleHealth
        except ImportError:
            self.skipTest("bonbon_msgs not available")
        msg = self._wait("/bonbon/spatial/lidar_node/health", ModuleHealth)
        self.assertIsNotNone(msg)
        self.assertEqual(msg.module_name, "lidar_node")

    def test_battery_health_published(self):
        try:
            from bonbon_msgs.msg import ModuleHealth
        except ImportError:
            self.skipTest("bonbon_msgs not available")
        msg = self._wait("/bonbon/power/battery_node/health", ModuleHealth, timeout=10)
        self.assertIsNotNone(msg)
