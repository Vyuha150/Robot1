"""
test_safety_gate.py
====================
Unit tests for the SafetyGateNode's pure-Python logic:

  GateStats          — counter correctness
  _clamp_twist       — velocity clamping arithmetic
  _can_actuate/nav   — gating decisions under all 8 safety states
  Defensive mode     — supervisor watchdog expiry
  Lifecycle          — configure / activate / deactivate / cleanup sequencing

These tests deliberately do NOT start a ROS2 context (no rclpy.init()) so they
run fast with `pytest tests/ -v --ignore=tests/integration`.  Only the gating
logic and helper methods are exercised; ROS2 pub/sub wiring is validated by
the integration test.
"""

from __future__ import annotations

import math
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

# ── Import pure-Python helpers from the node module ──────────────────────────
from bonbon_safety.nodes.safety_gate_node import (
    GateStats,
    SafetyGateNode,
)

# ── Minimal SafetyState stub (avoids ROS2 import at test time) ───────────────
# The real class comes from bonbon_msgs.msg.SafetyState, but pytest runs
# without a ROS2 installation on the CI.  We replicate just the fields that
# the gate node reads.


class _FakeSafetyState:
    INITIALIZING = 0
    NORMAL = 1
    CAUTION = 2
    DANGER = 3
    DOCKING = 4
    DEGRADED = 5
    FAULT = 6
    SAFE_STOP = 7

    def __init__(
        self,
        state: int = 1,
        actuation_permitted: bool = True,
        navigation_permitted: bool = True,
        max_velocity_mps: float = 0.8,
        state_name: str = "NORMAL",
        requires_manual_reset: bool = False,
    ):
        self.state = state
        self.actuation_permitted = actuation_permitted
        self.navigation_permitted = navigation_permitted
        self.max_velocity_mps = max_velocity_mps
        self.state_name = state_name
        self.requires_manual_reset = requires_manual_reset


class _FakeTwist:
    """Minimal geometry_msgs/Twist stand-in."""

    class _Vec3:
        def __init__(self):
            self.x = 0.0
            self.y = 0.0
            self.z = 0.0

    def __init__(self, vx: float = 0.0, vy: float = 0.0, wz: float = 0.0):
        self.linear = self._Vec3()
        self.angular = self._Vec3()
        self.linear.x = vx
        self.linear.y = vy
        self.angular.z = wz


# ── Pre-built SafetyState fixtures for all 8 states ──────────────────────────
_STATES = {
    "INITIALIZING": _FakeSafetyState(0, False, False, 0.0, "INITIALIZING"),
    "NORMAL": _FakeSafetyState(1, True, True, 0.8, "NORMAL"),
    "CAUTION": _FakeSafetyState(2, True, True, 0.3, "CAUTION"),
    "DANGER": _FakeSafetyState(3, False, False, 0.0, "DANGER"),
    "DOCKING": _FakeSafetyState(4, True, True, 0.2, "DOCKING"),
    "DEGRADED": _FakeSafetyState(5, True, True, 0.3, "DEGRADED"),
    "FAULT": _FakeSafetyState(6, False, False, 0.0, "FAULT", True),
    "SAFE_STOP": _FakeSafetyState(7, False, False, 0.0, "SAFE_STOP", True),
}


# ═══════════════════════════════════════════════════════════════════════════════
# GateStats
# ═══════════════════════════════════════════════════════════════════════════════


