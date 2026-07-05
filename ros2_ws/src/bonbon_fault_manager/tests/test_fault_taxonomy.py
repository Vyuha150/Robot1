"""Tests for bonbon_fault_manager.core.fault_taxonomy."""

from __future__ import annotations

import pytest
from bonbon_fault_manager.core.fault_taxonomy import FaultLevel, is_actionable, worst


class TestFaultLevelOrdering:
    def test_ok_is_lowest(self):
        assert FaultLevel.OK < FaultLevel.WARNING

    def test_blocked_is_highest(self):
        assert FaultLevel.BLOCKED > FaultLevel.CRITICAL

    def test_full_order(self):
        levels = [
            FaultLevel.OK,
            FaultLevel.WARNING,
            FaultLevel.DEGRADED,
            FaultLevel.FAULT,
            FaultLevel.CRITICAL,
            FaultLevel.BLOCKED,
        ]
        assert levels == sorted(levels)


class TestWorst:
    def test_empty_is_ok(self):
        assert worst([]) == FaultLevel.OK

    def test_single_level(self):
        assert worst([FaultLevel.FAULT]) == FaultLevel.FAULT

    def test_picks_maximum(self):
        assert worst([FaultLevel.OK, FaultLevel.CRITICAL, FaultLevel.WARNING]) == (
            FaultLevel.CRITICAL
        )

    def test_all_ok_is_ok(self):
        assert worst([FaultLevel.OK, FaultLevel.OK]) == FaultLevel.OK

    def test_blocked_dominates(self):
        assert worst([FaultLevel.BLOCKED, FaultLevel.CRITICAL]) == FaultLevel.BLOCKED


class TestIsActionable:
    def test_ok_not_actionable(self):
        assert is_actionable(FaultLevel.OK) is False

    @pytest.mark.parametrize(
        "level",
        [
            FaultLevel.WARNING,
            FaultLevel.DEGRADED,
            FaultLevel.FAULT,
            FaultLevel.CRITICAL,
            FaultLevel.BLOCKED,
        ],
    )
    def test_warning_and_above_is_actionable(self, level):
        assert is_actionable(level) is True


if __name__ == "__main__":
    pytest.main([__file__])
