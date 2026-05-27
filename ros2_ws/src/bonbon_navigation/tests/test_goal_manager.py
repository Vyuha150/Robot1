"""
Tests for bonbon_navigation.core.goal_manager
"""

import time

import pytest
from bonbon_navigation.core.goal_manager import (
    RESULT_STUCK,
    RESULT_SUCCESS,
    GoalManager,
    GoalState,
    NavigationGoalEntry,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _enqueue(
    gm: GoalManager,
    goal_id: str = "",
    priority: int = 1,
    timeout_sec: float = 60.0,
    x: float = 1.0,
    y: float = 1.0,
    yaw: float = 0.0,
    preempt: bool = False,
) -> str:
    return gm.enqueue(
        target_x=x,
        target_y=y,
        target_yaw=yaw,
        priority=priority,
        timeout_sec=timeout_sec,
        goal_id=goal_id or None,
        preempt=preempt,
    )


# ── Basic enqueue / activate ──────────────────────────────────────────────────


class TestEnqueueActivate:
    def test_enqueue_returns_goal_id(self):
        gm = GoalManager()
        gid = _enqueue(gm, "g1")
        assert gid == "g1"

    def test_activate_next_pops_from_queue(self):
        gm = GoalManager()
        _enqueue(gm, "g1")
        active = gm.activate_next()
        assert active is not None
        assert active.goal_id == "g1"
        assert active.state == GoalState.ACTIVE

    def test_activate_returns_none_when_empty(self):
        gm = GoalManager()
        assert gm.activate_next() is None

    def test_no_double_activate(self):
        """Cannot activate while another goal is active."""
        gm = GoalManager()
        _enqueue(gm, "g1")
        _enqueue(gm, "g2")
        first = gm.activate_next()
        second = gm.activate_next()
        assert first is not None
        assert second is None  # g1 still active

    def test_queue_size(self):
        gm = GoalManager()
        for i in range(3):
            _enqueue(gm, f"g{i}")
        assert gm.queue_size() == 3

    def test_get_active_property(self):
        gm = GoalManager()
        assert gm.get_active() is None
        _enqueue(gm, "g1")
        gm.activate_next()
        assert gm.get_active() is not None
        assert gm.get_active().goal_id == "g1"


# ── Priority ordering ─────────────────────────────────────────────────────────


class TestPriorityOrdering:
    def test_higher_priority_first(self):
        gm = GoalManager()
        _enqueue(gm, "low", priority=0)
        _enqueue(gm, "high", priority=3)
        active = gm.activate_next()
        assert active.goal_id == "high"

    def test_fifo_within_same_priority(self):
        gm = GoalManager()
        _enqueue(gm, "first", priority=2)
        _enqueue(gm, "second", priority=2)
        g1 = gm.activate_next()
        gm.mark_succeeded("first")
        g2 = gm.activate_next()
        assert g1.goal_id == "first"
        assert g2.goal_id == "second"

    def test_priority_0_last(self):
        gm = GoalManager()
        _enqueue(gm, "p0", priority=0)
        _enqueue(gm, "p1", priority=1)
        _enqueue(gm, "p2", priority=2)
        order = []
        for _ in range(3):
            g = gm.activate_next()
            order.append(g.goal_id)
            gm.mark_succeeded(g.goal_id)
        assert order == ["p2", "p1", "p0"]


# ── Preemption ────────────────────────────────────────────────────────────────


class TestPreemption:
    def test_preempt_cancels_active_and_clears_queue(self):
        gm = GoalManager()
        _enqueue(gm, "running", priority=1)
        gm.activate_next()
        _enqueue(gm, "urgent", priority=3, preempt=True)
        # After preempt, running is cancelled; queue has only "urgent"
        assert gm.get_active() is None  # preempt cancelled active
        urgent = gm.activate_next()
        assert urgent is not None
        assert urgent.goal_id == "urgent"

    def test_no_preempt_keeps_running(self):
        gm = GoalManager()
        _enqueue(gm, "running", priority=1)
        gm.activate_next()
        _enqueue(gm, "queued", priority=3)
        # No preempt — active goal stays
        assert gm.get_active().goal_id == "running"


# ── Queue capacity ────────────────────────────────────────────────────────────


class TestQueueCapacity:
    def test_max_queue_size_respected(self):
        gm = GoalManager(max_queue_size=3)
        for i in range(5):
            _enqueue(gm, f"g{i}")
        assert gm.queue_size() <= 3

    def test_lowest_priority_dropped_when_full(self):
        gm = GoalManager(max_queue_size=2)
        _enqueue(gm, "low", priority=0)
        _enqueue(gm, "med", priority=1)
        _enqueue(gm, "high", priority=3)  # should drop "low"
        ids_in_queue = [e.goal_id for e in list(gm._queue)]
        assert "low" not in ids_in_queue


# ── Completion / cancellation ─────────────────────────────────────────────────


class TestCompletion:
    def test_mark_succeeded(self):
        gm = GoalManager()
        _enqueue(gm, "g1")
        gm.activate_next()
        gm.mark_succeeded("g1")
        assert gm.get_active() is None
        history = gm.get_history()
        assert len(history) == 1
        assert history[-1].state == GoalState.SUCCEEDED
        assert history[-1].result_code == RESULT_SUCCESS

    def test_mark_failed_with_reason(self):
        gm = GoalManager()
        _enqueue(gm, "g1")
        gm.activate_next()
        gm.mark_failed("g1", result_code=RESULT_STUCK, message="robot stuck")
        assert gm.get_active() is None
        history = gm.get_history()
        assert history[-1].state == GoalState.FAILED
        assert history[-1].result_code == RESULT_STUCK

    def test_cancel_active_goal(self):
        gm = GoalManager()
        _enqueue(gm, "g1")
        gm.activate_next()
        cancelled_count = gm.cancel_goal("g1", reason="user request")
        assert cancelled_count == 1
        assert gm.get_active() is None

    def test_cancel_queued_goal(self):
        gm = GoalManager()
        _enqueue(gm, "g1")
        _enqueue(gm, "g2")
        cancelled_count = gm.cancel_goal("g2", reason="user")
        assert cancelled_count == 1
        assert gm.queue_size() == 1

    def test_cancel_nonexistent_goal_returns_zero(self):
        gm = GoalManager()
        assert gm.cancel_goal("no_such_goal") == 0

    def test_history_capped_at_50(self):
        gm = GoalManager()
        for i in range(60):
            _enqueue(gm, f"g{i}")
            gm.activate_next()
            gm.mark_succeeded(f"g{i}")
        assert len(gm.get_history(100)) <= 50


# ── Timeout ───────────────────────────────────────────────────────────────────


class TestTimeout:
    def test_timed_out_goal_detected(self):
        gm = GoalManager()
        _enqueue(gm, "g1", timeout_sec=0.05)
        gm.activate_next()
        time.sleep(0.1)
        timed_out_goal = gm.check_timeout()
        assert timed_out_goal is not None
        assert timed_out_goal.goal_id == "g1"

    def test_no_timeout_for_recent_goal(self):
        gm = GoalManager()
        _enqueue(gm, "g1", timeout_sec=60.0)
        gm.activate_next()
        assert gm.check_timeout() is None

    def test_timed_out_property_on_entry(self):
        entry = NavigationGoalEntry(
            goal_id="t1",
            goal_type=0,
            target_x=0,
            target_y=0,
            target_yaw=0,
            priority=1,
            timeout_sec=0.01,
            start_time=time.monotonic() - 1.0,
        )
        assert entry.timed_out is True

    def test_entry_not_timed_out_when_no_start(self):
        entry = NavigationGoalEntry(
            goal_id="t2",
            goal_type=0,
            target_x=0,
            target_y=0,
            target_yaw=0,
            priority=1,
            timeout_sec=0.01,
            start_time=None,
        )
        assert entry.timed_out is False


# ── Plan failures ─────────────────────────────────────────────────────────────


class TestPlanFailures:
    def test_plan_failure_below_limit(self):
        gm = GoalManager(max_plan_failures=3)
        _enqueue(gm, "g1")
        gm.activate_next()
        assert gm.record_plan_failure("g1") is False
        assert gm.record_plan_failure("g1") is False

    def test_plan_failure_at_limit(self):
        gm = GoalManager(max_plan_failures=3)
        _enqueue(gm, "g1")
        gm.activate_next()
        at_limit = False
        for _ in range(3):
            at_limit = gm.record_plan_failure("g1")
        assert at_limit is True

    def test_plan_failure_wrong_id_returns_false(self):
        gm = GoalManager(max_plan_failures=3)
        _enqueue(gm, "g1")
        gm.activate_next()
        assert gm.record_plan_failure("wrong_id") is False


# ── Distance helper ───────────────────────────────────────────────────────────


class TestDistanceHelper:
    def test_distance_to_goal(self):
        entry = NavigationGoalEntry(
            goal_id="d1",
            goal_type=0,
            target_x=3.0,
            target_y=4.0,
            target_yaw=0,
            priority=1,
        )
        dist = entry.distance_to(0.0, 0.0)
        assert abs(dist - 5.0) < 1e-9

    def test_distance_at_goal(self):
        entry = NavigationGoalEntry(
            goal_id="d1",
            goal_type=0,
            target_x=1.0,
            target_y=2.0,
            target_yaw=0,
            priority=1,
        )
        assert entry.distance_to(1.0, 2.0) == pytest.approx(0.0)


# ── Cancel all ────────────────────────────────────────────────────────────────


class TestCancelAll:
    def test_cancel_all_returns_count(self):
        gm = GoalManager()
        _enqueue(gm, "g1")
        _enqueue(gm, "g2")
        _enqueue(gm, "g3")
        gm.activate_next()  # g1 active, g2+g3 queued
        count = gm.cancel_goal(reason="shutdown")
        assert count == 3  # 1 active + 2 queued

    def test_cancel_all_clears_state(self):
        gm = GoalManager()
        _enqueue(gm, "g1")
        _enqueue(gm, "g2")
        gm.activate_next()
        gm.cancel_goal()
        assert gm.get_active() is None
        assert gm.queue_size() == 0
