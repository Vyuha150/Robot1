"""Unit tests for bonbon_safety.core.fault_handler."""

from __future__ import annotations

from bonbon_safety.core.fault_handler import (
    FaultDefinition,
    FaultHandler,
    RecoveryPolicy,
    Watchdog,
)
from bonbon_safety.core.fault_levels import FallbackLevel


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


# ── Watchdog ─────────────────────────────────────────────────────────────────

class TestWatchdog:
    def test_unpetted_is_stale(self):
        wd = Watchdog(timeout_sec=1.0, clock=_Clock())
        assert wd.is_stale() is True

    def test_fresh_pet_not_stale(self):
        clock = _Clock()
        wd = Watchdog(timeout_sec=1.0, clock=clock)
        wd.pet()
        clock.t = 0.5
        assert wd.is_stale() is False

    def test_goes_stale_after_timeout(self):
        clock = _Clock()
        wd = Watchdog(timeout_sec=1.0, clock=clock)
        wd.pet()
        clock.t = 1.5
        assert wd.is_stale() is True

    def test_operation_timeout(self):
        clock = _Clock()
        wd = Watchdog(timeout_sec=1.0, clock=clock)
        wd.start_operation()
        clock.t = 0.05
        assert wd.operation_exceeded(0.08) is False
        clock.t = 0.10
        assert wd.operation_exceeded(0.08) is True


# ── RecoveryPolicy ─────────────────────────────────────────────────────────────

class TestRecoveryPolicy:
    def test_backoff_grows_and_caps(self):
        p = RecoveryPolicy(backoff_sec=0.5, backoff_mult=2.0, max_backoff_sec=3.0)
        assert p.delay_for_attempt(1) == 0.5
        assert p.delay_for_attempt(2) == 1.0
        assert p.delay_for_attempt(3) == 2.0
        assert p.delay_for_attempt(4) == 3.0   # capped
        assert p.delay_for_attempt(0) == 0.0


# ── FaultHandler pipeline ──────────────────────────────────────────────────────

def _defs():
    return {
        "X": FaultDefinition(
            fault_id="X", module="m", detection="d",
            level=FallbackLevel.DEGRADED, recovery="r", user_facing="u",
            operator_alert=False,
            policy=RecoveryPolicy(max_attempts=2, terminal_level=FallbackLevel.SAFE_STOP),
        ),
        "CRIT": FaultDefinition(
            fault_id="CRIT", module="m", detection="d",
            level=FallbackLevel.SAFE_STOP, recovery="r", user_facing="u",
            operator_alert=True,
        ),
    }


class TestFaultHandler:
    def test_raise_records_active_and_logs(self):
        logs = []
        h = FaultHandler(_defs(), log_sink=logs.append)
        h.raise_fault("X", "camera lost")
        assert h.is_active("X")
        assert any(e.phase == "detected" for e in logs)

    def test_unknown_fault_raises(self):
        h = FaultHandler(_defs())
        try:
            h.raise_fault("NOPE")
            assert False, "expected KeyError"
        except KeyError:
            pass

    def test_operator_escalation_on_safe_stop(self):
        escalations = []
        h = FaultHandler(_defs(), escalation_sink=escalations.append)
        h.raise_fault("CRIT")
        assert len(escalations) == 1
        assert escalations[0].phase == "escalated"

    def test_no_escalation_for_degraded(self):
        escalations = []
        h = FaultHandler(_defs(), escalation_sink=escalations.append)
        h.raise_fault("X")
        assert escalations == []

    def test_successful_recovery_clears(self):
        h = FaultHandler(_defs())
        h.raise_fault("X")
        h.register_recovery("X", lambda: True)
        assert h.attempt_recovery("X") is True
        assert h.is_active("X") is False

    def test_failed_recovery_escalates_after_attempts(self):
        escalations = []
        diags = []
        h = FaultHandler(_defs(), escalation_sink=escalations.append,
                         diagnostic_sink=diags.append)
        h.raise_fault("X")
        h.register_recovery("X", lambda: False)
        assert h.attempt_recovery("X") is False   # attempt 1
        assert h.attempt_recovery("X") is False   # attempt 2 (== max) → escalate
        assert any(e.phase == "escalated" and e.level == FallbackLevel.SAFE_STOP
                   for e in escalations)

    def test_recovery_exception_counts_as_failure(self):
        h = FaultHandler(_defs())
        h.raise_fault("X")
        h.register_recovery("X", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        assert h.attempt_recovery("X") is False
        assert h.is_active("X") is True

    def test_current_level_is_most_severe(self):
        h = FaultHandler(_defs())
        h.raise_fault("X")       # DEGRADED
        h.raise_fault("CRIT")    # SAFE_STOP
        assert h.current_level() == FallbackLevel.SAFE_STOP
        h.clear_fault("CRIT")
        assert h.current_level() == FallbackLevel.DEGRADED
        h.clear_fault("X")
        assert h.current_level() == FallbackLevel.NORMAL

    def test_clear_resets_attempts(self):
        h = FaultHandler(_defs())
        h.raise_fault("X")
        h.register_recovery("X", lambda: False)
        h.attempt_recovery("X")
        h.clear_fault("X")
        h.raise_fault("X")
        # Attempt counter restarted — first attempt again, not escalation.
        h.register_recovery("X", lambda: False)
        assert h.attempt_recovery("X") is False
        assert h.is_active("X") is True
