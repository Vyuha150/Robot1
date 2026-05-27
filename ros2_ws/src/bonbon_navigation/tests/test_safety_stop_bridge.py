"""
Tests for bonbon_navigation.safety.safety_stop_bridge
"""

import time

import pytest
from bonbon_navigation.safety.safety_stop_bridge import (
    SAFETY_CAUTION,
    SAFETY_DANGER,
    SAFETY_DEGRADED,
    SAFETY_DOCKING,
    SAFETY_FAULT,
    SAFETY_NORMAL,
    SAFETY_SAFE_STOP,
    GatedVelocity,
    SafetyStopBridge,
)


def _bridge(**kw) -> SafetyStopBridge:
    defaults = dict(
        max_speed_mps=0.80,
        caution_speed_mps=0.30,
        dock_speed_mps=0.15,
        watchdog_timeout_sec=0.2,
    )
    defaults.update(kw)
    return SafetyStopBridge(**defaults)


# ── Blocked states ────────────────────────────────────────────────────────────


class TestBlockedStates:
    @pytest.mark.parametrize("state", [SAFETY_DANGER, SAFETY_FAULT, SAFETY_SAFE_STOP])
    def test_blocked_states_zero_velocity(self, state):
        b = _bridge()
        b.update_safety_state(state)
        gv = b.gate(0.5, 0.3)
        assert gv.linear_mps == 0.0
        assert gv.angular_rps == 0.0
        assert gv.was_blocked is True
        assert gv.was_capped is False

    @pytest.mark.parametrize("state", [SAFETY_DANGER, SAFETY_FAULT, SAFETY_SAFE_STOP])
    def test_blocked_count_increments(self, state):
        b = _bridge()
        b.update_safety_state(state)
        before = b.blocked_count
        b.gate(0.5, 0.0)
        assert b.blocked_count == before + 1

    def test_nav_not_permitted_blocks(self):
        b = _bridge()
        b.update_safety_state(SAFETY_NORMAL, navigation_permitted=False)
        gv = b.gate(0.3, 0.0)
        assert gv.was_blocked is True

    def test_nav_not_permitted_zero_vel_allowed(self):
        """Zero-velocity commands pass even when nav not permitted."""
        b = _bridge()
        b.update_safety_state(SAFETY_NORMAL, navigation_permitted=False)
        gv = b.gate(0.0, 0.0)
        assert gv.was_blocked is False


# ── Normal state ──────────────────────────────────────────────────────────────


class TestNormalState:
    def test_normal_passes_within_max_speed(self):
        b = _bridge()
        b.update_safety_state(SAFETY_NORMAL)
        gv = b.gate(0.5, 0.3)
        assert gv.was_blocked is False
        assert gv.was_capped is False
        assert gv.linear_mps == pytest.approx(0.5)
        assert gv.angular_rps == pytest.approx(0.3)

    def test_normal_caps_at_max_speed(self):
        b = _bridge()
        b.update_safety_state(SAFETY_NORMAL)
        gv = b.gate(1.5, 0.0)  # exceeds 0.80 m/s
        assert gv.was_capped is True
        assert gv.linear_mps == pytest.approx(0.80)

    def test_normal_preserves_direction(self):
        b = _bridge()
        b.update_safety_state(SAFETY_NORMAL)
        gv = b.gate(-1.0, 0.0)
        assert gv.linear_mps == pytest.approx(-0.80)

    def test_normal_zero_velocity_passes(self):
        b = _bridge()
        b.update_safety_state(SAFETY_NORMAL)
        gv = b.gate(0.0, 0.0)
        assert gv.was_blocked is False
        assert gv.linear_mps == 0.0
        assert gv.angular_rps == 0.0


# ── Caution state ─────────────────────────────────────────────────────────────


class TestCautionState:
    def test_caution_caps_at_caution_speed(self):
        b = _bridge()
        b.update_safety_state(SAFETY_CAUTION)
        gv = b.gate(0.5, 0.0)
        assert gv.was_capped is True
        assert gv.linear_mps == pytest.approx(0.30)

    def test_caution_passes_slow_velocity(self):
        b = _bridge()
        b.update_safety_state(SAFETY_CAUTION)
        gv = b.gate(0.20, 0.1)
        assert gv.was_capped is False
        assert gv.linear_mps == pytest.approx(0.20)

    def test_caution_scales_angular_proportionally(self):
        b = _bridge()
        b.update_safety_state(SAFETY_CAUTION)
        # Request 0.6 m/s with 0.4 rad/s angular
        gv = b.gate(0.6, 0.4)
        assert gv.was_capped is True
        expected_scale = 0.30 / 0.6  # 0.5
        assert gv.angular_rps == pytest.approx(0.4 * expected_scale, abs=1e-4)


