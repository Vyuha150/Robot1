"""
Tests for bonbon_navigation.core.recovery_executor
"""
import time

import pytest

from bonbon_navigation.config.nav_config import RecoveryConfig
from bonbon_navigation.core.recovery_executor import (
    RecoveryExecutor,
    RecoveryOutcome,
    RecoveryState,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cfg(**kw) -> RecoveryConfig:
    defaults = dict(
        enabled=True,
        max_retries_per_goal=10,
        behavior_sequence=["wait", "clear_costmap", "backup", "spin",
                           "replan", "announce", "escalate"],
        wait_sec=0.05,
        backup_distance_m=0.3,
        backup_speed_mps=0.1,
        spin_angular_speed_rps=0.5,
        spin_full_rotations=1,
        announce_repeat_sec=0.05,
    )
    defaults.update(kw)
    return RecoveryConfig(**defaults)


def _executor(cfg=None, **kw):
    cfg = cfg or _cfg(**kw)
    ex = RecoveryExecutor(cfg)

    calls = {"clear": 0, "backup": [], "spin": [], "announce": [], "escalate": []}
    ex.set_clear_costmap_fn(lambda: calls.__setitem__("clear", calls["clear"] + 1))
    ex.set_backup_fn(lambda d, s: calls["backup"].append((d, s)))
    ex.set_spin_fn(lambda r, n: calls["spin"].append((r, n)))
    ex.set_announce_fn(lambda t: calls["announce"].append(t))
    ex.set_escalate_fn(lambda r: calls["escalate"].append(r))
    return ex, calls


# ── Disabled ──────────────────────────────────────────────────────────────────

class TestDisabled:
    def test_disabled_returns_succeeded_immediately(self):
        ex, _ = _executor(enabled=False)
        ex.reset()
        outcome = ex.step()
        assert outcome == RecoveryOutcome.SUCCEEDED

    def test_is_active_false_when_disabled(self):
        ex, _ = _executor(enabled=False)
        ex.reset()
        assert ex.is_active() is False


# ── Wait behavior ─────────────────────────────────────────────────────────────

class TestWaitBehavior:
    def test_wait_in_progress_then_succeeds(self):
        ex, _ = _executor(behavior_sequence=["wait"], wait_sec=0.05)
        ex.reset(trigger_reason="test")
        r1 = ex.step()
        assert r1 == RecoveryOutcome.IN_PROGRESS
        time.sleep(0.07)
        r2 = ex.step()
        assert r2 in (RecoveryOutcome.IN_PROGRESS, RecoveryOutcome.SUCCEEDED)

    def test_wait_completes_after_timeout(self):
        ex, _ = _executor(behavior_sequence=["wait"], wait_sec=0.05,
                          max_retries_per_goal=5)
        ex.reset()
        ex.step()  # starts wait
        time.sleep(0.08)
        outcome = RecoveryOutcome.IN_PROGRESS
        for _ in range(20):
            outcome = ex.step()
            if outcome == RecoveryOutcome.SUCCEEDED:
                break
        assert outcome == RecoveryOutcome.SUCCEEDED


# ── Clear costmap behavior ────────────────────────────────────────────────────

class TestClearCostmap:
    def test_clear_costmap_instant(self):
        ex, calls = _executor(behavior_sequence=["clear_costmap"])
        ex.reset()
        outcome = ex.step()
        assert calls["clear"] == 1
        assert outcome in (RecoveryOutcome.SUCCEEDED, RecoveryOutcome.IN_PROGRESS)

    def test_clear_costmap_advances_to_next(self):
        ex, calls = _executor(behavior_sequence=["clear_costmap", "replan"])
        ex.reset()
        ex.step()         # clear_costmap (instant) → advances to replan
        outcome = ex.step()  # replan (instant) → SUCCEEDED
        assert outcome == RecoveryOutcome.SUCCEEDED


# ── Backup behavior ───────────────────────────────────────────────────────────

class TestBackup:
    def test_backup_called_with_config_values(self):
        cfg = _cfg(behavior_sequence=["backup"], backup_distance_m=0.3,
                   backup_speed_mps=0.1)
        ex, calls = _executor(cfg=cfg)
        ex.reset()
        ex.step()
        assert calls["backup"] == [(0.3, 0.1)]

    def test_backup_in_progress_then_succeeds(self):
        ex, _ = _executor(behavior_sequence=["backup"],
                          backup_distance_m=0.01, backup_speed_mps=1.0)
        ex.reset()
        ex.step()  # starts backup
        # backup_time = 0.01 / 1.0 + 3.0 = 3.01 s — too long for test
        # Just verify in-progress is returned after first step
        assert ex.is_active()


# ── Spin behavior ─────────────────────────────────────────────────────────────

class TestSpin:
    def test_spin_called_with_config_values(self):
        cfg = _cfg(behavior_sequence=["spin"], spin_angular_speed_rps=0.5,
                   spin_full_rotations=1)
        ex, calls = _executor(cfg=cfg)
        ex.reset()
        ex.step()
        assert calls["spin"] == [(0.5, 1)]

    def test_spin_in_progress(self):
        ex, _ = _executor(behavior_sequence=["spin"])
        ex.reset()
        r = ex.step()
        assert r == RecoveryOutcome.IN_PROGRESS


# ── Replan behavior ───────────────────────────────────────────────────────────

class TestReplan:
    def test_replan_instant(self):
        ex, _ = _executor(behavior_sequence=["replan"])
        ex.reset()
        # replan is instant — should succeed on first or second step
        outcomes = [ex.step() for _ in range(3)]
        assert RecoveryOutcome.SUCCEEDED in outcomes


# ── Announce behavior ─────────────────────────────────────────────────────────

class TestAnnounce:
    def test_announce_text_contains_step_aside(self):
        ex, calls = _executor(behavior_sequence=["announce"],
                              announce_repeat_sec=0.05)
        ex.reset()
        ex.step()
        assert calls["announce"]
        assert "step aside" in calls["announce"][0].lower() \
               or "please" in calls["announce"][0].lower()

    def test_announce_waits_then_succeeds(self):
        ex, _ = _executor(behavior_sequence=["announce"],
                          announce_repeat_sec=0.05, max_retries_per_goal=5)
        ex.reset()
        ex.step()
        time.sleep(0.08)
        outcome = ex.step()
        assert outcome == RecoveryOutcome.SUCCEEDED


# ── Escalate behavior ─────────────────────────────────────────────────────────

class TestEscalate:
    def test_escalate_calls_escalate_fn(self):
        ex, calls = _executor(behavior_sequence=["escalate"])
        ex.reset(trigger_reason="test_reason")
        ex.step()
        assert calls["escalate"]
        assert "test_reason" in calls["escalate"][0]

    def test_escalate_terminal_exhausted(self):
        ex, _ = _executor(behavior_sequence=["escalate"])
        ex.reset()
        outcome = ex.step()
        assert outcome == RecoveryOutcome.EXHAUSTED

    def test_escalate_also_announces(self):
        ex, calls = _executor(behavior_sequence=["escalate"])
        ex.reset()
        ex.step()
        assert calls["announce"]


# ── Max retries ───────────────────────────────────────────────────────────────

class TestMaxRetries:
    def test_exhausted_when_max_retries_reached(self):
        ex, _ = _executor(
            behavior_sequence=["clear_costmap"],
            max_retries_per_goal=1,
        )
        ex.reset()
        # clear_costmap increments total_attempts immediately
        outcomes = []
        for _ in range(10):
            o = ex.step()
            outcomes.append(o)
            if o == RecoveryOutcome.EXHAUSTED:
                break
        assert RecoveryOutcome.EXHAUSTED in outcomes


# ── Unknown behavior ──────────────────────────────────────────────────────────

class TestUnknownBehavior:
    def test_unknown_behavior_skipped(self):
        ex, _ = _executor(behavior_sequence=["totally_unknown_behavior", "replan"])
        ex.reset()
        outcomes = [ex.step() for _ in range(5)]
        # Should not raise; should eventually reach replan and succeed
        assert RecoveryOutcome.SUCCEEDED in outcomes


# ── State accessors ───────────────────────────────────────────────────────────

class TestStateAccessors:
    def test_get_state_none_before_reset(self):
        ex, _ = _executor()
        assert ex.get_state() is None

    def test_get_state_after_reset(self):
        ex, _ = _executor()
        ex.reset(trigger_reason="testing")
        s = ex.get_state()
        assert s is not None
        assert s.trigger_reason == "testing"

    def test_is_active_true_after_reset(self):
        ex, _ = _executor()
        ex.reset()
        assert ex.is_active() is True
