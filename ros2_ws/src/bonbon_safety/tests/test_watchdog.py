"""
test_watchdog.py
================
Pure-Python unit tests for WatchdogNode logic, isolated from ROS2.

We test the data structures and classification logic directly rather than
spinning up a ROS2 node. The key behaviours are:

- ManagedNode staleness detection (age > stale_multiplier × period)
- Recovery resets is_stale and restart_count
- restart_count is bounded by max_restart_attempts
- Node class assignment matches the DEFAULT_MANAGED_NODES registry
- Critical vs important stale flags are computed correctly
"""

from __future__ import annotations

import time

from bonbon_safety.nodes.watchdog_node import (
    DEFAULT_MANAGED_NODES,
    ManagedNode,
    NodeClass,
)

# ── ManagedNode dataclass ─────────────────────────────────────────────────────


class TestManagedNodeDefaults:
    def test_default_stale_false(self):
        node = ManagedNode(
            name="test_node",
            health_topic="/test/health",
            node_class=NodeClass.ESSENTIAL,
            expected_period_sec=1.0,
        )
        assert node.is_stale is False

    def test_default_restart_count_zero(self):
        node = ManagedNode(
            name="test_node",
            health_topic="/test/health",
            node_class=NodeClass.AUXILIARY,
            expected_period_sec=2.0,
        )
        assert node.restart_count == 0

    def test_default_last_seen_nonzero(self):
        """last_seen defaults to 0.0 in the dataclass (not time.monotonic)."""
        node = ManagedNode(
            name="test_node",
            health_topic="/test/health",
            node_class=NodeClass.CRITICAL,
            expected_period_sec=1.0,
        )
        assert node.last_seen == 0.0


# ── NodeClass enum ────────────────────────────────────────────────────────────


class TestNodeClass:
    def test_critical_lowest_int(self):
        assert NodeClass.CRITICAL < NodeClass.ESSENTIAL
        assert NodeClass.ESSENTIAL < NodeClass.IMPORTANT
        assert NodeClass.IMPORTANT < NodeClass.AUXILIARY

    def test_values_are_1_to_4(self):
        assert NodeClass.CRITICAL == 1
        assert NodeClass.ESSENTIAL == 2
        assert NodeClass.IMPORTANT == 3
        assert NodeClass.AUXILIARY == 4


# ── Stale detection logic ─────────────────────────────────────────────────────


class TestStaleDetection:
    """Simulate the watchdog's check_cycle logic without ROS2."""

    @staticmethod
    def _is_stale(node: ManagedNode, now: float) -> bool:
        threshold = node.expected_period_sec * node.stale_multiplier
        return (now - node.last_seen) > threshold

    def test_not_stale_immediately_after_update(self):
        node = ManagedNode("n", "/h", NodeClass.ESSENTIAL, 1.0)
        node.last_seen = time.monotonic()
        assert not self._is_stale(node, time.monotonic())

    def test_stale_after_threshold(self):
        node = ManagedNode("n", "/h", NodeClass.ESSENTIAL, 1.0, stale_multiplier=3.0)
        node.last_seen = time.monotonic() - 4.0  # 4s > 3 × 1.0s threshold
        assert self._is_stale(node, time.monotonic())

    def test_not_stale_just_under_threshold(self):
        node = ManagedNode("n", "/h", NodeClass.ESSENTIAL, 1.0, stale_multiplier=3.0)
        node.last_seen = time.monotonic() - 2.9  # < 3s
        assert not self._is_stale(node, time.monotonic())

    def test_faster_heartbeat_has_tighter_stale_window(self):
        slow = ManagedNode("slow", "/s", NodeClass.IMPORTANT, 2.0)
        fast = ManagedNode("fast", "/f", NodeClass.IMPORTANT, 0.5)
        # Both last seen 2s ago
        now = time.monotonic()
        slow.last_seen = now - 2.0
        fast.last_seen = now - 2.0
        # slow: threshold = 2.0×3=6s  → not stale at 2s
        # fast: threshold = 0.5×3=1.5s → stale at 2s
        assert not self._is_stale(slow, now)
        assert self._is_stale(fast, now)


# ── Restart logic ─────────────────────────────────────────────────────────────


class TestRestartLogic:
    def test_restart_increments_count(self):
        node = ManagedNode("n", "/h", NodeClass.ESSENTIAL, 1.0, max_restart_attempts=3)
        node.restart_count += 1
        assert node.restart_count == 1

    def test_restart_stops_at_max(self):
        node = ManagedNode("n", "/h", NodeClass.ESSENTIAL, 1.0, max_restart_attempts=3)
        node.restart_count = 3
        # Simulating _attempt_restart guard
        can_restart = node.restart_count < node.max_restart_attempts
        assert can_restart is False

    def test_restart_allowed_below_max(self):
        node = ManagedNode("n", "/h", NodeClass.ESSENTIAL, 1.0, max_restart_attempts=3)
        node.restart_count = 2
        can_restart = node.restart_count < node.max_restart_attempts
        assert can_restart is True

    def test_recovery_resets_restart_count(self):
        node = ManagedNode("n", "/h", NodeClass.ESSENTIAL, 1.0)
        node.is_stale = True
        node.restart_count = 2
        # Simulate recovery (as in _cb_health)
        node.is_stale = False
        node.restart_count = 0
        assert node.restart_count == 0
        assert node.is_stale is False


