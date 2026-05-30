"""Integrity tests for the 50-entry failure-mode catalogue.

These guarantee the catalogue stays complete and internally consistent, so the
runtime fault registry and the published matrix can never silently drift.
"""

from __future__ import annotations

from bonbon_safety.core.failure_catalog import (
    CATEGORY_RANGES,
    build_catalog,
    numbered_catalog,
)
from bonbon_safety.core.fault_handler import FaultHandler
from bonbon_safety.core.fault_levels import FallbackLevel, requires_operator


class TestCompleteness:
    def test_exactly_fifty_modes(self):
        assert len(build_catalog()) == 50
        assert len(numbered_catalog()) == 50

    def test_numbers_are_1_to_50_contiguous(self):
        nums = sorted(n for n, _ in numbered_catalog())
        assert nums == list(range(1, 51))

    def test_fault_ids_unique(self):
        ids = [d.fault_id for _, d in numbered_catalog()]
        assert len(ids) == len(set(ids))

    def test_category_ranges_cover_all(self):
        covered = set()
        for lo, hi in CATEGORY_RANGES.values():
            covered |= set(range(lo, hi + 1))
        assert covered == set(range(1, 51))


class TestConsistency:
    def test_every_field_populated(self):
        for _, d in numbered_catalog():
            assert d.fault_id and d.module and d.detection
            assert d.recovery and d.user_facing
            assert isinstance(d.level, FallbackLevel)

    def test_severe_levels_alert_operator_or_via_policy(self):
        # Any SAFE_STOP+ fault must alert an operator (directly or by level).
        for _, d in numbered_catalog():
            if d.level >= FallbackLevel.SAFE_STOP:
                assert d.operator_alert or requires_operator(d.level), d.fault_id

    def test_recovery_policies_have_terminal_level(self):
        for _, d in numbered_catalog():
            assert isinstance(d.policy.terminal_level, FallbackLevel)
            assert d.policy.max_attempts >= 0

    def test_emergency_stop_is_not_self_recoverable(self):
        # The e-stop-during-motion mode must not auto-retry.
        cat = build_catalog()
        estop = cat["NAV_ESTOP_DURING_MOTION"]
        assert estop.level == FallbackLevel.EMERGENCY_STOP
        assert estop.policy.max_attempts == 0


class TestRegistryUsableByHandler:
    def test_handler_accepts_full_catalog(self):
        handler = FaultHandler(build_catalog())
        # A representative fault from each category can be raised + cleared.
        for fid in ("SENSOR_LIDAR_DISCONNECT", "AI_LLM_UNSAFE_PROPOSAL",
                    "ACT_SERVO_STUCK", "SYS_NODE_CRASH"):
            handler.raise_fault(fid, "test")
            assert handler.is_active(fid)
            handler.clear_fault(fid)
            assert not handler.is_active(fid)

    def test_unsafe_llm_proposal_is_safe_pause(self):
        cat = build_catalog()
        assert cat["AI_LLM_UNSAFE_PROPOSAL"].level == FallbackLevel.SAFE_PAUSE
        assert cat["AI_LLM_UNSAFE_PROPOSAL"].operator_alert is True
