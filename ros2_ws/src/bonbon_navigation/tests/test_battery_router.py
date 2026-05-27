"""
Tests for bonbon_navigation.core.battery_router
"""

import pytest
from bonbon_navigation.config.nav_config import BatteryRoutingConfig
from bonbon_navigation.core.battery_router import (
    BatteryLevel,
    BatteryRouter,
    BatteryState,
)
from bonbon_navigation.core.map_manager import MapManager

# ── Helpers ───────────────────────────────────────────────────────────────────


def _cfg(**kw) -> BatteryRoutingConfig:
    defaults = dict(
        enabled=True,
        low_battery_pct=20.0,
        critical_battery_pct=10.0,
        resume_threshold_pct=80.0,
    )
    defaults.update(kw)
    return BatteryRoutingConfig(**defaults)


def _map_with_chargers() -> MapManager:
    """MapManager with charger_a and charger_b registered."""
    mm = MapManager({})
    mm.add_location("charger_a", 1.0, 1.0, 0.0)
    mm.add_location("charger_b", 1.0, 8.0, 0.0)
    return mm


def _router(cfg=None, mm=None) -> BatteryRouter:
    return BatteryRouter(cfg or _cfg(), mm or _map_with_chargers())


# ── BatteryLevel classification ───────────────────────────────────────────────


class TestBatteryClassification:
    def test_full_battery_ok(self):
        r = _router()
        r.update_battery(percentage=95.0, voltage_v=25.2, is_charging=False)
        assert r.classify() == BatteryLevel.OK

    def test_at_low_threshold_is_low(self):
        r = _router()
        r.update_battery(percentage=20.0, voltage_v=22.0, is_charging=False)
        assert r.classify() == BatteryLevel.LOW

    def test_below_low_threshold_is_low(self):
        r = _router()
        r.update_battery(percentage=15.0, voltage_v=21.0, is_charging=False)
        assert r.classify() == BatteryLevel.LOW

    def test_at_critical_threshold_is_critical(self):
        r = _router()
        r.update_battery(percentage=10.0, voltage_v=20.0, is_charging=False)
        assert r.classify() == BatteryLevel.CRITICAL

    def test_below_critical_threshold(self):
        r = _router()
        r.update_battery(percentage=5.0, voltage_v=19.5, is_charging=False)
        assert r.classify() == BatteryLevel.CRITICAL

    def test_charging_returns_charging(self):
        r = _router()
        r.update_battery(percentage=50.0, voltage_v=24.0, is_charging=True)
        assert r.classify() == BatteryLevel.CHARGING

    def test_above_resume_threshold_is_ok(self):
        r = _router()
        r.update_battery(percentage=85.0, voltage_v=25.0, is_charging=False)
        assert r.classify() == BatteryLevel.OK

    def test_just_below_ok_boundary_is_low(self):
        r = _router()
        r.update_battery(percentage=19.9, voltage_v=21.5, is_charging=False)
        assert r.classify() == BatteryLevel.LOW


# ── Routing decisions ─────────────────────────────────────────────────────────


