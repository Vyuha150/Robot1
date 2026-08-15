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


class TestNetworkQualityThresholds(unittest.TestCase):
    def test_defaults_construct_without_a_file(self):
        from bonbon_distributed_network_monitor.core.network_thresholds import (
            NetworkQualityThresholds,
        )

        cfg = NetworkQualityThresholds.defaults()
        self.assertGreater(cfg.rtt_alert_ms, cfg.rtt_warn_ms)
        self.assertGreater(cfg.packet_loss_alert_pct, cfg.packet_loss_warn_pct)

    def test_load_missing_file_falls_back_to_defaults(self):
        from bonbon_distributed_network_monitor.core.network_thresholds import (
            NetworkQualityThresholds,
        )

        cfg = NetworkQualityThresholds.load("/nonexistent/path/robot_network.yaml")
        self.assertEqual(cfg, NetworkQualityThresholds.defaults())

    def test_checked_in_file_matches_documented_values(self):
        from bonbon_distributed_network_monitor.core.network_thresholds import (
            NetworkQualityThresholds,
        )

        self.assertTrue(ROBOT_NETWORK_CONFIG_PATH.exists(), f"missing {ROBOT_NETWORK_CONFIG_PATH}")
        cfg = NetworkQualityThresholds.load(ROBOT_NETWORK_CONFIG_PATH)
        self.assertEqual(cfg.probe_port, 22)
        self.assertEqual(cfg.rtt_warn_ms, 50.0)
        self.assertEqual(cfg.rtt_alert_ms, 200.0)
        self.assertEqual(cfg.packet_loss_warn_pct, 10.0)
        self.assertEqual(cfg.packet_loss_alert_pct, 30.0)


class TestLoadPeerTargets(unittest.TestCase):
    def test_missing_file_returns_empty_list(self):
        from bonbon_distributed_network_monitor.core.network_thresholds import load_peer_targets

        self.assertEqual(load_peer_targets("ui_api", "/nonexistent/path.yaml"), [])

    def test_checked_in_file_excludes_self_by_role(self):
        from bonbon_distributed_network_monitor.core.network_thresholds import load_peer_targets

        targets = load_peer_targets("ui_api", ROBOT_NETWORK_CONFIG_PATH)
        roles = {t.role for t in targets}
        self.assertNotIn("ui_api", roles)
        self.assertEqual(roles, {"human_ai", "navigation_safety"})

    def test_checked_in_file_excludes_self_by_yaml_key(self):
        from bonbon_distributed_network_monitor.core.network_thresholds import load_peer_targets

        targets = load_peer_targets("pi2", ROBOT_NETWORK_CONFIG_PATH)
        roles = {t.role for t in targets}
        self.assertNotIn("human_ai", roles)
        self.assertEqual(roles, {"ui_api", "navigation_safety"})

    def test_hostnames_are_populated(self):
        from bonbon_distributed_network_monitor.core.network_thresholds import load_peer_targets

        targets = load_peer_targets("ui_api", ROBOT_NETWORK_CONFIG_PATH)
        hostnames = {t.hostname for t in targets}
        self.assertEqual(hostnames, {"bonbon-pi2", "bonbon-pi3"})


if __name__ == "__main__":
    unittest.main()