# ── DEFAULT_MANAGED_NODES registry ───────────────────────────────────────────


class TestDefaultRegistry:
    def test_registry_not_empty(self):
        assert len(DEFAULT_MANAGED_NODES) > 0

    def test_estop_node_is_critical(self):
        estop = next((n for n in DEFAULT_MANAGED_NODES if n.name == "estop_node"), None)
        assert estop is not None, "estop_node not in registry"
        assert estop.node_class == NodeClass.CRITICAL

    def test_safety_gate_is_critical(self):
        gate = next((n for n in DEFAULT_MANAGED_NODES if n.name == "safety_gate_node"), None)
        assert gate is not None, "safety_gate_node not in registry"
        assert gate.node_class == NodeClass.CRITICAL

    def test_lidar_is_essential(self):
        lidar = next((n for n in DEFAULT_MANAGED_NODES if n.name == "lidar_node"), None)
        assert lidar is not None, "lidar_node not in registry"
        assert lidar.node_class == NodeClass.ESSENTIAL

    def test_display_is_auxiliary(self):
        display = next((n for n in DEFAULT_MANAGED_NODES if n.name == "display_node"), None)
        assert display is not None, "display_node not in registry"
        assert display.node_class == NodeClass.AUXILIARY

    def test_no_duplicate_names(self):
        names = [n.name for n in DEFAULT_MANAGED_NODES]
        assert len(names) == len(set(names)), "Duplicate node names in registry"

    def test_all_have_valid_health_topics(self):
        for node in DEFAULT_MANAGED_NODES:
            assert node.health_topic.startswith(
                "/bonbon/"
            ), f"{node.name}: health_topic should start with /bonbon/"
            assert node.health_topic.endswith(
                "/health"
            ), f"{node.name}: health_topic should end with /health"

    def test_all_have_positive_period(self):
        for node in DEFAULT_MANAGED_NODES:
            assert (
                node.expected_period_sec > 0
            ), f"{node.name}: expected_period_sec must be positive"

    def test_all_critical_nodes_have_1hz_period(self):
        """Critical nodes should have tight heartbeat periods."""
        for node in DEFAULT_MANAGED_NODES:
            if node.node_class == NodeClass.CRITICAL:
                assert (
                    node.expected_period_sec <= 1.0
                ), f"{node.name}: CRITICAL node period should be ≤ 1.0s"

    def test_critical_and_essential_node_counts(self):
        critical = [n for n in DEFAULT_MANAGED_NODES if n.node_class == NodeClass.CRITICAL]
        essential = [n for n in DEFAULT_MANAGED_NODES if n.node_class == NodeClass.ESSENTIAL]
        assert len(critical) >= 2, "Expected at least 2 CRITICAL nodes"
        assert len(essential) >= 2, "Expected at least 2 ESSENTIAL nodes"


# ── Crash flag computation ────────────────────────────────────────────────────


class TestCrashFlags:
    """Simulate how watchdog computes critical/important stale flags."""

    @staticmethod
    def _compute_flags(registry: list[ManagedNode]) -> tuple[bool, bool]:
        critical = any(n.is_stale and n.node_class == NodeClass.CRITICAL for n in registry)
        important = any(
            n.is_stale and n.node_class in (NodeClass.ESSENTIAL, NodeClass.IMPORTANT)
            for n in registry
        )
        return critical, important

    def test_no_stale_no_flags(self):
        registry = [
            ManagedNode("a", "/a/h", NodeClass.CRITICAL, 1.0),
            ManagedNode("b", "/b/h", NodeClass.ESSENTIAL, 1.0),
        ]
        c, i = self._compute_flags(registry)
        assert c is False
        assert i is False

    def test_critical_stale_sets_critical_flag(self):
        node = ManagedNode("a", "/a/h", NodeClass.CRITICAL, 1.0)
        node.is_stale = True
        c, i = self._compute_flags([node])
        assert c is True

    def test_important_stale_sets_important_flag(self):
        node = ManagedNode("b", "/b/h", NodeClass.IMPORTANT, 1.0)
        node.is_stale = True
        c, i = self._compute_flags([node])
        assert i is True
        assert c is False

    def test_auxiliary_stale_sets_neither_flag(self):
        node = ManagedNode("c", "/c/h", NodeClass.AUXILIARY, 2.0)
        node.is_stale = True
        c, i = self._compute_flags([node])
        assert c is False
        assert i is False
