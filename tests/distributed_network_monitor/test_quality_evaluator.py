"""bonbon_distributed_network_monitor.core.quality_evaluator -- 3-Pi Phase 7
remainder. Mirrors test_offset_evaluator.py's structure."""

from __future__ import annotations

import unittest


class TestComputeQualityMetrics(unittest.TestCase):
    def _thresholds(self):
        from bonbon_distributed_network_monitor.core.network_thresholds import (
            NetworkQualityThresholds,
        )

        return NetworkQualityThresholds(
            rtt_warn_ms=50.0,
            rtt_alert_ms=200.0,
            packet_loss_warn_pct=10.0,
            packet_loss_alert_pct=30.0,
        )

    def test_unreachable_peer_is_not_reachable(self):
        from bonbon_distributed_network_monitor.core.quality_evaluator import (
            compute_quality_metrics,
        )
        from bonbon_distributed_network_monitor.core.rtt_probe import ProbeResult

        result = ProbeResult(
            host="bonbon-pi2", port=22, attempts=5, successes=0, rtt_samples_ms=()
        )
        metrics = compute_quality_metrics("ui_api", "human_ai", result, self._thresholds())
        self.assertFalse(metrics.reachable)
        self.assertIsNone(metrics.avg_rtt_ms)

    def test_healthy_link_exceeds_no_threshold(self):
        from bonbon_distributed_network_monitor.core.quality_evaluator import (
            compute_quality_metrics,
        )
        from bonbon_distributed_network_monitor.core.rtt_probe import ProbeResult

        result = ProbeResult(
            host="bonbon-pi2", port=22, attempts=5, successes=5, rtt_samples_ms=(5.0,) * 5
        )
        metrics = compute_quality_metrics("ui_api", "human_ai", result, self._thresholds())
        self.assertTrue(metrics.reachable)
        self.assertFalse(metrics.rtt_warn_exceeded)
        self.assertFalse(metrics.loss_warn_exceeded)

    def test_elevated_rtt_sets_warn_not_alert(self):
        from bonbon_distributed_network_monitor.core.quality_evaluator import (
            compute_quality_metrics,
        )
        from bonbon_distributed_network_monitor.core.rtt_probe import ProbeResult

        result = ProbeResult(
            host="bonbon-pi2", port=22, attempts=5, successes=5, rtt_samples_ms=(80.0,) * 5
        )
        metrics = compute_quality_metrics("ui_api", "human_ai", result, self._thresholds())
        self.assertTrue(metrics.rtt_warn_exceeded)
        self.assertFalse(metrics.rtt_alert_exceeded)

    def test_severe_rtt_sets_alert(self):
        from bonbon_distributed_network_monitor.core.quality_evaluator import (
            compute_quality_metrics,
        )
        from bonbon_distributed_network_monitor.core.rtt_probe import ProbeResult

        result = ProbeResult(
            host="bonbon-pi2", port=22, attempts=5, successes=5, rtt_samples_ms=(300.0,) * 5
        )
        metrics = compute_quality_metrics("ui_api", "human_ai", result, self._thresholds())
        self.assertTrue(metrics.rtt_alert_exceeded)

    def test_partial_loss_computed_correctly(self):
        from bonbon_distributed_network_monitor.core.quality_evaluator import (
            compute_quality_metrics,
        )
        from bonbon_distributed_network_monitor.core.rtt_probe import ProbeResult

        result = ProbeResult(
            host="bonbon-pi2", port=22, attempts=10, successes=8, rtt_samples_ms=(10.0,) * 8
        )
        metrics = compute_quality_metrics("ui_api", "human_ai", result, self._thresholds())
        self.assertEqual(metrics.packet_loss_pct, 20.0)
        self.assertTrue(metrics.loss_warn_exceeded)
        self.assertFalse(metrics.loss_alert_exceeded)


class TestQualityTriggers(unittest.TestCase):
    def _metrics(self, **overrides):
        from bonbon_distributed_network_monitor.core.quality_evaluator import QualityMetrics

        defaults = dict(
            pi_role="ui_api",
            peer_role="human_ai",
            peer_host="bonbon-pi2",
            reachable=True,
            avg_rtt_ms=5.0,
            max_rtt_ms=6.0,
            packet_loss_pct=0.0,
            rtt_warn_exceeded=False,
            rtt_alert_exceeded=False,
            loss_warn_exceeded=False,
            loss_alert_exceeded=False,
        )
        defaults.update(overrides)
        return QualityMetrics(**defaults)

    def test_healthy_link_produces_no_triggers(self):
        from bonbon_distributed_network_monitor.core.quality_evaluator import quality_triggers

        self.assertEqual(quality_triggers(self._metrics()), [])

    def test_unreachable_produces_exactly_one_error_trigger(self):
        from bonbon_distributed_network_monitor.core.quality_evaluator import quality_triggers

        triggers = quality_triggers(self._metrics(reachable=False, avg_rtt_ms=None))
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0].code, "PEER_UNREACHABLE")

    def test_alert_loss_takes_priority_over_warn(self):
        from bonbon_distributed_network_monitor.core.quality_evaluator import quality_triggers

        triggers = quality_triggers(
            self._metrics(
                packet_loss_pct=50.0, loss_warn_exceeded=True, loss_alert_exceeded=True
            )
        )
        codes = [t.code for t in triggers]
        self.assertIn("PACKET_LOSS_ALERT", codes)
        self.assertNotIn("PACKET_LOSS_ELEVATED", codes)

    def test_rtt_and_loss_triggers_can_both_fire(self):
        from bonbon_distributed_network_monitor.core.quality_evaluator import quality_triggers

        triggers = quality_triggers(
            self._metrics(
                rtt_warn_exceeded=True,
                loss_warn_exceeded=True,
                avg_rtt_ms=80.0,
                packet_loss_pct=15.0,
            )
        )
        codes = {t.code for t in triggers}
        self.assertEqual(codes, {"PACKET_LOSS_ELEVATED", "RTT_ELEVATED"})


if __name__ == "__main__":
    unittest.main()
