"""Unit tests for bonbon_safety.core.perf_monitor."""

from __future__ import annotations

from bonbon_safety.core.perf_monitor import (
    LatencyTimer,
    LatencyTracker,
    PerfBudget,
    check_budget,
    percentile,
)


class _Clock:
    """Deterministic perf_counter-style clock advanced manually."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class TestPercentile:
    def test_empty_is_zero(self):
        assert percentile([], 95) == 0.0

    def test_extremes(self):
        s = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert percentile(s, 0) == 1.0
        assert percentile(s, 100) == 5.0

    def test_median(self):
        assert percentile([1, 2, 3, 4, 5], 50) == 3.0

    def test_p95_nearest_rank(self):
        s = list(range(1, 101))  # 1..100
        assert percentile(s, 95) == 95.0


class TestLatencyTracker:
    def test_records_and_counts(self):
        t = LatencyTracker("x", window=100)
        for v in (10, 20, 30):
            t.record_ms(v)
        st = t.stats()
        assert st.count == 3
        assert st.min_ms == 10 and st.max_ms == 30
        assert st.mean_ms == 20

    def test_window_bounded(self):
        t = LatencyTracker("x", window=3)
        for v in (1, 2, 3, 4, 5):
            t.record_ms(v)
        st = t.stats()
        assert st.count == 3              # only last 3 retained
        assert t.total_count == 5         # but lifetime count is exact
        assert st.min_ms == 3.0

    def test_seconds_helper(self):
        t = LatencyTracker("x")
        t.record_s(0.05)                  # 50 ms
        assert abs(t.stats().mean_ms - 50.0) < 1e-9

    def test_empty_stats(self):
        st = LatencyTracker("x").stats()
        assert st.count == 0 and st.p95_ms == 0.0


class TestLatencyTimer:
    def test_records_elapsed(self):
        clock = _Clock()
        t = LatencyTracker("x")
        with LatencyTimer(t, clock=clock) as timer:
            clock.t = 0.025               # 25 ms elapsed
        assert abs(timer.last_ms - 25.0) < 1e-6
        assert abs(t.stats().mean_ms - 25.0) < 1e-6

    def test_decorator_form(self):
        clock = _Clock()
        t = LatencyTracker("x")

        @LatencyTimer.wrap(t, clock=clock)
        def work():
            clock.t += 0.01              # 10 ms each call
            return "ok"

        assert work() == "ok"
        work()
        assert t.stats().count == 2

    def test_exception_still_records(self):
        clock = _Clock()
        t = LatencyTracker("x")
        try:
            with LatencyTimer(t, clock=clock):
                clock.t = 0.005
                raise ValueError("boom")
        except ValueError:
            pass
        assert t.stats().count == 1       # timing recorded despite exception


class TestBudget:
    def test_within_budget_passes(self):
        t = LatencyTracker("behavior_decision")
        for _ in range(20):
            t.record_ms(40.0)
        rep = check_budget(t, PerfBudget("behavior_decision", 100.0, "p95"))
        assert rep.passed is True
        assert rep.observed_ms <= 100.0

    def test_over_budget_fails(self):
        t = LatencyTracker("safety_validation")
        for _ in range(20):
            t.record_ms(80.0)
        rep = check_budget(t, PerfBudget("safety_validation", 50.0, "p95", critical=True))
        assert rep.passed is False
        assert rep.critical is True

    def test_empty_tracker_passes_vacuously(self):
        rep = check_budget(LatencyTracker("x"), PerfBudget("x", 50.0))
        assert rep.passed is True
        assert rep.samples == 0

    def test_p99_metric_selected(self):
        t = LatencyTracker("emergency_stop_reaction")
        for _ in range(95):
            t.record_ms(100.0)
        for _ in range(5):                # 5% slow tail → caught by p99
            t.record_ms(400.0)
        rep = check_budget(
            t, PerfBudget("emergency_stop_reaction", 300.0, "p99", critical=True)
        )
        # p99 picks up the slow tail → over the 300 ms budget.
        assert rep.observed_ms >= 300.0
        assert rep.passed is False
