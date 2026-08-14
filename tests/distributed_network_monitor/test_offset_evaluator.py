"""bonbon_distributed_network_monitor.core.offset_evaluator -- exercises
the trigger tiers (unavailable / not-synchronised / elevated / alert)
against the real threshold defaults."""

from __future__ import annotations

import unittest

from bonbon_distributed_network_monitor.core.chrony_offset import (
    ChronyTrackingResult,
    unavailable_result,
)
from bonbon_distributed_network_monitor.core.network_thresholds import TimeSyncThresholds
from bonbon_distributed_network_monitor.core.offset_evaluator import (
    compute_offset_metrics,
    offset_triggers,
)


def _synced(offset_ms: float) -> ChronyTrackingResult:
    return ChronyTrackingResult(
        parsed=True, synchronised=True, offset_ms=offset_ms, leap_status="Normal"
    )


class TestOffsetEvaluator(unittest.TestCase):
    def setUp(self):
        self.thresholds = TimeSyncThresholds.defaults()

    def test_healthy_offset_has_no_triggers(self):
        m = compute_offset_metrics("pi2", _synced(5.0), self.thresholds)
        self.assertFalse(m.max_offset_exceeded)
        self.assertFalse(m.alert_offset_exceeded)
        self.assertEqual(offset_triggers(m), [])

    def test_offset_between_max_and_alert_fires_warn(self):
        offset = (self.thresholds.max_offset_ms + self.thresholds.alert_offset_ms) / 2.0
        m = compute_offset_metrics("pi2", _synced(offset), self.thresholds)
        self.assertTrue(m.max_offset_exceeded)
        self.assertFalse(m.alert_offset_exceeded)
        triggers = offset_triggers(m)
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0].code, "CLOCK_OFFSET_ELEVATED")

    def test_offset_above_alert_threshold_fires_error(self):
        offset = self.thresholds.alert_offset_ms + 10.0
        m = compute_offset_metrics("pi3", _synced(offset), self.thresholds)
        triggers = offset_triggers(m)
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0].code, "CLOCK_OFFSET_ALERT")
        from bonbon_distributed_network_monitor.core.trigger import Severity

        self.assertEqual(triggers[0].severity, Severity.ERROR)

    def test_negative_offset_uses_magnitude(self):
        offset = -(self.thresholds.alert_offset_ms + 10.0)
        m = compute_offset_metrics("pi1", _synced(offset), self.thresholds)
        self.assertTrue(m.alert_offset_exceeded)

    def test_not_synchronised_fires_warn_not_a_fabricated_zero_offset(self):
        result = ChronyTrackingResult(
            parsed=True, synchronised=False, offset_ms=None, leap_status="Not synchronised"
        )
        m = compute_offset_metrics("pi2", result, self.thresholds)
        self.assertFalse(m.max_offset_exceeded)
        self.assertFalse(m.alert_offset_exceeded)
        triggers = offset_triggers(m)
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0].code, "CLOCK_NOT_SYNCHRONISED")

    def test_chronyc_unavailable_fires_warn(self):
        m = compute_offset_metrics("pi3", unavailable_result("not installed"), self.thresholds)
        triggers = offset_triggers(m)
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0].code, "CHRONY_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
