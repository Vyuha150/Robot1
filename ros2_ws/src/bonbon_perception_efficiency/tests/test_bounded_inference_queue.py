"""Tests for BoundedInferenceQueue — backpressure for unguarded executor submission."""

from __future__ import annotations

from bonbon_perception_efficiency.core.bounded_inference_queue import BoundedInferenceQueue


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class TestAdmission:
    def test_admits_within_capacity(self):
        q = BoundedInferenceQueue(max_depth=2)
        r1 = q.try_admit("a")
        r2 = q.try_admit("b")
        assert r1.admitted is True
        assert r2.admitted is True
        assert q.depth == 2

    def test_rejects_beyond_capacity_drop_newest_by_default(self):
        q = BoundedInferenceQueue(max_depth=2)
        q.try_admit("a")
        q.try_admit("b")
        r3 = q.try_admit("c")
        assert r3.admitted is False
        assert q.depth == 2  # "a" and "b" still there, "c" rejected

    def test_drop_oldest_mode_evicts_to_make_room(self):
        q = BoundedInferenceQueue(max_depth=2, drop_oldest=True)
        q.try_admit("a")
        q.try_admit("b")
        r3 = q.try_admit("c")
        assert r3.admitted is True
        assert q.depth == 2  # "a" evicted, "b" and "c" remain

    def test_dropped_count_increments(self):
        q = BoundedInferenceQueue(max_depth=1)
        q.try_admit("a")
        q.try_admit("b")
        q.try_admit("c")
        assert q.dropped_count == 2


class TestCompletion:
    def test_mark_complete_frees_a_slot(self):
        q = BoundedInferenceQueue(max_depth=1)
        q.try_admit("a")
        assert q.is_full is True
        q.mark_complete("a")
        assert q.is_full is False
        r = q.try_admit("b")
        assert r.admitted is True

    def test_mark_complete_by_specific_token_removes_correct_item(self):
        q = BoundedInferenceQueue(max_depth=3)
        q.try_admit("a")
        q.try_admit("b")
        q.try_admit("c")
        q.mark_complete("b")
        assert q.depth == 2

    def test_mark_complete_on_empty_queue_is_safe(self):
        q = BoundedInferenceQueue(max_depth=2)
        q.mark_complete("nonexistent")  # must not raise
        assert q.depth == 0

    def test_mark_complete_unknown_token_falls_back_to_oldest(self):
        q = BoundedInferenceQueue(max_depth=2)
        q.try_admit("a")
        q.mark_complete("never_admitted")
        assert q.depth == 0


class TestOldestAge:
    def test_oldest_age_zero_when_empty(self):
        q = BoundedInferenceQueue(max_depth=2)
        assert q.oldest_age_sec() == 0.0

    def test_oldest_age_tracks_elapsed_time(self):
        clock = _Clock()
        q = BoundedInferenceQueue(max_depth=2, clock=clock)
        q.try_admit("a")
        clock.advance(3.0)
        assert abs(q.oldest_age_sec() - 3.0) < 1e-6
