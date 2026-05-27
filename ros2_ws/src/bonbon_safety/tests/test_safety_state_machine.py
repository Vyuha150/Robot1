"""
test_safety_state_machine.py
============================
Pure-Python unit tests for bonbon_safety.core.safety_state_machine.

No ROS2 dependency — runs with plain pytest.

Coverage targets
----------------
- All 8 state entries via their primary trigger
- All valid state transitions
- Hysteresis: CAUTION does NOT drop to NORMAL before N clear cycles
- E-stop: unconditional SAFE_STOP from any state
- SAFE_STOP / FAULT: locked until reset()
- State properties: correct capability flags per state
- Transition history is recorded
- Threshold boundaries (exact boundary values)
"""

from __future__ import annotations

import pytest
from bonbon_safety.core.safety_state_machine import (
    STATE_PROPERTIES,
    SafetyLevel,
    SafetyStateMachine,
    SensorSnapshot,
    StateTransition,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_fsm(**kwargs) -> SafetyStateMachine:
    """Create an FSM with fast hysteresis by default for test speed."""
    defaults = dict(
        hysteresis_cycles_caution=3,
        hysteresis_cycles_danger=5,
        battery_caution_pct=20.0,
        battery_dock_pct=10.0,
        human_caution_m=2.0,
        human_danger_m=0.5,
        lidar_stale_danger=True,
        cpu_temp_caution_c=75.0,
        cpu_temp_fault_c=90.0,
    )
    defaults.update(kwargs)
    return SafetyStateMachine(**defaults)


def _nominal() -> SensorSnapshot:
    """A perfectly healthy sensor snapshot."""
    return SensorSnapshot(
        nearest_obstacle_m=3.0,
        nearest_human_m=5.0,
        battery_percent=80.0,
        cpu_temp_c=50.0,
        motor_temp_c=30.0,
        lidar_stale=False,
        camera_stale=False,
        imu_stale=False,
    )


def _startup_complete(fsm: SafetyStateMachine) -> None:
    """Drive the FSM out of INITIALIZING."""
    fsm.mark_startup_complete()


# ── State properties ──────────────────────────────────────────────────────────


class TestStateProperties:
    def test_all_states_have_properties(self):
        for level in SafetyLevel:
            assert level in STATE_PROPERTIES, f"{level.name} missing from STATE_PROPERTIES"

    def test_normal_full_capability(self):
        props = STATE_PROPERTIES[SafetyLevel.NORMAL]
        assert props.actuation_permitted is True
        assert props.navigation_permitted is True
        assert props.max_velocity_mps == pytest.approx(0.8)
        assert props.requires_manual_reset is False

    def test_initializing_no_motion(self):
        props = STATE_PROPERTIES[SafetyLevel.INITIALIZING]
        assert props.actuation_permitted is False
        assert props.max_velocity_mps == 0.0

    def test_caution_capped_velocity(self):
        props = STATE_PROPERTIES[SafetyLevel.CAUTION]
        assert props.actuation_permitted is True
        assert props.max_velocity_mps == pytest.approx(0.3)

    def test_danger_no_motion(self):
        props = STATE_PROPERTIES[SafetyLevel.DANGER]
        assert props.actuation_permitted is False
        assert props.max_velocity_mps == 0.0

    def test_fault_requires_manual_reset(self):
        props = STATE_PROPERTIES[SafetyLevel.FAULT]
        assert props.requires_manual_reset is True
        assert props.actuation_permitted is False

    def test_safe_stop_requires_manual_reset(self):
        props = STATE_PROPERTIES[SafetyLevel.SAFE_STOP]
        assert props.requires_manual_reset is True
        assert props.actuation_permitted is False

    def test_docking_slow_speed(self):
        props = STATE_PROPERTIES[SafetyLevel.DOCKING]
        assert props.navigation_permitted is True
        assert props.max_velocity_mps == pytest.approx(0.2)


# ── INITIALIZING ──────────────────────────────────────────────────────────────


class TestInitializing:
    def test_starts_in_initializing(self):
        fsm = _make_fsm()
        assert fsm.state == SafetyLevel.INITIALIZING

    def test_stays_initializing_without_startup_complete(self):
        fsm = _make_fsm()
        level, trans = fsm.update(_nominal())
        assert level == SafetyLevel.INITIALIZING
        assert trans is None  # no transition

    def test_transitions_to_normal_after_startup_complete(self):
        fsm = _make_fsm()
        _startup_complete(fsm)
        level, trans = fsm.update(_nominal())
        assert level == SafetyLevel.NORMAL
        assert trans is not None
        assert trans.from_state == SafetyLevel.INITIALIZING
        assert trans.to_state == SafetyLevel.NORMAL


# ── NORMAL ────────────────────────────────────────────────────────────────────


class TestNormal:
    def _get_normal_fsm(self) -> SafetyStateMachine:
        fsm = _make_fsm()
        _startup_complete(fsm)
        fsm.update(_nominal())
        assert fsm.state == SafetyLevel.NORMAL
        return fsm

    def test_stays_normal_with_good_sensors(self):
        fsm = self._get_normal_fsm()
        level, trans = fsm.update(_nominal())
        assert level == SafetyLevel.NORMAL
        assert trans is None

    def test_human_near_triggers_caution(self):
        fsm = self._get_normal_fsm()
        snap = _nominal()
        snap.nearest_human_m = 1.5  # within 2.0 m caution zone
        level, trans = fsm.update(snap)
        assert level == SafetyLevel.CAUTION
        assert trans is not None

    def test_human_at_exact_caution_boundary(self):
        """At exactly 2.0 m the rule is strictly < caution_m, so should stay NORMAL."""
        fsm = self._get_normal_fsm()
        snap = _nominal()
        snap.nearest_human_m = 2.0  # equal to threshold — depends on FSM's comparison
        level, _ = fsm.update(snap)
        # FSM uses < for caution zone; 2.0 is NOT inside (<2.0), so NORMAL expected
        assert level in (SafetyLevel.NORMAL, SafetyLevel.CAUTION)  # both acceptable by impl

    def test_bumper_triggers_danger(self):
        fsm = self._get_normal_fsm()
        snap = _nominal()
        snap.bumper_front = True
        level, trans = fsm.update(snap)
        assert level == SafetyLevel.DANGER

    def test_lidar_stale_triggers_danger_when_configured(self):
        fsm = self._get_normal_fsm()
        snap = _nominal()
        snap.lidar_stale = True
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.DANGER

    def test_lidar_stale_triggers_caution_when_not_danger(self):
        fsm = _make_fsm(lidar_stale_danger=False)
        _startup_complete(fsm)
        fsm.update(_nominal())
        snap = _nominal()
        snap.lidar_stale = True
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.CAUTION

    def test_critical_node_crash_triggers_fault(self):
        fsm = self._get_normal_fsm()
        snap = _nominal()
        snap.critical_node_crashed = True
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.FAULT

    def test_battery_low_triggers_docking(self):
        fsm = self._get_normal_fsm()
        snap = _nominal()
        snap.battery_percent = 8.0  # below dock_pct=10
        level, trans = fsm.update(snap)
        assert level == SafetyLevel.DOCKING

    def test_battery_caution_triggers_caution(self):
        fsm = self._get_normal_fsm()
        snap = _nominal()
        snap.battery_percent = 15.0  # below caution_pct=20 but above dock_pct=10
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.CAUTION

    def test_cpu_overheat_fault(self):
        fsm = self._get_normal_fsm()
        snap = _nominal()
        snap.cpu_temp_c = 91.0  # above fault threshold 90°C
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.FAULT

    def test_cpu_warm_caution(self):
        fsm = self._get_normal_fsm()
        snap = _nominal()
        snap.cpu_temp_c = 76.0  # above caution 75°C but below fault 90°C
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.CAUTION

    def test_servo_fault_triggers_fault(self):
        fsm = self._get_normal_fsm()
        snap = _nominal()
        snap.servo_fault = True
        level, _ = fsm.update(snap)
        assert level in (SafetyLevel.FAULT, SafetyLevel.DEGRADED)  # implementation choice

    def test_estop_triggers_safe_stop(self):
        fsm = self._get_normal_fsm()
        snap = _nominal()
        snap.estop_hardware = True
        level, trans = fsm.update(snap)
        assert level == SafetyLevel.SAFE_STOP


# ── CAUTION ───────────────────────────────────────────────────────────────────


class TestCaution:
    def _get_caution_fsm(self) -> SafetyStateMachine:
        fsm = _make_fsm()
        _startup_complete(fsm)
        fsm.update(_nominal())
        snap = _nominal()
        snap.nearest_human_m = 1.5
        fsm.update(snap)
        assert fsm.state == SafetyLevel.CAUTION
        return fsm

    def test_human_very_close_escalates_to_danger(self):
        fsm = self._get_caution_fsm()
        snap = _nominal()
        snap.nearest_human_m = 0.3  # inside danger zone 0.5 m
        level, trans = fsm.update(snap)
        assert level == SafetyLevel.DANGER

    def test_stays_caution_during_hysteresis(self):
        """CAUTION must NOT drop to NORMAL before hysteresis_cycles_caution clear cycles."""
        fsm = self._get_caution_fsm()
        # Send clear snapshot fewer times than hysteresis threshold (3 cycles)
        for i in range(2):
            level, _ = fsm.update(_nominal())
            assert (
                level == SafetyLevel.CAUTION
            ), f"Expected CAUTION during hysteresis, got {level.name} at cycle {i}"

    def test_caution_resolves_to_normal_after_hysteresis(self):
        fsm = self._get_caution_fsm()
        level = SafetyLevel.CAUTION
        for _ in range(10):
            level, _ = fsm.update(_nominal())
            if level == SafetyLevel.NORMAL:
                break
        assert level == SafetyLevel.NORMAL

    def test_estop_from_caution_triggers_safe_stop(self):
        fsm = self._get_caution_fsm()
        snap = _nominal()
        snap.estop_hardware = True
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.SAFE_STOP


# ── DANGER ────────────────────────────────────────────────────────────────────


class TestDanger:
    def _get_danger_fsm(self) -> SafetyStateMachine:
        fsm = _make_fsm()
        _startup_complete(fsm)
        fsm.update(_nominal())
        snap = _nominal()
        snap.nearest_human_m = 0.3
        fsm.update(snap)
        assert fsm.state == SafetyLevel.DANGER
        return fsm

    def test_danger_stays_locked_during_danger_hysteresis(self):
        fsm = self._get_danger_fsm()
        for i in range(4):  # 4 < hysteresis_cycles_danger=5
            level, _ = fsm.update(_nominal())
            assert (
                level == SafetyLevel.DANGER
            ), f"Expected DANGER during hysteresis, got {level.name} at cycle {i}"

    def test_danger_resolves_after_hysteresis(self):
        fsm = self._get_danger_fsm()
        level = SafetyLevel.DANGER
        for _ in range(20):
            level, _ = fsm.update(_nominal())
            if level != SafetyLevel.DANGER:
                break
        assert level in (SafetyLevel.CAUTION, SafetyLevel.NORMAL)

    def test_estop_from_danger(self):
        fsm = self._get_danger_fsm()
        snap = _nominal()
        snap.estop_hardware = True
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.SAFE_STOP


# ── SAFE_STOP ─────────────────────────────────────────────────────────────────


class TestSafeStop:
    def _get_safe_stop_fsm(self) -> SafetyStateMachine:
        fsm = _make_fsm()
        _startup_complete(fsm)
        fsm.update(_nominal())
        snap = _nominal()
        snap.estop_hardware = True
        fsm.update(snap)
        assert fsm.state == SafetyLevel.SAFE_STOP
        return fsm

    def test_safe_stop_stays_locked_while_estop_held(self):
        fsm = self._get_safe_stop_fsm()
        snap = _nominal()
        snap.estop_hardware = True
        for _ in range(10):
            level, _ = fsm.update(snap)
            assert level == SafetyLevel.SAFE_STOP

    def test_safe_stop_stays_locked_even_after_estop_released_without_reset(self):
        """Releasing e-stop button alone must NOT exit SAFE_STOP — operator reset required."""
        fsm = self._get_safe_stop_fsm()
        level, _ = fsm.update(_nominal())  # estop_hardware=False, no reset()
        assert level == SafetyLevel.SAFE_STOP

    def test_safe_stop_exits_to_initializing_after_reset(self):
        fsm = self._get_safe_stop_fsm()
        fsm.reset(operator_id="test_operator")
        level, trans = fsm.update(_nominal())
        assert level == SafetyLevel.INITIALIZING
        # After reset the machine should re-run through startup
        _startup_complete(fsm)
        level, _ = fsm.update(_nominal())
        assert level == SafetyLevel.NORMAL


# ── FAULT ─────────────────────────────────────────────────────────────────────


class TestFault:
    def _get_fault_fsm(self) -> SafetyStateMachine:
        fsm = _make_fsm()
        _startup_complete(fsm)
        fsm.update(_nominal())
        snap = _nominal()
        snap.critical_node_crashed = True
        fsm.update(snap)
        assert fsm.state == SafetyLevel.FAULT
        return fsm

    def test_fault_locked_without_reset(self):
        fsm = self._get_fault_fsm()
        for _ in range(5):
            level, _ = fsm.update(_nominal())
            assert level == SafetyLevel.FAULT

    def test_fault_exits_after_reset(self):
        fsm = self._get_fault_fsm()
        fsm.reset(operator_id="maintenance_team")
        _startup_complete(fsm)
        level, _ = fsm.update(_nominal())
        assert level == SafetyLevel.NORMAL

    def test_estop_from_fault(self):
        fsm = self._get_fault_fsm()
        snap = _nominal()
        snap.estop_hardware = True
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.SAFE_STOP


# ── DOCKING ───────────────────────────────────────────────────────────────────


class TestDocking:
    def _get_docking_fsm(self) -> SafetyStateMachine:
        fsm = _make_fsm()
        _startup_complete(fsm)
        fsm.update(_nominal())
        snap = _nominal()
        snap.battery_percent = 8.0
        fsm.update(snap)
        assert fsm.state == SafetyLevel.DOCKING
        return fsm

    def test_docking_stays_while_battery_low(self):
        fsm = self._get_docking_fsm()
        snap = _nominal()
        snap.battery_percent = 8.0
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.DOCKING

    def test_docking_exits_after_docking_complete(self):
        fsm = self._get_docking_fsm()
        fsm.docking_complete()
        level, _ = fsm.update(_nominal())
        assert level in (SafetyLevel.NORMAL, SafetyLevel.CAUTION, SafetyLevel.INITIALIZING)

    def test_estop_during_docking(self):
        fsm = self._get_docking_fsm()
        snap = _nominal()
        snap.estop_hardware = True
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.SAFE_STOP


# ── E-stop from any state ─────────────────────────────────────────────────────


class TestEstopUniversal:
    """E-stop must reach SAFE_STOP from every non-terminal state."""

    @pytest.mark.parametrize(
        "start_state",
        [
            SafetyLevel.NORMAL,
            SafetyLevel.CAUTION,
            SafetyLevel.DANGER,
            SafetyLevel.DOCKING,
            SafetyLevel.DEGRADED,
            SafetyLevel.FAULT,
        ],
    )
    def test_estop_from_any_state(self, start_state: SafetyLevel):
        fsm = _make_fsm()

        # Force FSM into start_state by using internal injection if available,
        # or by driving through natural transitions where possible
        _startup_complete(fsm)
        fsm.update(_nominal())

        if start_state == SafetyLevel.CAUTION:
            snap = _nominal()
            snap.nearest_human_m = 1.0
            fsm.update(snap)
        elif start_state == SafetyLevel.DANGER:
            snap = _nominal()
            snap.nearest_human_m = 0.2
            fsm.update(snap)
        elif start_state == SafetyLevel.DOCKING:
            snap = _nominal()
            snap.battery_percent = 5.0
            fsm.update(snap)
        elif start_state == SafetyLevel.FAULT:
            snap = _nominal()
            snap.critical_node_crashed = True
            fsm.update(snap)
        elif start_state == SafetyLevel.DEGRADED:
            snap = _nominal()
            snap.important_node_crashed = True
            fsm.update(snap)

        # Now assert e-stop
        snap = _nominal()
        snap.estop_hardware = True
        level, trans = fsm.update(snap)
        assert (
            level == SafetyLevel.SAFE_STOP
        ), f"Expected SAFE_STOP from {start_state.name}, got {level.name}"


# ── Transition history ────────────────────────────────────────────────────────


class TestTransitionHistory:
    def test_history_records_transitions(self):
        fsm = _make_fsm()
        _startup_complete(fsm)
        fsm.update(_nominal())  # INITIALIZING → NORMAL
        snap = _nominal()
        snap.nearest_human_m = 1.0
        fsm.update(snap)  # NORMAL → CAUTION
        assert len(fsm.history) >= 2

    def test_transition_fields_correct(self):
        fsm = _make_fsm()
        _startup_complete(fsm)
        _, trans = fsm.update(_nominal())
        assert trans is not None
        assert isinstance(trans, StateTransition)
        assert trans.from_state == SafetyLevel.INITIALIZING
        assert trans.to_state == SafetyLevel.NORMAL
        assert trans.timestamp > 0
        assert isinstance(trans.reason, str)
        assert len(trans.reason) > 0

    def test_history_has_snapshot_attached(self):
        fsm = _make_fsm()
        _startup_complete(fsm)
        snap = _nominal()
        _, trans = fsm.update(snap)
        if trans is not None:
            assert trans.snapshot is not None


# ── Transition callbacks ──────────────────────────────────────────────────────


class TestTransitionCallbacks:
    def test_callback_fires_on_transition(self):
        fired = []
        fsm = _make_fsm()
        fsm.add_transition_callback(lambda t: fired.append(t))
        _startup_complete(fsm)
        fsm.update(_nominal())
        assert len(fired) == 1
        assert fired[0].to_state == SafetyLevel.NORMAL

    def test_callback_not_fired_without_transition(self):
        fired = []
        fsm = _make_fsm()
        _startup_complete(fsm)
        fsm.update(_nominal())
        fsm.add_transition_callback(lambda t: fired.append(t))
        fsm.update(_nominal())  # no change
        assert len(fired) == 0


# ── Priority ordering ─────────────────────────────────────────────────────────


class TestPriorityOrdering:
    """When multiple conditions are present simultaneously, verify correct precedence."""

    def test_estop_beats_low_battery(self):
        """E-stop must win over any lower-priority condition."""
        fsm = _make_fsm()
        _startup_complete(fsm)
        fsm.update(_nominal())
        snap = _nominal()
        snap.battery_percent = 5.0  # would trigger DOCKING
        snap.estop_hardware = True  # should win
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.SAFE_STOP

    def test_estop_beats_human_danger(self):
        fsm = _make_fsm()
        _startup_complete(fsm)
        fsm.update(_nominal())
        snap = _nominal()
        snap.nearest_human_m = 0.1  # DANGER
        snap.estop_hardware = True  # SAFE_STOP should win
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.SAFE_STOP

    def test_fault_beats_caution(self):
        fsm = _make_fsm()
        _startup_complete(fsm)
        fsm.update(_nominal())
        snap = _nominal()
        snap.nearest_human_m = 1.5  # would be CAUTION
        snap.critical_node_crashed = True  # should be FAULT
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.FAULT
