"""bonbon_hardware_telemetry.core.threshold_config -- verifies the
checked-in config/hardware_telemetry/thresholds.yaml loads, that its
values match its own defaults (the yaml documents the same numbers the
dataclasses already default to -- this test catches the two drifting
apart), and that the values are consistent with the real modules they're
required to mirror (ResourceSnapshot's cpu/memory/disk properties,
HeartbeatConfig's stale_after_sec, the battery driver's voltage table)."""

from __future__ import annotations

import unittest
from pathlib import Path

THRESHOLDS_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "hardware_telemetry" / "thresholds.yaml"
)


class TestThresholdConfigDefaults(unittest.TestCase):
    def test_defaults_construct_without_a_file(self):
        from bonbon_hardware_telemetry.core.threshold_config import ThresholdConfig

        cfg = ThresholdConfig.defaults()
        self.assertGreater(cfg.liveness.stale_after_sec, 0)
        self.assertGreater(cfg.battery.percent_warn, cfg.battery.percent_error)
        self.assertGreater(cfg.battery.voltage_warn_v, cfg.battery.voltage_error_v)
        self.assertGreater(
            cfg.pi_resources.cpu_overloaded_percent, cfg.pi_resources.cpu_elevated_percent
        )

    def test_load_missing_file_falls_back_to_defaults(self):
        from bonbon_hardware_telemetry.core.threshold_config import ThresholdConfig

        cfg = ThresholdConfig.load("/nonexistent/path/thresholds.yaml")
        self.assertEqual(cfg, ThresholdConfig.defaults())


class TestThresholdsYamlFile(unittest.TestCase):
    def setUp(self):
        from bonbon_hardware_telemetry.core.threshold_config import ThresholdConfig

        self.assertTrue(THRESHOLDS_PATH.exists(), f"missing {THRESHOLDS_PATH}")
        self.cfg = ThresholdConfig.load(THRESHOLDS_PATH)
        self.defaults = ThresholdConfig.defaults()

    def test_checked_in_file_matches_dataclass_defaults(self):
        self.assertEqual(self.cfg, self.defaults)

    def test_pi_resource_thresholds_mirror_resource_monitor(self):
        from bonbon_safety.core.resource_monitor import ResourceSnapshot

        cpu_snapshot = ResourceSnapshot(
            cpu_percent=self.cfg.pi_resources.cpu_overloaded_percent,
            memory_percent=0.0,
            memory_mb=0.0,
            disk_free_percent=100.0,
            available=True,
        )
        self.assertTrue(cpu_snapshot.cpu_overloaded)

        mem_snapshot = ResourceSnapshot(
            cpu_percent=0.0,
            memory_percent=self.cfg.pi_resources.memory_pressure_percent,
            memory_mb=0.0,
            disk_free_percent=100.0,
            available=True,
        )
        self.assertTrue(mem_snapshot.memory_pressure)

        disk_snapshot = ResourceSnapshot(
            cpu_percent=0.0,
            memory_percent=0.0,
            memory_mb=0.0,
            disk_free_percent=self.cfg.pi_resources.disk_low_percent,
            available=True,
        )
        self.assertTrue(disk_snapshot.disk_low)

    def test_heartbeat_threshold_mirrors_distributed_safety(self):
        self.assertEqual(self.cfg.pi_resources.heartbeat_stale_after_sec, 1.5)

    def test_battery_thresholds_land_on_voltage_table_rows(self):
        from bonbon_hal.drivers.battery.battery_driver import voltage_to_percent

        self.assertAlmostEqual(
            voltage_to_percent(self.cfg.battery.voltage_warn_v),
            self.cfg.battery.percent_warn,
            delta=0.5,
        )
        self.assertAlmostEqual(
            voltage_to_percent(self.cfg.battery.voltage_error_v),
            self.cfg.battery.percent_error,
            delta=0.5,
        )


if __name__ == "__main__":
    unittest.main()
