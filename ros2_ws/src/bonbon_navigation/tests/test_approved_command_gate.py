"""Tests for bonbon_navigation.safety.approved_command_gate -- GAP-E2
fix. Pure logic, no rclpy required."""

from __future__ import annotations

from bonbon_navigation.safety.approved_command_gate import should_dispatch_navigation


class TestShouldDispatchNavigation:
    def test_approved_navigate_dispatches(self):
        assert should_dispatch_navigation("approved", "navigate") is True

    def test_approved_approach_dispatches(self):
        assert should_dispatch_navigation("approved", "approach") is True

    def test_rejected_never_dispatches(self):
        assert should_dispatch_navigation("rejected", "navigate") is False

    def test_escalated_never_dispatches(self):
        # Safety Supervisor approval required -- an escalation is
        # explicitly NOT an approval and must never reach goal dispatch.
        assert should_dispatch_navigation("escalated", "navigate") is False

    def test_deferred_never_dispatches(self):
        assert should_dispatch_navigation("deferred", "navigate") is False

    def test_approved_non_navigation_action_never_dispatches(self):
        # An approved "speak" or "gesture" decision must never be
        # mistaken for a navigation goal just because decision=="approved".
        assert should_dispatch_navigation("approved", "speak") is False
        assert should_dispatch_navigation("approved", "gesture") is False

    def test_unknown_action_fails_closed(self):
        assert should_dispatch_navigation("approved", "something_new") is False
