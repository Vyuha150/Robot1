"""bonbon_hardware_telemetry.core.pi_metrics -- confirms per-Pi
cpu/memory/disk pressure never fires a fault_manager-style trigger
(already actioned by resource_guard/DegradedModeManager elsewhere) while
monitor-degraded and snapshot-staleness genuinely do."""

from __future__ import annotations

import unittest

from bonbon_hardware_telemetry.core.pi_metrics import (
    compute_pi_resource_metrics,
    pi_resource_triggers,
)
from bonbon_hardware_telemetry.core.threshold_config import ThresholdConfig


class TestPiResourceMetrics(unittest.TestCase):
    def setUp(self):
        self.thresholds = ThresholdConfig.defaults()

    def test_idle_pi_has_no_triggers(self):
        m = compute_pi_resource_metrics(
            "ai_interaction_pi",
            10.0,
            20.0,
            512.0,
            80.0,
            available=True,
            age_sec=0.1,
            thresholds=self.thresholds,
        )
        self.assertEqual(pi_resource_triggers(m), [])

    def test_overloaded_cpu_sets_flags_but_fires_no_trigger(self):
        # Deliberate: cpu/mem/disk pressure is already actioned by
        # resource_guard/LoadSheddingController on the same thresholds --
        # this module must not duplicate that pipeline.
        m = compute_pi_resource_metrics(
            "ai_interaction_pi",
            95.0,
            90.0,
            512.0,
            5.0,
            available=True,
            age_sec=0.1,
            thresholds=self.thresholds,
        )
        self.assertTrue(m.cpu_overloaded)
        self.assertTrue(m.memory_pressure)
        self.assertTrue(m.disk_low)
        self.assertEqual(pi_resource_triggers(m), [])

    def test_degraded_monitor_fires_info_not_error(self):
        m = compute_pi_resource_metrics(
            "navigation_safety_pi",
            0.0,
            0.0,
            0.0,
            100.0,
            available=False,
            age_sec=0.1,
            thresholds=self.thresholds,
        )
        triggers = pi_resource_triggers(m)
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0].code, "PI_RESOURCE_MONITOR_DEGRADED")
        from bonbon_hardware_telemetry.core.trigger import Severity

        self.assertEqual(triggers[0].severity, Severity.INFO)

    def test_stale_snapshot_fires_warn(self):
        stale_age = self.thresholds.pi_resources.heartbeat_stale_after_sec + 1.0
        m = compute_pi_resource_metrics(
            "ui_supervisor_pi",
            10.0,
            20.0,
            512.0,
            80.0,
            available=True,
            age_sec=stale_age,
            thresholds=self.thresholds,
        )
        codes = [t.code for t in pi_resource_triggers(m)]
        self.assertIn("PI_RESOURCE_SNAPSHOT_STALE", codes)


if __name__ == "__main__":
    unittest.main()
