"""bonbon_hardware_telemetry.core.battery_metrics -- exercises the
percent/voltage/current/staleness thresholds against the real 3S-LiPo
voltage-table-derived defaults from threshold_config.py."""

from __future__ import annotations

import unittest

from bonbon_hardware_telemetry.core.battery_metrics import battery_triggers, compute_battery_metrics
from bonbon_hardware_telemetry.core.threshold_config import ThresholdConfig


class TestBatteryMetrics(unittest.TestCase):
    def setUp(self):
        self.thresholds = ThresholdConfig.defaults()

    def test_healthy_battery_has_no_triggers(self):
        m = compute_battery_metrics(
            voltage_v=12.3,
            current_a=-1.5,
            percent=90.0,
            is_charging=False,
            age_sec=0.5,
            thresholds=self.thresholds,
        )
        self.assertEqual(battery_triggers(m), [])

    def test_low_percent_fires_warn(self):
        m = compute_battery_metrics(
            voltage_v=11.0,
            current_a=-1.0,
            percent=15.0,
            is_charging=False,
            age_sec=0.5,
            thresholds=self.thresholds,
        )
        codes = [t.code for t in battery_triggers(m)]
        self.assertIn("BATTERY_LOW", codes)
        self.assertNotIn("BATTERY_CRITICALLY_LOW", codes)

    def test_critical_percent_fires_error_not_warn(self):
        m = compute_battery_metrics(
            voltage_v=10.1,
            current_a=-1.0,
            percent=3.0,
            is_charging=False,
            age_sec=0.5,
            thresholds=self.thresholds,
        )
        codes = [t.code for t in battery_triggers(m)]
        self.assertIn("BATTERY_CRITICALLY_LOW", codes)
        self.assertNotIn("BATTERY_LOW", codes)

    def test_undervoltage_fires_independently_of_percent(self):
        m = compute_battery_metrics(
            voltage_v=10.0,
            current_a=-1.0,
            percent=50.0,
            is_charging=False,
            age_sec=0.5,
            thresholds=self.thresholds,
        )
        codes = [t.code for t in battery_triggers(m)]
        self.assertIn("BATTERY_UNDERVOLTAGE", codes)

    def test_overcurrent_uses_magnitude_regardless_of_sign(self):
        m = compute_battery_metrics(
            voltage_v=12.0,
            current_a=-19.0,
            percent=80.0,
            is_charging=False,
            age_sec=0.5,
            thresholds=self.thresholds,
        )
        self.assertTrue(m.overcurrent)
        self.assertIn("BATTERY_OVERCURRENT", [t.code for t in battery_triggers(m)])

    def test_high_current_while_charging_is_not_overcurrent(self):
        m = compute_battery_metrics(
            voltage_v=12.0,
            current_a=19.0,
            percent=80.0,
            is_charging=True,
            age_sec=0.5,
            thresholds=self.thresholds,
        )
        self.assertFalse(m.overcurrent)

    def test_stale_topic_fires_warn(self):
        stale_age = self.thresholds.liveness.stale_after_sec + 1.0
        m = compute_battery_metrics(
            voltage_v=12.0,
            current_a=0.0,
            percent=80.0,
            is_charging=False,
            age_sec=stale_age,
            thresholds=self.thresholds,
        )
        self.assertIn("BATTERY_STATE_STALE", [t.code for t in battery_triggers(m)])


if __name__ == "__main__":
    unittest.main()
