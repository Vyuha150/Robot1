"""Unit tests for bonbon_actuation.core.motion_queue.MotionQueue."""

from __future__ import annotations

from bonbon_actuation.core.motion_queue import MotionQueue


class TestEnqueueDequeueOrdering:
    def test_empty_queue_returns_none(self):
        q = MotionQueue()
        assert q.dequeue() is None
        assert q.is_empty()

    def test_fifo_within_equal_priority(self):
        q = MotionQueue()
        q.enqueue("wave", priority=5, event_id="a")
        q.enqueue("nod_yes", priority=5, event_id="b")
        q.enqueue("shake_no", priority=5, event_id="c")
        assert q.dequeue().event_id == "a"
        assert q.dequeue().event_id == "b"
        assert q.dequeue().event_id == "c"

    def test_higher_priority_first(self):
        q = MotionQueue()
        q.enqueue("idle_scan", priority=0, event_id="low")
        q.enqueue("stop_gesture", priority=20, event_id="emerg")
        q.enqueue("wave", priority=5, event_id="mid")
        assert q.dequeue().event_id == "emerg"
        assert q.dequeue().event_id == "mid"
        assert q.dequeue().event_id == "low"

    def test_depth_tracks_pending(self):
        q = MotionQueue()
        assert q.depth() == 0
        q.enqueue("wave", priority=5)
        q.enqueue("nod_yes", priority=5)
        assert q.depth() == 2
        q.dequeue()
        assert q.depth() == 1


class TestBoundedQueue:
    def test_eviction_when_full(self):
        q = MotionQueue(max_depth=2)
        q.enqueue("a", priority=1, event_id="a")
        q.enqueue("b", priority=1, event_id="b")
        # Third, higher-priority entry should evict the lowest-priority one.
        admitted = q.enqueue("c", priority=5, event_id="c")
        assert admitted is True
        assert q.depth() == 2
        assert q.total_evicted == 1
        # The high-priority entry survives and comes out first.
        assert q.dequeue().event_id == "c"

    def test_lowest_priority_newcomer_rejected_when_full(self):
        q = MotionQueue(max_depth=2)
        q.enqueue("a", priority=5, event_id="a")
        q.enqueue("b", priority=5, event_id="b")
        # A brand-new lowest-priority request loses to the existing higher ones.
        admitted = q.enqueue("c", priority=0, event_id="c")
        assert admitted is False
        assert q.depth() == 2

    def test_clear_discards_all(self):
        q = MotionQueue()
        q.enqueue("a", priority=1)
        q.enqueue("b", priority=1)
        assert q.clear() == 2
        assert q.is_empty()


class TestPreemption:
    def test_emergency_always_preempts(self):
        q = MotionQueue(preempt_threshold=10)
        q.enqueue("stop_gesture", priority=20)
        assert q.should_preempt(running_priority=15) is True

    def test_higher_priority_preempts(self):
        q = MotionQueue(preempt_threshold=10)
        q.enqueue("wave", priority=8)
        assert q.should_preempt(running_priority=5) is True

    def test_lower_priority_does_not_preempt(self):
        q = MotionQueue(preempt_threshold=10)
        q.enqueue("idle_scan", priority=2)
        assert q.should_preempt(running_priority=5) is False

    def test_no_preempt_when_empty(self):
        q = MotionQueue()
        assert q.should_preempt(running_priority=0) is False


class TestTelemetry:
    def test_counters_increment(self):
        q = MotionQueue()
        q.enqueue("a", priority=1)
        q.enqueue("b", priority=1)
        q.dequeue()
        assert q.total_enqueued == 2
        assert q.total_dequeued == 1
