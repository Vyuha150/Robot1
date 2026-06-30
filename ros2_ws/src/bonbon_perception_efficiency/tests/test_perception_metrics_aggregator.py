"""Tests for PerceptionMetricsAggregator."""

from __future__ import annotations

from bonbon_perception_efficiency.core.perception_metrics_aggregator import (
    ModuleMetricSample,
    PerceptionMetricsAggregator,
)

_OK, _WARN, _ERROR, _STALE = 0, 1, 2, 3


def _sample(name, status=_OK, latency_ms=5.0, errors=0, processed=100):
    return ModuleMetricSample(name, status, latency_ms, errors, processed)


class TestEmptyAggregator:
    def test_empty_snapshot_has_zero_modules(self):
        agg = PerceptionMetricsAggregator()
        snap = agg.snapshot()
        assert snap.module_count == 0
        assert snap.worst_status == _OK


class TestAggregation:
    def test_single_module_reflected_directly(self):
        agg = PerceptionMetricsAggregator()
        agg.record(_sample("vision", latency_ms=12.0, errors=1, processed=50))
        snap = agg.snapshot()
        assert snap.module_count == 1
        assert snap.avg_latency_ms == 12.0
        assert snap.total_errors == 1
        assert snap.total_processed == 50

    def test_multiple_modules_averaged_and_summed(self):
        agg = PerceptionMetricsAggregator()
        agg.record(_sample("vision", latency_ms=10.0, errors=1, processed=100))
        agg.record(_sample("gesture", latency_ms=20.0, errors=2, processed=200))
        snap = agg.snapshot()
        assert snap.module_count == 2
        assert snap.avg_latency_ms == 15.0
        assert snap.max_latency_ms == 20.0
        assert snap.total_errors == 3
        assert snap.total_processed == 300

    def test_recording_same_module_again_replaces_not_accumulates(self):
        agg = PerceptionMetricsAggregator()
        agg.record(_sample("vision", processed=100))
        agg.record(_sample("vision", processed=150))
        snap = agg.snapshot()
        assert snap.module_count == 1
        assert snap.total_processed == 150


class TestWorstStatusWins:
    def test_stale_outranks_error_warn_ok(self):
        agg = PerceptionMetricsAggregator()
        agg.record(_sample("a", status=_OK))
        agg.record(_sample("b", status=_WARN))
        agg.record(_sample("c", status=_ERROR))
        agg.record(_sample("d", status=_STALE))
        snap = agg.snapshot()
        assert snap.worst_status == _STALE
        assert snap.worst_status_module == "d"

    def test_error_outranks_warn_when_no_stale(self):
        agg = PerceptionMetricsAggregator()
        agg.record(_sample("a", status=_OK))
        agg.record(_sample("b", status=_WARN))
        agg.record(_sample("c", status=_ERROR))
        snap = agg.snapshot()
        assert snap.worst_status == _ERROR

    def test_all_ok_reports_ok(self):
        agg = PerceptionMetricsAggregator()
        agg.record(_sample("a", status=_OK))
        agg.record(_sample("b", status=_OK))
        snap = agg.snapshot()
        assert snap.worst_status == _OK


class TestForget:
    def test_forget_removes_module_from_aggregation(self):
        agg = PerceptionMetricsAggregator()
        agg.record(_sample("vision"))
        agg.forget("vision")
        snap = agg.snapshot()
        assert snap.module_count == 0
