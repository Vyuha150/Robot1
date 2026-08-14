"""bonbon_distributed_network_monitor.core.network_thresholds -- verifies
the checked-in config/distributed/robot_network.yaml's time_sync section
loads and matches the values that file's own header already promises
(max_offset_ms=50, alert_offset_ms=200, server=pi3)."""

from __future__ import annotations

import unittest
from pathlib import Path

ROBOT_NETWORK_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "distributed" / "robot_network.yaml"
)


class TestTimeSyncThresholds(unittest.TestCase):
    def test_defaults_construct_without_a_file(self):
        from bonbon_distributed_network_monitor.core.network_thresholds import TimeSyncThresholds

        cfg = TimeSyncThresholds.defaults()
        self.assertGreater(cfg.alert_offset_ms, cfg.max_offset_ms)

    def test_load_missing_file_falls_back_to_defaults(self):
        from bonbon_distributed_network_monitor.core.network_thresholds import TimeSyncThresholds

        cfg = TimeSyncThresholds.load("/nonexistent/path/robot_network.yaml")
        self.assertEqual(cfg, TimeSyncThresholds.defaults())

    def test_checked_in_file_matches_documented_values(self):
        from bonbon_distributed_network_monitor.core.network_thresholds import TimeSyncThresholds

        self.assertTrue(ROBOT_NETWORK_CONFIG_PATH.exists(), f"missing {ROBOT_NETWORK_CONFIG_PATH}")
        cfg = TimeSyncThresholds.load(ROBOT_NETWORK_CONFIG_PATH)
        self.assertEqual(cfg.max_offset_ms, 50.0)
        self.assertEqual(cfg.alert_offset_ms, 200.0)
        self.assertEqual(cfg.server, "pi3")


if __name__ == "__main__":
    unittest.main()
