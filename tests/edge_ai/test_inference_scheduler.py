"""Edge AI Runtime brief Phase 13 -- bonbon_edge_ai_runtime.inference_scheduler.
Covers rule 1 ("safety and movement must never wait for AI") enforced
structurally -- a safety-critical module's task bypasses the queue
entirely -- plus bounded-queue drop-oldest behavior and reading the
real config/pi_efficiency_profile.yaml priority_order/queue_limits."""

from __future__ import annotations

import unittest

from bonbon_edge_ai_runtime.inference_scheduler import InferenceScheduler, SchedulerConfig


class TestSchedulerConfigLoadsRealProfile(unittest.TestCase):
    def test_loads_real_pi_efficiency_profile_priority_order(self):
        config = SchedulerConfig.load()
        self.assertTrue(config.priority, "config/pi_efficiency_profile.yaml priority_order is empty")

    def test_unknown_module_sorts_last_and_is_never_assumed_safety_critical(self):
        config = SchedulerConfig.load()
        self.assertEqual(config.rank_for("totally_unknown_module_xyz"), 999)
        self.assertFalse(config.is_safety_critical("totally_unknown_module_xyz"))


class TestSafetyCriticalBypassesQueue(unittest.TestCase):
    def setUp(self):
        # A minimal, self-contained config rather than the real (large,
        # environment-dependent) profile, so bypass behavior is asserted
        # against known priorities, not whatever real modules happen to
        # currently be marked safety_critical.
        from bonbon_edge_ai_runtime.inference_scheduler import ModulePriority

        self.config = SchedulerConfig(
            priority={
                "safety_supervisor": ModulePriority(rank=1, safety_critical=True),
                "ai_pi_speech": ModulePriority(rank=10, safety_critical=False),
            },
            queue_limits={"ai_pi_speech": 2},
        )
        self.scheduler = InferenceScheduler(self.config)

    def test_safety_critical_module_dispatches_immediately_never_queued(self):
        result = self.scheduler.submit("safety_supervisor", "task-1")
        self.assertTrue(result.dispatched)
        self.assertEqual(self.scheduler.queue_depth("safety_supervisor"), 0)

    def test_non_safety_critical_module_is_queued_not_dispatched(self):
        result = self.scheduler.submit("ai_pi_speech", "task-1")
        self.assertFalse(result.dispatched)
        self.assertEqual(self.scheduler.queue_depth("ai_pi_speech"), 1)

    def test_bounded_queue_drops_oldest_non_critical_request(self):
        self.scheduler.submit("ai_pi_speech", "task-a")
        self.scheduler.submit("ai_pi_speech", "task-b")
        self.scheduler.submit("ai_pi_speech", "task-c")  # limit is 2 -- must drop "task-a"
        self.assertEqual(self.scheduler.queue_depth("ai_pi_speech"), 2)
        next_task = self.scheduler.next_ready("ai_pi_speech")
        self.assertEqual(next_task.task_id, "task-b")

    def test_expired_queued_task_is_dropped_not_dispatched_stale(self):
        import time

        self.scheduler.submit("ai_pi_speech", "task-old", timeout_sec=1.0)
        result = self.scheduler.next_ready("ai_pi_speech", now=time.monotonic() + 100.0)  # far past the 1s timeout
        self.assertIsNone(result)

    def test_status_reports_priority_order_safety_critical_first(self):
        status = self.scheduler.status()
        self.assertEqual(status["priorityOrder"][0], "safety_supervisor")


if __name__ == "__main__":
    unittest.main()
