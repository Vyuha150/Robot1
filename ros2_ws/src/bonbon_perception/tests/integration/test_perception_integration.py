"""
test_perception_integration.py
================================
ROS2 launch_testing integration test for bonbon_perception.

Verifies that detection_node and face_node launch cleanly in mock mode
and publish their expected topics.
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
from bonbon_msgs.msg import ModuleHealth, PersonStateArray

pytestmark = pytest.mark.launch_test


@pytest.fixture(scope="module")
def launch_description():
    os.environ["BONBON_SIMULATION"] = "1"
    from ament_index_python.packages import get_package_share_directory

    pkg = get_package_share_directory("bonbon_perception")
    base = os.path.join(pkg, "config", "perception_params.yaml")

    def _node(name, extra=None):
        params = [base, {name: {"ros__parameters": {"detector_mode": "mock", "face_mode": "mock"}}}]
        if extra:
            params.append(extra)
        return launch_ros.actions.LifecycleNode(
            package="bonbon_perception",
            executable=name,
            name=name,
            namespace="/bonbon",
            parameters=params,
            output="screen",
        )

    return launch.LaunchDescription(
        [
            _node("detection_node"),
            _node("face_node"),
            launch_testing.actions.ReadyToTest(),
        ]
    )


def generate_launch_description():
    return launch_description()


@launch_testing.markers.keep_alive
class TestPerceptionIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        rclpy.init()
        cls.node = rclpy.create_node("perception_integration_test")

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

    def test_persons_topic_published(self):
        msg = self._wait("/bonbon/vision/persons", PersonStateArray)
        self.assertIsNotNone(msg, "/bonbon/vision/persons not published")

    def test_persons_identified_topic_published(self):
        msg = self._wait("/bonbon/vision/persons_identified", PersonStateArray)
        self.assertIsNotNone(msg, "/bonbon/vision/persons_identified not published")

    def test_detection_node_health_published(self):
        try:
            msg = self._wait("/bonbon/vision/detection_node/health", ModuleHealth, timeout=10)
            self.assertIsNotNone(msg, "Detection health not published")
            self.assertEqual(msg.module_name, "detection_node")
        except ImportError:
            self.skipTest("bonbon_msgs not available")

    def test_face_node_health_published(self):
        try:
            msg = self._wait("/bonbon/vision/face_node/health", ModuleHealth, timeout=10)
            self.assertIsNotNone(msg, "Face node health not published")
        except ImportError:
            self.skipTest("bonbon_msgs not available")
