"""bonbon_distributed_network_monitor.nodes.network_monitor_node --
_run_chronyc_tracking() lives at module level outside the rclpy-guarded
main(), so it's directly testable without a ROS2 environment. The
NetworkMonitorNode class itself is not importable here (needs rclpy);
it's syntax-checked via py_compile only, matching every other rclpy
node in this repo's established convention."""

from __future__ import annotations

import unittest

from bonbon_distributed_network_monitor.nodes.network_monitor_node import _run_chronyc_tracking


class TestRunChronycTracking(unittest.TestCase):
    def test_missing_chronyc_binary_returns_none_not_a_fabricated_reading(self):
        # This dev sandbox genuinely has no chronyc installed -- real
        # FileNotFoundError path, not a mock.
        result = _run_chronyc_tracking(timeout_sec=2.0)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