# ── Degraded state ────────────────────────────────────────────────────────────


class TestDegradedState:
    def test_degraded_same_cap_as_caution(self):
        b = _bridge()
        b.update_safety_state(SAFETY_DEGRADED)
        gv = b.gate(0.5, 0.0)
        assert gv.was_capped is True
        assert gv.linear_mps == pytest.approx(0.30)


# ── Docking state ─────────────────────────────────────────────────────────────


class TestDockingState:
    def test_docking_caps_at_dock_speed(self):
        b = _bridge()
        b.update_safety_state(SAFETY_DOCKING)
        gv = b.gate(0.3, 0.0)
        assert gv.was_capped is True
        assert gv.linear_mps == pytest.approx(0.15)

    def test_docking_passes_very_slow(self):
        b = _bridge()
        b.update_safety_state(SAFETY_DOCKING)
        gv = b.gate(0.10, 0.0)
        assert gv.was_capped is False
        assert gv.linear_mps == pytest.approx(0.10)

    def test_docking_dock_speed_boundary(self):
        b = _bridge()
        b.update_safety_state(SAFETY_DOCKING)
        gv = b.gate(0.15, 0.0)
        assert gv.was_capped is False


# ── Watchdog ──────────────────────────────────────────────────────────────────


class TestWatchdog:
    def test_watchdog_blocks_after_timeout(self):
        b = _bridge(watchdog_timeout_sec=0.05)
        b.update_safety_state(SAFETY_NORMAL)
        time.sleep(0.08)
        gv = b.gate(0.5, 0.0)
        assert gv.was_blocked is True
        assert "watchdog" in gv.reason.lower()

    def test_watchdog_ok_before_timeout(self):
        b = _bridge(watchdog_timeout_sec=2.0)
        b.update_safety_state(SAFETY_NORMAL)
        gv = b.gate(0.5, 0.0)
        assert gv.was_blocked is False

    def test_watchdog_resets_on_update(self):
        b = _bridge(watchdog_timeout_sec=0.05)
        b.update_safety_state(SAFETY_NORMAL)
        time.sleep(0.08)
        # Refresh
        b.update_safety_state(SAFETY_NORMAL)
        gv = b.gate(0.5, 0.0)
        assert gv.was_blocked is False

    def test_is_motion_blocked_watchdog(self):
        b = _bridge(watchdog_timeout_sec=0.05)
        b.update_safety_state(SAFETY_NORMAL)
        time.sleep(0.08)
        assert b.is_motion_blocked is True


# ── Accessors ─────────────────────────────────────────────────────────────────


class TestAccessors:
    def test_safety_state_name(self):
        b = _bridge()
        b.update_safety_state(SAFETY_NORMAL)
        assert b.safety_state_name() == "NORMAL"

    def test_safety_state_name_unknown(self):
        b = _bridge()
        b.update_safety_state(99)
        assert "99" in b.safety_state_name()

    def test_navigation_permitted_property(self):
        b = _bridge()
        b.update_safety_state(SAFETY_NORMAL, navigation_permitted=True)
        assert b.navigation_permitted is True
        b.update_safety_state(SAFETY_NORMAL, navigation_permitted=False)
        assert b.navigation_permitted is False

    def test_safety_state_property(self):
        b = _bridge()
        b.update_safety_state(SAFETY_CAUTION)
        assert b.safety_state == SAFETY_CAUTION


# ── Initializing state ────────────────────────────────────────────────────────


class TestInitializingState:
    def test_initializing_no_update_blocks(self):
        """Before first update, last_update=0; watchdog check should pass
        because _last_update==0 skips the watchdog (first-boot grace)."""
        b = _bridge()
        # _last_update = 0.0 → watchdog check:
        #   if self._last_update > 0 and ... → False → skip watchdog block
        # But INITIALIZING is not in blocked states, and nav_permitted=False
        gv = b.gate(0.5, 0.0)
        # nav_permitted=False by default → blocked
        assert gv.was_blocked is True

    def test_initializing_zero_vel_allowed(self):
        b = _bridge()
        gv = b.gate(0.0, 0.0)
        assert gv.was_blocked is False


# ── GatedVelocity dataclass ───────────────────────────────────────────────────


class TestGatedVelocity:
    def test_gated_velocity_fields(self):
        gv = GatedVelocity(
            linear_mps=0.5,
            angular_rps=0.2,
            was_capped=False,
            was_blocked=False,
            safety_state=SAFETY_NORMAL,
            reason="",
        )
        assert gv.linear_mps == 0.5
        assert gv.angular_rps == 0.2
        assert gv.safety_state == SAFETY_NORMAL
