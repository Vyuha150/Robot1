"""bonbon_hardware_telemetry.core.wheel_metrics -- open-loop wheel
telemetry has exactly one real trigger (topic staleness); this test
confirms fresh data never fires it and stale data always does, and that
no fault is fabricated from velocity/distance values alone."""

from __future__ import annotations

import unittest

from bonbon_hardware_telemetry.core.threshold_config import ThresholdConfig
from bonbon_hardware_telemetry.core.wheel_metrics import compute_wheel_metrics, wheel_triggers


class TestWheelMetrics(unittest.TestCase):
    def setUp(self):
        self.thresholds = ThresholdConfig.defaults()

    def test_fresh_data_is_not_stale_and_has_no_triggers(self):
        m = compute_wheel_metrics(0.5, 0.5, 1.2, 1.2, age_sec=0.1, thresholds=self.thresholds)
        self.assertFalse(m.stale)
        self.assertEqual(wheel_triggers(m), [])

    def test_stale_topic_fires_exactly_one_warn_trigger(self):
        stale_age = self.thresholds.liveness.stale_after_sec + 1.0
        m = compute_wheel_metrics(0.0, 0.0, 1.2, 1.2, age_sec=stale_age, thresholds=self.thresholds)
        self.assertTrue(m.stale)
        triggers = wheel_triggers(m)
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0].code, "WHEEL_STATE_STALE")

    def test_asymmetric_wheel_speeds_do_not_fabricate_a_trigger(self):
        # No feedback sensor exists to confirm a mismatch is a real fault --
        # this module must never infer one from velocity values alone.
        m = compute_wheel_metrics(1.0, -1.0, 1.2, 1.2, age_sec=0.1, thresholds=self.thresholds)
        self.assertEqual(wheel_triggers(m), [])


if __name__ == "__main__":
    unittest.main()
