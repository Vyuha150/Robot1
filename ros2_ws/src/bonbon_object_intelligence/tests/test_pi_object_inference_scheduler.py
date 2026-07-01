"""Tests for PiObjectInferenceScheduler -- stale-frame dropping and a
bounded processing queue that never grows unbounded."""

from __future__ import annotations

import unittest

from bonbon_object_intelligence.core.pi_object_inference_scheduler import (
    PiObjectInferenceScheduler,
    SchedulerConfig,
)


class TestPiObjectInferenceScheduler(unittest.TestCase):
    def test_first_frame_always_accepted(self):
        sched = PiObjectInferenceScheduler(SchedulerConfig(target_fps=10.0))
        decision = sched.offer(0.0)
        self.assertTrue(decision.accepted)

    def test_frame_faster_than_target_fps_is_dropped_as_stale(self):
        sched = PiObjectInferenceScheduler(SchedulerConfig(target_fps=10.0, drop_stale_frames=True))
        sched.offer(0.0)
        decision = sched.offer(0.01)  # 10ms later, target interval is 100ms
        self.assertFalse(decision.accepted)
        self.assertTrue(decision.dropped_stale)
        self.assertEqual(sched.stale_dropped_count, 1)

    def test_frame_at_or_after_target_interval_is_accepted(self):
        sched = PiObjectInferenceScheduler(SchedulerConfig(target_fps=10.0))
        sched.offer(0.0)
        decision = sched.offer(0.11)
        self.assertTrue(decision.accepted)

    def test_queue_never_exceeds_bounded_size(self):
        sched = PiObjectInferenceScheduler(SchedulerConfig(target_fps=1000.0, bounded_queue_size=2))
        for i in range(10):
            sched.offer(float(i))
        self.assertLessEqual(sched.queue_depth, 2)

    def test_queue_drops_oldest_not_newest_when_full(self):
        sched = PiObjectInferenceScheduler(SchedulerConfig(target_fps=1000.0, bounded_queue_size=2))
        sched.offer(1.0)
        sched.offer(2.0)
        sched.offer(3.0)
        self.assertEqual(list(sched._queue), [2.0, 3.0])

    def test_mark_done_removes_from_queue(self):
        sched = PiObjectInferenceScheduler(SchedulerConfig(target_fps=1000.0, bounded_queue_size=5))
        sched.offer(1.0)
        self.assertEqual(sched.queue_depth, 1)
        sched.mark_done(1.0)
        self.assertEqual(sched.queue_depth, 0)


if __name__ == "__main__":
    unittest.main()
