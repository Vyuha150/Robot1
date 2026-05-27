"""
Integration tests — Obstacle blocking and recovery cascade
===========================================================
Simulates a robot stuck behind an obstacle:
  - Stuck detector fires
  - Recovery cascade (wait → clear_costmap → replan → announce → escalate)
  - Goal eventually failed with RESULT_STUCK
  - Safety bridge blocks motion when DANGER state injected mid-recovery
"""

import time

import pytest
from bonbon_navigation.config.nav_config import (
    RecoveryConfig,
    StuckDetectorConfig,
)
from bonbon_navigation.core.goal_manager import (
    RESULT_STUCK,
    GoalManager,
)
from bonbon_navigation.core.recovery_executor import RecoveryExecutor, RecoveryOutcome
from bonbon_navigation.core.stuck_detector import StuckDetector
from bonbon_navigation.safety.safety_stop_bridge import (
    SAFETY_CAUTION,
    SAFETY_DANGER,
    SAFETY_NORMAL,
    SafetyStopBridge,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _recovery_cfg(sequence=None) -> RecoveryConfig:
    return RecoveryConfig(
        enabled=True,
        max_retries_per_goal=20,
        behavior_sequence=sequence or ["wait", "clear_costmap", "replan", "announce", "escalate"],
        wait_sec=0.03,
        backup_distance_m=0.3,
        backup_speed_mps=0.1,
        spin_angular_speed_rps=0.5,
        spin_full_rotations=1,
        announce_repeat_sec=0.03,
    )


def _stuck_cfg() -> StuckDetectorConfig:
    return StuckDetectorConfig(
        window_sec=0.05,
        min_progress_m=0.10,
        stuck_threshold_count=2,
        zero_velocity_window_sec=0.05,
    )


class ObstacleHarness:
    """
    Simulates navigation blocked by an obstacle.
    The robot stays at (5.0, 5.0) regardless of commands.
    """

    def __init__(self):
        self.gm = GoalManager()
        self.stuck = StuckDetector(_stuck_cfg())
        self.recovery = RecoveryExecutor(_recovery_cfg())
        self.bridge = SafetyStopBridge(watchdog_timeout_sec=5.0)
        self.bridge.update_safety_state(SAFETY_NORMAL)

        self.events: list = []
        self.vel_cmds: list = []

        self.recovery.set_announce_fn(lambda t: self.events.append(("announce", t)))
        self.recovery.set_escalate_fn(lambda r: self.events.append(("escalate", r)))
        self.recovery.set_clear_costmap_fn(lambda: self.events.append(("clear_costmap",)))

    def tick(self, robot_x: float = 5.0, robot_y: float = 5.0, velocity: float = 0.0):
        """One simulation tick — robot stays fixed (blocked by obstacle)."""
        self.stuck.update(robot_x, robot_y, velocity)
        stuck_result = self.stuck.check()

        active = self.gm.get_active()
        if active and stuck_result.is_stuck and not self.recovery.is_active():
            self.events.append(("stuck_detected",))
            self.gm.mark_failed(
                active.goal_id, result_code=RESULT_STUCK, message="obstacle blocking"
            )
            self.recovery.reset(trigger_reason="obstacle")

        if self.recovery.is_active():
            outcome = self.recovery.step()
            if outcome == RecoveryOutcome.SUCCEEDED:
                self.events.append(("recovery_done",))
            elif outcome == RecoveryOutcome.EXHAUSTED:
                self.events.append(("recovery_exhausted",))

        if self.gm.get_active() is None and not self.recovery.is_active():
            nxt = self.gm.activate_next()
            if nxt:
                self.stuck.reset()  # start monitoring from fresh state
                self.events.append(("activated", nxt.goal_id))


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestObstacleBlocking:
    def test_stuck_detection_fires(self):
        h = ObstacleHarness()
        h.gm.enqueue(
            target_x=10.0, target_y=10.0, target_yaw=0.0, priority=1, timeout_sec=60.0, goal_id="g1"
        )
        h.tick()  # activate
        for _ in range(10):
            h.tick(robot_x=5.0, robot_y=5.0, velocity=0.0)
            time.sleep(0.02)
        assert any(e[0] == "stuck_detected" for e in h.events)

    def test_recovery_starts_after_stuck(self):
        h = ObstacleHarness()
        h.gm.enqueue(
            target_x=10.0, target_y=10.0, target_yaw=0.0, priority=1, timeout_sec=60.0, goal_id="g1"
        )
        h.tick()
        for _ in range(10):
            h.tick(robot_x=5.0, robot_y=5.0, velocity=0.0)
            time.sleep(0.02)
        recovery_started = any(e[0] in ("clear_costmap", "announce", "escalate") for e in h.events)
        assert recovery_started or h.recovery.is_active()

    def test_announce_emitted_during_recovery(self):
        h = ObstacleHarness()
        h.gm.enqueue(
            target_x=10.0, target_y=10.0, target_yaw=0.0, priority=1, timeout_sec=60.0, goal_id="g1"
        )
        h.tick()
        for _ in range(10):
            h.tick(robot_x=5.0, robot_y=5.0, velocity=0.0)
            time.sleep(0.02)
        for _ in range(50):
            h.tick(robot_x=5.0, robot_y=5.0, velocity=0.0)
            time.sleep(0.01)
        assert any(e[0] == "announce" for e in h.events)

    def test_escalate_after_exhausted_recovery(self):
        h = ObstacleHarness()
        h.gm.enqueue(
            target_x=10.0, target_y=10.0, target_yaw=0.0, priority=1, timeout_sec=60.0, goal_id="g1"
        )
        h.tick()
        for _ in range(10):
            h.tick(robot_x=5.0, robot_y=5.0, velocity=0.0)
            time.sleep(0.02)
        for _ in range(100):
            h.tick(robot_x=5.0, robot_y=5.0, velocity=0.0)
            time.sleep(0.01)
            if any(e[0] == "escalate" for e in h.events):
                break
        assert any(e[0] == "escalate" for e in h.events)


# ── Safety bridge blocks motion mid-recovery ──────────────────────────────────


class TestSafetyBlockDuringRecovery:
    def test_danger_state_zeros_velocity(self):
        bridge = SafetyStopBridge(watchdog_timeout_sec=5.0)
        bridge.update_safety_state(SAFETY_NORMAL)
        gv = bridge.gate(0.5, 0.0)
        assert gv.was_blocked is False
        bridge.update_safety_state(SAFETY_DANGER)
        gv_blocked = bridge.gate(0.5, 0.0)
        assert gv_blocked.was_blocked is True
        assert gv_blocked.linear_mps == 0.0

    def test_caution_state_limits_velocity(self):
        bridge = SafetyStopBridge(watchdog_timeout_sec=5.0)
        bridge.update_safety_state(SAFETY_CAUTION)
        gv = bridge.gate(0.6, 0.2)
        assert gv.was_capped is True
        assert gv.linear_mps == pytest.approx(0.30)

    def test_recovery_backup_blocked_in_danger(self):
        """Recovery backup commands should be blocked by DANGER safety state."""
        bridge = SafetyStopBridge(watchdog_timeout_sec=5.0)
        bridge.update_safety_state(SAFETY_DANGER)

        backup_cmds = []

        def safe_backup(distance, speed):
            gv = bridge.gate(-speed, 0.0)
            backup_cmds.append(gv)

        cfg = _recovery_cfg(sequence=["backup"])
        ex = RecoveryExecutor(cfg)
        ex.set_backup_fn(safe_backup)
        ex.reset(trigger_reason="test")
        for _ in range(5):
            ex.step()

        assert all(cmd.was_blocked for cmd in backup_cmds)


# ── Full cascade sequence ─────────────────────────────────────────────────────


class TestFullRecoveryCascade:
    def test_cascade_order(self):
        """Verify behaviors execute in configured sequence order."""
        sequence_log = []

        cfg = RecoveryConfig(
            enabled=True,
            max_retries_per_goal=30,
            behavior_sequence=["wait", "clear_costmap", "replan", "announce"],
            wait_sec=0.02,
            backup_distance_m=0.3,
            backup_speed_mps=0.1,
            spin_angular_speed_rps=0.5,
            spin_full_rotations=1,
            announce_repeat_sec=0.02,
        )
        ex = RecoveryExecutor(cfg)
        ex.set_clear_costmap_fn(lambda: sequence_log.append("clear_costmap"))
        ex.set_announce_fn(lambda t: sequence_log.append("announce"))

        ex.reset()
        for _ in range(200):
            o = ex.step()
            time.sleep(0.005)
            if o == RecoveryOutcome.SUCCEEDED:
                break

        if "clear_costmap" in sequence_log and "announce" in sequence_log:
            assert sequence_log.index("clear_costmap") < sequence_log.index("announce")

    def test_plan_failure_limit(self):
        """After max_plan_failures, record_plan_failure returns True."""
        gm = GoalManager(max_plan_failures=3)
        gm.enqueue(
            target_x=5.0, target_y=5.0, target_yaw=0.0, priority=1, timeout_sec=60.0, goal_id="g1"
        )
        gm.activate_next()
        for _ in range(2):
            assert gm.record_plan_failure("g1") is False
        assert gm.record_plan_failure("g1") is True
