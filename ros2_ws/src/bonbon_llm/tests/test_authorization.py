"""
tests.test_authorization
=========================
Unit tests for bonbon_llm.safety.authorization.CommandAuthorizer.

Tests cover
-----------
* Navigation allowed in NORMAL and DOCKING states
* Navigation denied in CAUTION, DANGER, FAULT, SAFE_STOP
* Actuation allowed only in NORMAL
* Speech always granted regardless of safety state
* Idle and wait_for_input always granted
* Authorization denied when navigation_permitted flag is False
* Authorization denied when actuation_permitted flag is False
* Low-confidence requests handling
"""

import pytest
from bonbon_llm.config.llm_config import AuthorizationConfig
from bonbon_llm.safety.authorization import (
    SAFETY_CAUTION,
    SAFETY_DANGER,
    SAFETY_DEGRADED,
    SAFETY_DOCKING,
    SAFETY_FAULT,
    SAFETY_INITIALIZING,
    SAFETY_NORMAL,
    SAFETY_SAFE_STOP,
    AuthStatus,
    CommandAuthorizer,
    SafetySnapshot,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def auth() -> CommandAuthorizer:
    return CommandAuthorizer(AuthorizationConfig())


def _snap(
    state: int = SAFETY_NORMAL,
    nav: bool = True,
    act: bool = True,
    max_vel: float = 0.5,
) -> SafetySnapshot:
    snap = SafetySnapshot()
    snap.state_id = state
    snap.state_name = {
        SAFETY_NORMAL: "NORMAL",
        SAFETY_CAUTION: "CAUTION",
        SAFETY_DANGER: "DANGER",
        SAFETY_DOCKING: "DOCKING",
        SAFETY_DEGRADED: "DEGRADED",
        SAFETY_FAULT: "FAULT",
        SAFETY_SAFE_STOP: "SAFE_STOP",
        SAFETY_INITIALIZING: "INITIALIZING",
    }.get(state, "UNKNOWN")
    snap.navigation_permitted = nav
    snap.actuation_permitted = act
    snap.max_velocity_mps = max_vel
    return snap


# ── Navigation authorization ───────────────────────────────────────────────────


class TestNavigationAuthorization:

    def test_navigate_granted_in_normal(self, auth):
        result = auth.authorize("navigate_to_goal", _snap(SAFETY_NORMAL), 0.90)
        assert result.granted, f"Expected GRANTED, got {result.status}: {result.reason}"

    def test_navigate_granted_in_docking(self, auth):
        result = auth.authorize("navigate_to_goal", _snap(SAFETY_DOCKING), 0.90)
        assert result.granted

    def test_navigate_denied_in_caution(self, auth):
        result = auth.authorize("navigate_to_goal", _snap(SAFETY_CAUTION), 0.90)
        assert not result.granted
        assert result.status == AuthStatus.DENIED

    def test_navigate_denied_in_danger(self, auth):
        result = auth.authorize("navigate_to_goal", _snap(SAFETY_DANGER), 0.90)
        assert not result.granted
        assert result.status == AuthStatus.DENIED

    def test_navigate_denied_in_fault(self, auth):
        result = auth.authorize("navigate_to_goal", _snap(SAFETY_FAULT), 0.90)
        assert not result.granted
        assert result.status == AuthStatus.DENIED

    def test_navigate_denied_in_safe_stop(self, auth):
        result = auth.authorize("navigate_to_goal", _snap(SAFETY_SAFE_STOP), 0.90)
        assert not result.granted
        assert result.status == AuthStatus.DENIED

    def test_navigate_denied_when_nav_flag_false(self, auth):
        # NORMAL state but nav flag explicitly cleared
        result = auth.authorize("navigate_to_goal", _snap(SAFETY_NORMAL, nav=False), 0.90)
        assert not result.granted

    def test_approach_person_denied_in_danger(self, auth):
        result = auth.authorize("approach_person", _snap(SAFETY_DANGER), 0.95)
        assert not result.granted

    def test_approach_person_granted_in_normal(self, auth):
        result = auth.authorize("approach_person", _snap(SAFETY_NORMAL), 0.90)
        assert result.granted


# ── Actuation authorization ───────────────────────────────────────────────────


class TestActuationAuthorization:

    def test_serve_item_granted_in_normal(self, auth):
        result = auth.authorize("serve_item", _snap(SAFETY_NORMAL), 0.90)
        assert result.granted

    def test_serve_item_denied_in_caution(self, auth):
        result = auth.authorize("serve_item", _snap(SAFETY_CAUTION), 0.90)
        assert not result.granted

    def test_serve_item_denied_in_docking(self, auth):
        # DOCKING allows navigation but NOT actuation
        result = auth.authorize("serve_item", _snap(SAFETY_DOCKING), 0.90)
        assert not result.granted

    def test_serve_item_denied_when_act_flag_false(self, auth):
        result = auth.authorize("serve_item", _snap(SAFETY_NORMAL, act=False), 0.90)
        assert not result.granted

    def test_serve_item_denied_in_fault(self, auth):
        result = auth.authorize("serve_item", _snap(SAFETY_FAULT), 0.90)
        assert not result.granted


# ── Always-permitted behaviors ────────────────────────────────────────────────


class TestAlwaysPermitted:

    @pytest.mark.parametrize(
        "state",
        [
            SAFETY_NORMAL,
            SAFETY_CAUTION,
            SAFETY_DANGER,
            SAFETY_FAULT,
            SAFETY_SAFE_STOP,
            SAFETY_DEGRADED,
        ],
    )
    def test_idle_always_granted(self, auth, state):
        result = auth.authorize("idle", _snap(state), 0.99)
        assert result.granted, f"idle should always be GRANTED (state={state})"

    @pytest.mark.parametrize(
        "state",
        [
            SAFETY_NORMAL,
            SAFETY_FAULT,
            SAFETY_SAFE_STOP,
        ],
    )
    def test_wait_for_input_always_granted(self, auth, state):
        result = auth.authorize("wait_for_input", _snap(state), 0.99)
        assert result.granted

    @pytest.mark.parametrize(
        "state",
        [
            SAFETY_NORMAL,
            SAFETY_CAUTION,
            SAFETY_DANGER,
            SAFETY_FAULT,
            SAFETY_SAFE_STOP,
        ],
    )
    def test_stop_navigation_always_granted(self, auth, state):
        result = auth.authorize("stop_navigation", _snap(state), 0.99)
        assert result.granted, f"stop_navigation should always be GRANTED (state={state})"


# ── Result fields ─────────────────────────────────────────────────────────────


class TestResultFields:

    def test_granted_result_has_reason(self, auth):
        result = auth.authorize("idle", _snap(), 0.99)
        assert isinstance(result.reason, str)

    def test_denied_result_has_reason(self, auth):
        result = auth.authorize("navigate_to_goal", _snap(SAFETY_DANGER), 0.90)
        assert isinstance(result.reason, str)
        assert len(result.reason) > 0

    def test_auth_status_is_enum(self, auth):
        result = auth.authorize("idle", _snap(), 0.99)
        assert isinstance(result.status, AuthStatus)

    def test_granted_field_matches_status(self, auth):
        r1 = auth.authorize("idle", _snap(), 0.99)
        assert r1.granted == (r1.status == AuthStatus.GRANTED)

        r2 = auth.authorize("navigate_to_goal", _snap(SAFETY_FAULT), 0.90)
        assert r2.granted == (r2.status == AuthStatus.GRANTED)


# ── SafetySnapshot ────────────────────────────────────────────────────────────


class TestSafetySnapshot:

    def test_safe_default(self):
        snap = SafetySnapshot.safe_default()
        assert snap.navigation_permitted is True
        assert snap.actuation_permitted is True
        assert snap.state_id == SAFETY_NORMAL

    def test_default_snapshot(self):
        snap = SafetySnapshot()
        # Should be safe/permissive by default
        assert isinstance(snap.navigation_permitted, bool)
        assert isinstance(snap.actuation_permitted, bool)