class TestRoutingDecisions:
    def test_ok_battery_no_dock(self):
        r = _router()
        r.update_battery(percentage=85.0, voltage_v=25.0, is_charging=False)
        decision = r.evaluate(current_x=5.0, current_y=5.0)
        assert decision.should_dock is False

    def test_low_battery_should_dock(self):
        r = _router()
        r.update_battery(percentage=18.0, voltage_v=21.0, is_charging=False)
        decision = r.evaluate(current_x=5.0, current_y=5.0)
        assert decision.should_dock is True
        assert decision.charger is not None

    def test_critical_battery_urgent(self):
        r = _router()
        r.update_battery(percentage=8.0, voltage_v=19.0, is_charging=False)
        decision = r.evaluate(current_x=5.0, current_y=5.0)
        assert decision.should_dock is True
        assert decision.urgency == "urgent"

    def test_charging_no_dock(self):
        r = _router()
        r.update_battery(percentage=40.0, voltage_v=23.0, is_charging=True)
        decision = r.evaluate(current_x=0.0, current_y=0.0)
        assert decision.should_dock is False

    def test_nearest_charger_selected(self):
        """Router picks the closer charger: charger_a at (1,1) vs charger_b at (1,8)."""
        r = _router()
        r.update_battery(percentage=15.0, voltage_v=20.5, is_charging=False)
        # Robot at (1.0, 1.5) → charger_a is 0.5 m, charger_b is 6.5 m
        decision = r.evaluate(current_x=1.0, current_y=1.5)
        assert decision.charger is not None
        assert decision.charger.name == "charger_a"

    def test_low_battery_routing_active_after_decision(self):
        r = _router()
        r.update_battery(percentage=15.0, voltage_v=20.5, is_charging=False)
        r.evaluate(current_x=5.0, current_y=5.0)
        assert r.routing_active is True

    def test_routing_deactivates_on_resume_charge(self):
        r = _router()
        r.update_battery(percentage=15.0, voltage_v=20.5, is_charging=False)
        r.evaluate(current_x=5.0, current_y=5.0)
        # Now charging and above resume threshold
        r.update_battery(percentage=82.0, voltage_v=25.0, is_charging=True)
        assert r.routing_active is False


# ── Disabled router ───────────────────────────────────────────────────────────


class TestDisabledRouter:
    def test_disabled_never_docks(self):
        r = _router(cfg=_cfg(enabled=False))
        r.update_battery(percentage=1.0, voltage_v=15.0, is_charging=False)
        decision = r.evaluate(0.0, 0.0)
        assert decision.should_dock is False


# ── No chargers ───────────────────────────────────────────────────────────────


class TestNoChargers:
    def test_no_chargers_registered(self):
        mm = MapManager({})  # no chargers
        r = BatteryRouter(_cfg(), mm)
        r.update_battery(percentage=5.0, voltage_v=18.0, is_charging=False)
        decision = r.evaluate(0.0, 0.0)
        assert decision.should_dock is False
        assert decision.charger is None


# ── State accessors ───────────────────────────────────────────────────────────


class TestStateAccessors:
    def test_percentage_property(self):
        r = _router()
        r.update_battery(percentage=55.5, voltage_v=24.1, is_charging=False)
        assert r.percentage == pytest.approx(55.5)

    def test_is_charging_property(self):
        r = _router()
        r.update_battery(percentage=50.0, voltage_v=24.0, is_charging=True)
        assert r.is_charging is True

    def test_get_state_fields(self):
        r = _router()
        r.update_battery(percentage=67.0, voltage_v=24.5, current_a=-2.0, is_charging=False)
        state = r.get_state()
        assert isinstance(state, BatteryState)
        assert state.percentage == pytest.approx(67.0)
        assert state.voltage_v == pytest.approx(24.5)
        assert state.current_a == pytest.approx(-2.0)

    def test_initial_percentage_100(self):
        r = _router()
        assert r.percentage == pytest.approx(100.0)
        assert r.classify() == BatteryLevel.OK


# ── RoutingDecision fields ────────────────────────────────────────────────────


class TestRoutingDecisionFields:
    def test_decision_has_all_fields(self):
        r = _router()
        r.update_battery(percentage=15.0, voltage_v=20.0, is_charging=False)
        d = r.evaluate(5.0, 5.0)
        assert hasattr(d, "should_dock")
        assert hasattr(d, "charger")
        assert hasattr(d, "urgency")
        assert hasattr(d, "level")
        assert hasattr(d, "reason")

    def test_level_matches_classification(self):
        r = _router()
        r.update_battery(percentage=8.0, voltage_v=19.0, is_charging=False)
        d = r.evaluate(5.0, 5.0)
        assert d.level == BatteryLevel.CRITICAL
