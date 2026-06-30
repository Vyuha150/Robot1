"""Tests for ROS2DashboardBridge — the parts testable without a live rclpy
install (this dev/CI environment has no ROS2, so _ROS2_AVAILABLE is False
and self._running is always False; the bridge's real subscription/service-
client logic inside _DashboardNode requires a real ROS2 environment to
exercise and is not covered here — see PHASE2_BUILD_VALIDATION_REPORT.md).

What IS covered: the honest-failure contract for commands with no real
backend, and the not-ready short-circuit for commands that do have one.
Both are real behavior regardless of ROS2 availability.
"""

from __future__ import annotations

from bonbon_operator_api.ros2.ros2_bridge import _NOT_IMPLEMENTED, ROS2DashboardBridge
from bonbon_operator_api.ros2.status_aggregator import RobotStatusAggregator


def _bridge() -> ROS2DashboardBridge:
    return ROS2DashboardBridge(aggregator=RobotStatusAggregator())


class TestNotImplementedCommandsAreHonest:
    """These commands have no real backing service/topic anywhere in the
    codebase (verified by grep, documented in ros2_bridge.py's module
    docstring) -- they must report failure, never a fake success."""

    def test_emergency_stop_reports_failure_not_fake_success(self):
        result = _bridge().call_emergency_stop("test reason")
        assert result["success"] is False
        assert result["error"] == "NOT_IMPLEMENTED"
        assert "e-stop" in result["message"].lower()

    def test_pause_reports_failure(self):
        result = _bridge().call_pause()
        assert result["success"] is False

    def test_resume_reports_failure(self):
        result = _bridge().call_resume()
        assert result["success"] is False

    def test_restart_module_reports_failure(self):
        result = _bridge().call_restart_module("some_node")
        assert result["success"] is False

    def test_get_config_reports_failure(self):
        result = _bridge().call_get_config("some_key")
        assert result["success"] is False

    def test_set_config_reports_failure(self):
        result = _bridge().call_set_config("some_key", "some_value")
        assert result["success"] is False

    def test_memory_query_reports_failure(self):
        result = _bridge().call_memory_query("query", 5)
        assert result["success"] is False

    def test_rag_query_reports_failure(self):
        result = _bridge().call_rag_query("query", "collection", 5)
        assert result["success"] is False

    def test_every_not_implemented_entry_has_a_real_explanation(self):
        """Guards against a future stub being added with an empty/placeholder
        message -- every entry must explain WHY there's no real backend."""
        for name, message in _NOT_IMPLEMENTED.items():
            assert isinstance(message, str) and len(message) > 10, name


class TestRealTargetCommandsFailCleanlyWhenBridgeNotReady:
    """navigate/cancel_task/dock/speak DO have real ROS2 targets (verified),
    but this environment has no rclpy -- the bridge must report
    "not ready" honestly rather than crash or fake success."""

    def test_navigate_not_ready(self):
        result = _bridge().call_navigate(1.0, 1.0, None, None, None)
        assert result["success"] is False
        assert "not ready" in result["error"]

    def test_cancel_task_not_ready(self):
        result = _bridge().call_cancel_task(None)
        assert result["success"] is False

    def test_dock_not_ready(self):
        result = _bridge().call_dock(None)
        assert result["success"] is False

    def test_speak_not_ready(self):
        result = _bridge().call_speak("hello", "en", "normal")
        assert result["success"] is False


class TestBridgeLifecycleWithoutRos2:
    def test_start_does_not_raise_without_ros2(self):
        bridge = _bridge()
        bridge.start()  # must not raise even though rclpy is unavailable
        assert bridge._running is False

    def test_stop_does_not_raise_without_starting(self):
        bridge = _bridge()
        bridge.stop()  # must not raise
