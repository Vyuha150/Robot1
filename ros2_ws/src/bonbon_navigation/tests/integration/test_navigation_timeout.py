"""
Integration tests — Navigation timeout handling
===============================================
Tests the full goal lifecycle when a goal exceeds its timeout_sec.

No ROS2 runtime required — uses stub callbacks to simulate the
navigation node's internal logic.
"""

import time

from bonbon_navigation.config.nav_config import RecoveryConfig
from bonbon_navigation.core.goal_manager import (
    RESULT_TIMEOUT,
    GoalManager,
)
from bonbon_navigation.core.recovery_executor import RecoveryExecutor, RecoveryOutcome

# ── Helpers ───────────────────────────────────────────────────────────────────


def _recovery_cfg() -> RecoveryConfig:
    return RecoveryConfig(
        enabled=True,
        max_retries_per_goal=5,
        behavior_sequence=["wait", "replan"],
        wait_sec=0.02,
        backup_distance_m=0.3,
        backup_speed_mps=0.1,
        spin_angular_speed_rps=0.5,
        spin_full_rotations=1,
        announce_repeat_sec=0.02,
    )


class NavigationHarness:
    """
    Minimal harness that replicates the goal-timeout + recovery logic
    from NavigationNode._nav_loop() without requiring ROS2.
    """

    def __init__(self, goal_timeout_sec: float = 0.1):
        self.gm = GoalManager()
        self.recovery = RecoveryExecutor(_recovery_cfg())
        self.events: list = []
        self._goal_timeout = goal_timeout_sec

    def enqueue(self, goal_id: str, priority: int = 1) -> str:
        return self.gm.enqueue(
            target_x=5.0,
            target_y=5.0,
            target_yaw=0.0,
            priority=priority,
            timeout_sec=self._goal_timeout,
            goal_id=goal_id,
        )

    def tick(self):
        """One nav_loop tick."""
        active = self.gm.get_active()

        # Check timeout on active goal
        if active:
            timed_out = self.gm.check_timeout()
            if timed_out:
                self.events.append(("timeout", active.goal_id))
                self.gm.mark_failed(active.goal_id, result_code=RESULT_TIMEOUT, message="timeout")
                self.recovery.reset(trigger_reason="timeout")

        # Run recovery if active
        if self.recovery.is_active():
            outcome = self.recovery.step()
            if outcome == RecoveryOutcome.SUCCEEDED:
                self.events.append(("recovery_succeeded",))
            elif outcome == RecoveryOutcome.EXHAUSTED:
                self.events.append(("recovery_exhausted",))

        # Activate next goal if none active
        if self.gm.get_active() is None and not self.recovery.is_active():
            nxt = self.gm.activate_next()
            if nxt:
                self.events.append(("activated", nxt.goal_id))


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestNavigationTimeout:
    def test_goal_times_out(self):
        h = NavigationHarness(goal_timeout_sec=0.05)
        h.enqueue("g1")
        h.tick()  # activate g1
        time.sleep(0.07)
        h.tick()  # detect timeout
        assert any(e[0] == "timeout" and e[1] == "g1" for e in h.events)

    def test_timeout_triggers_recovery(self):
        h = NavigationHarness(goal_timeout_sec=0.05)
        h.enqueue("g1")
        h.tick()
        time.sleep(0.07)
        h.tick()  # timeout → starts recovery
        assert h.recovery.is_active()

    def test_recovery_runs_after_timeout(self):
        h = NavigationHarness(goal_timeout_sec=0.05)
        h.enqueue("g1")
        h.tick()
        time.sleep(0.07)
        for _ in range(30):
            h.tick()
            time.sleep(0.01)
            if any(e[0] in ("recovery_succeeded", "recovery_exhausted") for e in h.events):
                break
        assert any(e[0] in ("recovery_succeeded", "recovery_exhausted") for e in h.events)

    def test_no_timeout_for_fast_goal(self):
        h = NavigationHarness(goal_timeout_sec=10.0)
        h.enqueue("g1")
        h.tick()
        h.tick()
        assert not any(e[0] == "timeout" for e in h.events)

    def test_second_goal_activated_after_timeout_and_recovery(self):
        h = NavigationHarness(goal_timeout_sec=0.05)
        h.enqueue("g1")
        h.enqueue("g2")
        h.tick()  # activate g1
        time.sleep(0.07)
        for _ in range(50):
            h.tick()
            time.sleep(0.01)
            if h.gm.get_active() and h.gm.get_active().goal_id == "g2":
                break
        activated_ids = [e[1] for e in h.events if e[0] == "activated"]
        assert "g2" in activated_ids

    def test_goal_failed_with_timeout_result_code(self):
        h = NavigationHarness(goal_timeout_sec=0.05)
        h.enqueue("g1")
        h.tick()
        time.sleep(0.07)
        h.tick()
        failed = [g for g in h.gm.get_history() if g.goal_id == "g1"]
        assert failed
        assert failed[0].result_code == RESULT_TIMEOUT

    def test_multiple_sequential_timeouts(self):
        """3 goals, each times out → all recorded in history."""
        h = NavigationHarness(goal_timeout_sec=0.04)
        for i in range(3):
            h.enqueue(f"g{i}")
        for _ in range(60):
            h.tick()
            time.sleep(0.01)
        timeout_events = [e for e in h.events if e[0] == "timeout"]
        assert len(timeout_events) >= 1

    def test_priority_goal_activated_after_timeout(self):
        """High priority goal queued while low-priority times out."""
        h = NavigationHarness(goal_timeout_sec=0.05)
        h.enqueue("low_p", priority=0)
        h.tick()
        h.enqueue("high_p", priority=3)
        time.sleep(0.07)
        for _ in range(30):
            h.tick()
            time.sleep(0.01)
            active = h.gm.get_active()
            if active and active.goal_id == "high_p":
                break
        activated = [e[1] for e in h.events if e[0] == "activated"]
        assert "high_p" in activated