class TestGateStats:
    def test_initial_all_zero(self):
        s = GateStats()
        snap = s.snapshot()
        assert snap["servo_passed"] == 0
        assert snap["servo_blocked"] == 0
        assert snap["vel_passed"] == 0
        assert snap["vel_scaled"] == 0
        assert snap["vel_blocked"] == 0
        assert snap["total_blocked"] == 0

    def test_servo_pass_increments(self):
        s = GateStats()
        s.record_servo_pass()
        s.record_servo_pass()
        assert s.snapshot()["servo_passed"] == 2

    def test_servo_block_increments_total(self):
        s = GateStats()
        s.record_servo_block()
        snap = s.snapshot()
        assert snap["servo_blocked"] == 1
        assert snap["total_blocked"] == 1

    def test_vel_pass_increments(self):
        s = GateStats()
        s.record_vel_pass()
        assert s.snapshot()["vel_passed"] == 1
        assert s.snapshot()["total_blocked"] == 0

    def test_vel_scale_also_counts_pass(self):
        s = GateStats()
        s.record_vel_scale()
        snap = s.snapshot()
        assert snap["vel_scaled"] == 1
        assert snap["vel_passed"] == 1  # scaled = forwarded

    def test_vel_block_increments_total(self):
        s = GateStats()
        s.record_vel_block()
        snap = s.snapshot()
        assert snap["vel_blocked"] == 1
        assert snap["total_blocked"] == 1

    def test_mixed_scenario(self):
        s = GateStats()
        for _ in range(5):
            s.record_servo_pass()
        s.record_servo_block()
        for _ in range(3):
            s.record_vel_pass()
        s.record_vel_scale()
        s.record_vel_block()
        snap = s.snapshot()
        assert snap["servo_passed"] == 5
        assert snap["servo_blocked"] == 1
        assert snap["vel_passed"] == 4  # 3 pass + 1 scale
        assert snap["vel_scaled"] == 1
        assert snap["vel_blocked"] == 1
        assert snap["total_blocked"] == 2

    def test_uptime_increases(self):
        s = GateStats()
        time.sleep(0.05)
        assert s.snapshot()["uptime_sec"] >= 0.04

    def test_thread_safety(self):
        """Concurrent increments must not corrupt counters."""
        s = GateStats()
        threads = [
            threading.Thread(target=lambda: [s.record_servo_pass() for _ in range(100)])
            for _ in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert s.snapshot()["servo_passed"] == 1000


# ═══════════════════════════════════════════════════════════════════════════════
# _clamp_twist  (static method — no ROS2 needed)
# ═══════════════════════════════════════════════════════════════════════════════


class TestClampTwist:
    """Tests for SafetyGateNode._clamp_twist (static)."""

    def _clamp(self, vx, vy, max_v, wz=0.0):
        twist = _FakeTwist(vx=vx, vy=vy, wz=wz)
        # Patch the Twist constructor inside the node module temporarily
        with patch("bonbon_safety.nodes.safety_gate_node.Twist", _FakeTwist):
            return SafetyGateNode._clamp_twist(twist, max_v)

    def test_below_limit_not_scaled(self):
        twist = _FakeTwist(vx=0.2, vy=0.0)
        clamped, scaled = SafetyGateNode._clamp_twist(twist, 0.8)
        assert not scaled
        assert clamped.linear.x == pytest.approx(0.2)

    def test_exactly_at_limit_not_scaled(self):
        twist = _FakeTwist(vx=0.8, vy=0.0)
        clamped, scaled = SafetyGateNode._clamp_twist(twist, 0.8)
        assert not scaled

    def test_above_limit_scaled(self):
        twist = _FakeTwist(vx=1.0, vy=0.0)
        clamped, scaled = SafetyGateNode._clamp_twist(twist, 0.5)
        assert scaled
        speed = math.sqrt(clamped.linear.x**2 + clamped.linear.y**2)
        assert speed == pytest.approx(0.5, abs=1e-6)

    def test_diagonal_velocity_clamped(self):
        """2-D diagonal: both x and y scaled proportionally."""
        twist = _FakeTwist(vx=0.6, vy=0.8)  # speed = 1.0
        clamped, scaled = SafetyGateNode._clamp_twist(twist, 0.5)
        assert scaled
        speed = math.sqrt(clamped.linear.x**2 + clamped.linear.y**2)
        assert speed == pytest.approx(0.5, abs=1e-6)
        # Direction preserved: vy/vx ratio
        assert clamped.linear.y / clamped.linear.x == pytest.approx(0.8 / 0.6, abs=1e-4)

    def test_zero_max_vel_returns_zero_twist(self):
        """max_vel=0 → all-zero Twist regardless of input."""
        twist = _FakeTwist(vx=1.0, vy=0.5)
        with patch("bonbon_safety.nodes.safety_gate_node.Twist", _FakeTwist):
            clamped, scaled = SafetyGateNode._clamp_twist(twist, 0.0)
        assert scaled
        assert clamped.linear.x == pytest.approx(0.0)
        assert clamped.linear.y == pytest.approx(0.0)

    def test_angular_velocity_preserved(self):
        """Angular velocity must never be clamped."""
        twist = _FakeTwist(vx=1.0, vy=0.0, wz=2.0)
        clamped, scaled = SafetyGateNode._clamp_twist(twist, 0.5)
        assert clamped.angular.z == pytest.approx(2.0)

    def test_near_zero_speed_not_divided(self):
        """Avoids division by zero when input speed is negligible."""
        twist = _FakeTwist(vx=1e-9, vy=0.0)
        clamped, scaled = SafetyGateNode._clamp_twist(twist, 0.8)
        assert not scaled  # speed < 1e-6 threshold


# ═══════════════════════════════════════════════════════════════════════════════
# Gating decisions: _can_actuate / _can_navigate
# ═══════════════════════════════════════════════════════════════════════════════


def _make_gate_with_state(state_name: str, supervisor_ok: bool = True) -> SafetyGateNode:
    """
    Create a SafetyGateNode instance with a fake safety state injected directly
    into its internal fields — bypassing ROS2 entirely.
    """
    # Patch LifecycleNode.__init__ to do nothing (no ROS2 context needed)
    with (
        patch("bonbon_safety.nodes.safety_gate_node.LifecycleNode.__init__", lambda *a, **kw: None),
        patch(
            "bonbon_safety.nodes.safety_gate_node.LifecycleNode.get_logger",
            return_value=MagicMock(),
        ),
        patch("bonbon_safety.nodes.safety_gate_node.LifecycleNode.declare_parameter"),
    ):
        gate = SafetyGateNode.__new__(SafetyGateNode)
        gate._lock = threading.Lock()
        gate._safety_state = _STATES[state_name]
        gate._state_recv_time = time.monotonic()
        gate._supervisor_ok = supervisor_ok
        gate._stats = GateStats()
        gate._start_time = time.monotonic()
        gate._error_count = 0
        gate._warning_count = 0
        gate._processed_count = 0
        gate._pub_neck = None
        gate._pub_arm = None
        gate._pub_vel = None
        gate._pub_health = None
        gate._health_timer = None
        gate._watchdog_timer = None
        gate._caution_vel_cap = 0.3
        gate._block_servos_in_danger = True
        gate._health_rate_hz = 1.0
        gate._watchdog_timeout_sec = 2.0
    return gate


@pytest.mark.parametrize(
    "state_name,expected_actuate,expected_nav",
    [
        ("INITIALIZING", False, False),
        ("NORMAL", True, True),
        ("CAUTION", True, True),
        ("DANGER", False, False),
        ("DOCKING", True, True),
        ("DEGRADED", True, True),
        ("FAULT", False, False),
        ("SAFE_STOP", False, False),
    ],
)
class TestGatingDecisionsAllStates:
    def test_can_actuate(self, state_name, expected_actuate, expected_nav):
        gate = _make_gate_with_state(state_name)
        assert gate._can_actuate() == expected_actuate

    def test_can_navigate(self, state_name, expected_actuate, expected_nav):
        gate = _make_gate_with_state(state_name)
        assert gate._can_navigate() == expected_nav


class TestGatingEdgeCases:
    def test_no_safety_state_blocks_actuation(self):
        gate = _make_gate_with_state("NORMAL")
        gate._safety_state = None
        assert gate._can_actuate() is False

    def test_no_safety_state_blocks_navigation(self):
        gate = _make_gate_with_state("NORMAL")
        gate._safety_state = None
        assert gate._can_navigate() is False

    def test_supervisor_not_ok_blocks_actuation(self):
        gate = _make_gate_with_state("NORMAL", supervisor_ok=False)
        assert gate._can_actuate() is False

    def test_supervisor_not_ok_blocks_navigation(self):
        gate = _make_gate_with_state("NORMAL", supervisor_ok=False)
        assert gate._can_navigate() is False

    def test_danger_actuation_blocked_by_flag(self):
        """DANGER + block_servos_in_danger=True → actuation blocked even if
        actuation_permitted flag were somehow True (belt and suspenders)."""
        gate = _make_gate_with_state("DANGER")
        gate._block_servos_in_danger = True
        # Manually set actuation_permitted=True on the fake state to test the
        # secondary guard inside _can_actuate
        gate._safety_state.actuation_permitted = True
        assert gate._can_actuate() is False

    def test_danger_actuation_allowed_when_flag_false(self):
        """If block_servos_in_danger=False the gate defers to actuation_permitted."""
        gate = _make_gate_with_state("DANGER")
        gate._block_servos_in_danger = False
        # DANGER's actuation_permitted=False per _STATES so still blocked
        assert gate._can_actuate() is False

    def test_current_state_name_unknown_when_none(self):
        gate = _make_gate_with_state("NORMAL")
        gate._safety_state = None
        assert gate._current_state_name() == "UNKNOWN"

    def test_current_state_name_returns_label(self):
        gate = _make_gate_with_state("CAUTION")
        assert gate._current_state_name() == "CAUTION"


# ═══════════════════════════════════════════════════════════════════════════════
# Supervisor watchdog
# ═══════════════════════════════════════════════════════════════════════════════


class TestSupervisorWatchdog:
    def _make_gate(self, timeout: float = 0.1) -> SafetyGateNode:
        gate = _make_gate_with_state("NORMAL")
        gate._watchdog_timeout_sec = timeout
        gate._pub_vel = MagicMock()
        return gate

    def test_fresh_state_stays_ok(self):
        gate = self._make_gate()
        gate._check_supervisor_watchdog()
        assert gate._supervisor_ok is True

    def test_stale_state_enters_defensive(self):
        gate = self._make_gate(timeout=0.05)
        # Set last receive to far in the past
        gate._state_recv_time = time.monotonic() - 1.0
        gate._check_supervisor_watchdog()
        assert gate._supervisor_ok is False

    def test_stale_state_publishes_zero_vel(self):
        gate = self._make_gate(timeout=0.05)
        gate._state_recv_time = time.monotonic() - 1.0
        gate._check_supervisor_watchdog()
        gate._pub_vel.publish.assert_called()

    def test_stale_state_increments_warning_count(self):
        gate = self._make_gate(timeout=0.05)
        gate._state_recv_time = time.monotonic() - 1.0
        initial = gate._warning_count
        gate._check_supervisor_watchdog()
        assert gate._warning_count == initial + 1

    def test_recovery_restores_ok(self):
        gate = self._make_gate(timeout=0.05)
        gate._supervisor_ok = False  # simulate prior loss
        gate._state_recv_time = time.monotonic()  # fresh message
        gate._check_supervisor_watchdog()
        assert gate._supervisor_ok is True

    def test_no_double_warn_on_persistent_loss(self):
        """Watchdog logs WARN only once per transition, not every call."""
        gate = self._make_gate(timeout=0.05)
        gate._state_recv_time = time.monotonic() - 1.0
        # First call: supervisor_ok goes False → warning logged
        gate._check_supervisor_watchdog()
        warn_count_after_first = gate._warning_count
        # Second call: already False → should NOT add another warning
        gate._check_supervisor_watchdog()
        assert gate._warning_count == warn_count_after_first


# ═══════════════════════════════════════════════════════════════════════════════
# Velocity gating via _on_vel_raw
# ═══════════════════════════════════════════════════════════════════════════════


class TestVelocityGating:
    """End-to-end velocity gating with mocked publisher."""

    def _make_gate(self, state_name: str) -> SafetyGateNode:
        gate = _make_gate_with_state(state_name)
        gate._pub_vel = MagicMock()
        return gate

    def test_normal_passes_full_speed(self):
        gate = self._make_gate("NORMAL")
        twist = _FakeTwist(vx=0.5)
        with patch("bonbon_safety.nodes.safety_gate_node.Twist", _FakeTwist):
            gate._on_vel_raw(twist)
        gate._pub_vel.publish.assert_called_once()
        published = gate._pub_vel.publish.call_args[0][0]
        assert published.linear.x == pytest.approx(0.5)

    def test_caution_caps_velocity(self):
        gate = self._make_gate("CAUTION")  # max_vel=0.3
        twist = _FakeTwist(vx=0.8)  # over limit
        with patch("bonbon_safety.nodes.safety_gate_node.Twist", _FakeTwist):
            gate._on_vel_raw(twist)
        gate._pub_vel.publish.assert_called_once()
        published = gate._pub_vel.publish.call_args[0][0]
        speed = math.sqrt(published.linear.x**2 + published.linear.y**2)
        assert speed == pytest.approx(0.3, abs=0.01)

    def test_caution_below_cap_not_scaled(self):
        gate = self._make_gate("CAUTION")  # max_vel=0.3
        twist = _FakeTwist(vx=0.1)
        with patch("bonbon_safety.nodes.safety_gate_node.Twist", _FakeTwist):
            gate._on_vel_raw(twist)
        published = gate._pub_vel.publish.call_args[0][0]
        assert published.linear.x == pytest.approx(0.1)
        # vel_passed should be 1, vel_scaled should be 0
        snap = gate._stats.snapshot()
        assert snap["vel_passed"] == 1
        assert snap["vel_scaled"] == 0

    def test_danger_blocks_velocity(self):
        gate = self._make_gate("DANGER")
        twist = _FakeTwist(vx=0.5)
        with patch("bonbon_safety.nodes.safety_gate_node.Twist", _FakeTwist):
            gate._on_vel_raw(twist)
        # Published a zero twist
        gate._pub_vel.publish.assert_called()
        published = gate._pub_vel.publish.call_args[0][0]
        assert published.linear.x == pytest.approx(0.0)
        assert gate._stats.snapshot()["vel_blocked"] == 1

    def test_safe_stop_blocks_velocity(self):
        gate = self._make_gate("SAFE_STOP")
        twist = _FakeTwist(vx=0.5)
        with patch("bonbon_safety.nodes.safety_gate_node.Twist", _FakeTwist):
            gate._on_vel_raw(twist)
        assert gate._stats.snapshot()["vel_blocked"] == 1

    def test_no_state_blocks_velocity(self):
        gate = self._make_gate("NORMAL")
        gate._safety_state = None
        twist = _FakeTwist(vx=0.5)
        with patch("bonbon_safety.nodes.safety_gate_node.Twist", _FakeTwist):
            gate._on_vel_raw(twist)
        assert gate._stats.snapshot()["vel_blocked"] == 1

    def test_docking_caps_to_0_2(self):
        gate = self._make_gate("DOCKING")  # max_vel=0.2
        twist = _FakeTwist(vx=0.5)
        with patch("bonbon_safety.nodes.safety_gate_node.Twist", _FakeTwist):
            gate._on_vel_raw(twist)
        published = gate._pub_vel.publish.call_args[0][0]
        speed = math.sqrt(published.linear.x**2 + published.linear.y**2)
        assert speed == pytest.approx(0.2, abs=0.01)


# ═══════════════════════════════════════════════════════════════════════════════
# Servo gating via _on_neck_command_raw / _on_arm_command_raw
# ═══════════════════════════════════════════════════════════════════════════════


class TestServoGating:
    def _make_gate(self, state_name: str) -> SafetyGateNode:
        gate = _make_gate_with_state(state_name)
        gate._pub_neck = MagicMock()
        gate._pub_arm = MagicMock()
        return gate

    def test_normal_passes_neck_command(self):
        gate = self._make_gate("NORMAL")
        gate._on_neck_command_raw(MagicMock())
        gate._pub_neck.publish.assert_called_once()

    def test_normal_passes_arm_command(self):
        gate = self._make_gate("NORMAL")
        gate._on_arm_command_raw(MagicMock())
        gate._pub_arm.publish.assert_called_once()

    def test_caution_passes_servo(self):
        gate = self._make_gate("CAUTION")
        gate._on_neck_command_raw(MagicMock())
        gate._pub_neck.publish.assert_called_once()

    def test_danger_blocks_servo(self):
        gate = self._make_gate("DANGER")
        gate._on_neck_command_raw(MagicMock())
        gate._pub_neck.publish.assert_not_called()
        assert gate._stats.snapshot()["servo_blocked"] == 1

    def test_fault_blocks_servo(self):
        gate = self._make_gate("FAULT")
        gate._on_neck_command_raw(MagicMock())
        gate._pub_neck.publish.assert_not_called()

    def test_safe_stop_blocks_servo(self):
        gate = self._make_gate("SAFE_STOP")
        gate._on_arm_command_raw(MagicMock())
        gate._pub_arm.publish.assert_not_called()

    def test_initializing_blocks_servo(self):
        gate = self._make_gate("INITIALIZING")
        gate._on_neck_command_raw(MagicMock())
        gate._pub_neck.publish.assert_not_called()

    def test_docking_passes_servo(self):
        """Robot may still wave / gesture during docking approach."""
        gate = self._make_gate("DOCKING")
        gate._on_neck_command_raw(MagicMock())
        gate._pub_neck.publish.assert_called_once()

    def test_degraded_passes_servo(self):
        gate = self._make_gate("DEGRADED")
        gate._on_neck_command_raw(MagicMock())
        gate._pub_neck.publish.assert_called_once()

    def test_blocking_increments_warning_count(self):
        gate = self._make_gate("DANGER")
        gate._on_neck_command_raw(MagicMock())
        assert gate._warning_count == 1

    def test_passing_increments_processed_count(self):
        gate = self._make_gate("NORMAL")
        gate._on_neck_command_raw(MagicMock())
        assert gate._processed_count == 1

    def test_blocking_does_not_increment_processed_count(self):
        gate = self._make_gate("SAFE_STOP")
        gate._on_neck_command_raw(MagicMock())
        assert gate._processed_count == 0


# ═══════════════════════════════════════════════════════════════════════════════
# State transitions
# ═══════════════════════════════════════════════════════════════════════════════


class TestStateDynamics:
    """Verify the gate reacts instantly to incoming SafetyState updates."""

    def test_state_update_propagates(self):
        gate = _make_gate_with_state("NORMAL")
        gate._pub_neck = MagicMock()

        # First command in NORMAL: passes
        gate._on_neck_command_raw(MagicMock())
        assert gate._pub_neck.publish.call_count == 1

        # Supervisor transitions to DANGER
        gate._on_safety_state(_STATES["DANGER"])

        # Second command in DANGER: blocked
        gate._on_neck_command_raw(MagicMock())
        assert gate._pub_neck.publish.call_count == 1  # unchanged

    def test_state_update_updates_recv_time(self):
        gate = _make_gate_with_state("NORMAL")
        old_time = gate._state_recv_time
        time.sleep(0.05)
        gate._on_safety_state(_STATES["CAUTION"])
        assert gate._state_recv_time > old_time

    def test_state_update_sets_supervisor_ok(self):
        gate = _make_gate_with_state("NORMAL")
        gate._supervisor_ok = False
        gate._on_safety_state(_STATES["NORMAL"])
        assert gate._supervisor_ok is True

    def test_fault_to_normal_after_reset(self):
        gate = _make_gate_with_state("FAULT")
        gate._pub_neck = MagicMock()
        # While in FAULT — blocked
        gate._on_neck_command_raw(MagicMock())
        gate._pub_neck.publish.assert_not_called()
        # Operator resets → NORMAL
        gate._on_safety_state(_STATES["NORMAL"])
        gate._on_neck_command_raw(MagicMock())
        gate._pub_neck.publish.assert_called_once()
