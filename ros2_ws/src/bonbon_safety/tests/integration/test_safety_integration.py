"""
test_safety_integration.py
===========================
ROS2 launch_testing integration tests for the BonBon safety subsystem.

What is tested
--------------
1. All three safety nodes (supervisor, watchdog, estop) launch without error.
2. The supervisor publishes /bonbon/safety/state within 5 s of startup.
3. The safety state starts in INITIALIZING and transitions to NORMAL once
   the startup timeout fires (or fake sensor data is injected).
4. The /bonbon/safety/reset service exists and responds.
5. The estop node publishes /bonbon/estop/state.
6. The watchdog publishes /bonbon/safety/watchdog_node/health.

Prerequisites
-------------
- ROS2 Humble sourced
- bonbon_safety, bonbon_msgs, bonbon_srvs built and on the path
- Run with:
    colcon test --packages-select bonbon_safety
  or:
    ros2 run launch_testing launch_test \\
        bonbon_safety/tests/integration/test_safety_integration.py
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
from std_msgs.msg import Bool

# Mark this module for launch_testing auto-discovery
pytestmark = pytest.mark.launch_test


# ── Launch description ─────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def launch_description():
    """Bring up all 3 safety nodes in simulation mode."""
    os.environ["BONBON_SIMULATION"] = "1"

    from ament_index_python.packages import get_package_share_directory

    pkg = get_package_share_directory("bonbon_safety")
    params_file = os.path.join(pkg, "config", "safety_params.yaml")

    supervisor = launch_ros.actions.LifecycleNode(
        package="bonbon_safety",
        executable="safety_supervisor_node",
        name="safety_supervisor_node",
        namespace="/bonbon",
        parameters=[params_file, {"startup_timeout_sec": 3.0}],
        output="screen",
    )
    watchdog = launch_ros.actions.LifecycleNode(
        package="bonbon_safety",
        executable="watchdog_node",
        name="watchdog_node",
        namespace="/bonbon",
        parameters=[params_file],
        output="screen",
    )
    estop = launch_ros.actions.LifecycleNode(
        package="bonbon_safety",
        executable="estop_node",
        name="estop_node",
        namespace="/bonbon",
        parameters=[params_file],
        output="screen",
    )

    return launch.LaunchDescription(
        [
            supervisor,
            watchdog,
            estop,
            launch_testing.actions.ReadyToTest(),
        ]
    )


def generate_launch_description():
    return launch_description()


# ── Test class ────────────────────────────────────────────────────────────────


@launch_testing.markers.keep_alive
class TestSafetyIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        rclpy.init()
        cls.node = rclpy.create_node("safety_integration_test_node")

    @classmethod
    def tearDownClass(cls):
        cls.node.destroy_node()
        rclpy.shutdown()

    # ── Helper ────────────────────────────────────────────────────────────────

    def _wait_for_message(self, topic, msg_type, timeout_sec=10.0):
        """Block until one message arrives on topic or timeout expires."""
        received = []
        sub = self.node.create_subscription(msg_type, topic, lambda m: received.append(m), 10)
        deadline = time.monotonic() + timeout_sec
        while not received and time.monotonic() < deadline:
            rclpy.spin_once(self.node, timeout_sec=0.1)
        self.node.destroy_subscription(sub)
        return received[0] if received else None

    # ── Tests ─────────────────────────────────────────────────────────────────

    def test_safety_state_published(self):
        """Supervisor must publish /bonbon/safety/state within 10 s."""
        try:
            from bonbon_msgs.msg import SafetyState
        except ImportError:
            self.skipTest("bonbon_msgs not available")

        msg = self._wait_for_message("/bonbon/safety/state", SafetyState)
        self.assertIsNotNone(msg, "/bonbon/safety/state not published within timeout")
        # State should be INITIALIZING (0) or NORMAL (1) at startup
        self.assertIn(
            msg.state,
            [SafetyState.INITIALIZING, SafetyState.NORMAL],
            f"Unexpected initial state: {msg.state}",
        )

    def test_estop_state_published(self):
        """E-stop node must publish /bonbon/estop/state (Bool)."""
        msg = self._wait_for_message("/bonbon/estop/state", Bool)
        self.assertIsNotNone(msg, "/bonbon/estop/state not published within timeout")
        # In simulation, MockGPIO returns HIGH (not pressed)
        self.assertFalse(msg.data, "MockGPIO should report e-stop NOT pressed")

    def test_watchdog_health_published(self):
        """Watchdog must publish its own health topic."""
        try:
            from bonbon_msgs.msg import ModuleHealth
        except ImportError:
            self.skipTest("bonbon_msgs not available")

        msg = self._wait_for_message("/bonbon/safety/watchdog_node/health", ModuleHealth)
        self.assertIsNotNone(msg, "Watchdog health not published within timeout")
        self.assertEqual(msg.module_name, "watchdog_node")

    def test_safety_reset_service_exists(self):
        """The /bonbon/safety/reset service must be advertised."""
        try:
            from bonbon_srvs.srv import SafetyReset
        except ImportError:
            self.skipTest("bonbon_srvs not available")

        client = self.node.create_client(SafetyReset, "/bonbon/safety/reset")
        ready = client.wait_for_service(timeout_sec=10.0)
        self.node.destroy_client(client)
        self.assertTrue(ready, "/bonbon/safety/reset service not available")

    def test_supervisor_transitions_from_initializing(self):
        """
        After startup_timeout_sec (3 s in test config) the supervisor should
        transition out of INITIALIZING, either to NORMAL or FAULT.
        """
        try:
            from bonbon_msgs.msg import SafetyState
        except ImportError:
            self.skipTest("bonbon_msgs not available")

        # Wait long enough for startup timeout to fire
        time.sleep(4.0)
        msg = self._wait_for_message("/bonbon/safety/state", SafetyState, timeout_sec=5.0)
        self.assertIsNotNone(msg)
        self.assertNotEqual(
            msg.state,
            SafetyState.INITIALIZING,
            "Supervisor still INITIALIZING after startup_timeout_sec",
        )

    def test_critical_crash_flag_published(self):
        """Watchdog must publish /bonbon/safety/critical_node_crashed (Bool)."""
        msg = self._wait_for_message("/bonbon/safety/critical_node_crashed", Bool, timeout_sec=15.0)
        self.assertIsNotNone(msg, "critical_node_crashed flag not published")
