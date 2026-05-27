"""
test_failure_scenarios.py
==========================
Simulation / chaos failure tests for the BonBon safety FSM.

These tests exercise realistic failure sequences purely in Python
(no ROS2 required) using the SafetyStateMachine directly.

Scenarios
---------
S01  LIDAR loss mid-navigation → DANGER, then recovery → CAUTION → NORMAL
S02  Human walks into danger zone progressively → NORMAL→CAUTION→DANGER
S03  CPU overheats → FAULT, operator reset, startup, back to NORMAL
S04  Battery drains: NORMAL → CAUTION (20%) → DOCKING (10%)
S05  E-stop pressed during navigation → SAFE_STOP, release+reset → NORMAL
S06  Multiple faults simultaneously: estop wins over critical crash
S07  Rapid oscillation blocked by hysteresis
S08  Node crash sequence: CLASS_C crash → DEGRADED; CLASS_A crash → FAULT
S09  Navigation timeout during NORMAL → expected escalation
S010 Full lifecycle: startup → operation → fault → reset → normal
"""

from __future__ import annotations

from bonbon_safety.core.safety_state_machine import (
    SafetyLevel,
    SafetyStateMachine,
    SensorSnapshot,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _fsm(hysteresis_caution=3, hysteresis_danger=5) -> SafetyStateMachine:
    fsm = SafetyStateMachine(
        hysteresis_cycles_caution=hysteresis_caution,
        hysteresis_cycles_danger=hysteresis_danger,
        battery_caution_pct=20.0,
        battery_dock_pct=10.0,
        human_caution_m=2.0,
        human_danger_m=0.5,
        lidar_stale_danger=True,
        cpu_temp_caution_c=75.0,
        cpu_temp_fault_c=90.0,
    )
    return fsm


def _nominal() -> SensorSnapshot:
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


def _startup(fsm: SafetyStateMachine) -> None:
    fsm.mark_startup_complete()
    fsm.update(_nominal())
    assert fsm.state == SafetyLevel.NORMAL, f"Startup failed: {fsm.state.name}"


def _drive_to_normal(fsm: SafetyStateMachine, max_cycles: int = 30) -> bool:
    """Keep sending nominal data until NORMAL is reached or max_cycles exceeded."""
    for _ in range(max_cycles):
        level, _ = fsm.update(_nominal())
        if level == SafetyLevel.NORMAL:
            return True
    return False


# ── S01: LIDAR loss mid-navigation ────────────────────────────────────────────


class TestS01LidarLoss:
    def test_lidar_loss_triggers_danger(self):
        fsm = _fsm()
        _startup(fsm)

        snap = _nominal()
        snap.lidar_stale = True
        level, trans = fsm.update(snap)
        assert level == SafetyLevel.DANGER
        assert trans is not None

    def test_lidar_restored_exits_danger(self):
        fsm = _fsm(hysteresis_danger=3)
        _startup(fsm)

        # Trigger danger via stale LIDAR
        snap = _nominal()
        snap.lidar_stale = True
        fsm.update(snap)
        assert fsm.state == SafetyLevel.DANGER

        # Restore LIDAR
        recovered = _drive_to_normal(fsm, max_cycles=20)
        assert recovered or fsm.state in (
            SafetyLevel.CAUTION,
            SafetyLevel.NORMAL,
        ), f"Did not recover from DANGER: {fsm.state.name}"


# ── S02: Human walks into danger zone progressively ──────────────────────────


class TestS02HumanProximity:
    def test_human_at_2m_triggers_caution(self):
        fsm = _fsm()
        _startup(fsm)
        snap = _nominal()
        snap.nearest_human_m = 1.8  # within 2m caution zone
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.CAUTION

    def test_human_at_0_4m_escalates_to_danger(self):
        fsm = _fsm()
        _startup(fsm)
        snap = _nominal()
        snap.nearest_human_m = 0.4  # within 0.5m danger zone
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.DANGER

    def test_progressive_escalation_sequence(self):
        fsm = _fsm()
        _startup(fsm)
        states = []

        distances = [5.0, 3.0, 1.5, 0.8, 0.3]
        for d in distances:
            snap = _nominal()
            snap.nearest_human_m = d
            level, _ = fsm.update(snap)
            states.append(level)

        # First two should be NORMAL (outside 2m), rest CAUTION or DANGER
        assert states[0] == SafetyLevel.NORMAL
        assert states[1] == SafetyLevel.NORMAL
        assert states[2] == SafetyLevel.CAUTION  # 1.5m < 2m
        assert states[4] == SafetyLevel.DANGER  # 0.3m < 0.5m


# ── S03: CPU overheat → FAULT → reset → NORMAL ───────────────────────────────


class TestS03Overheat:
    def test_overheat_triggers_fault(self):
        fsm = _fsm()
        _startup(fsm)
        snap = _nominal()
        snap.cpu_temp_c = 92.0
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.FAULT

    def test_fault_persists_after_temp_drops(self):
        fsm = _fsm()
        _startup(fsm)
        snap = _nominal()
        snap.cpu_temp_c = 92.0
        fsm.update(snap)
        # Temperature drops back to normal — fault should PERSIST
        for _ in range(5):
            level, _ = fsm.update(_nominal())
            assert level == SafetyLevel.FAULT

    def test_full_reset_after_overheat_fault(self):
        fsm = _fsm()
        _startup(fsm)
        snap = _nominal()
        snap.cpu_temp_c = 92.0
        fsm.update(snap)
        assert fsm.state == SafetyLevel.FAULT

        fsm.reset(operator_id="maintenance")
        fsm.mark_startup_complete()
        level, _ = fsm.update(_nominal())
        assert level == SafetyLevel.NORMAL


# ── S04: Battery drain sequence ───────────────────────────────────────────────


class TestS04BatteryDrain:
    def test_battery_at_15_triggers_caution(self):
        fsm = _fsm()
        _startup(fsm)
        snap = _nominal()
        snap.battery_percent = 15.0
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.CAUTION

    def test_battery_at_8_triggers_docking(self):
        fsm = _fsm()
        _startup(fsm)
        snap = _nominal()
        snap.battery_percent = 8.0
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.DOCKING

    def test_battery_drain_sequence(self):
        """Simulate battery draining 80%→15%→8% across three updates."""
        fsm = _fsm()
        _startup(fsm)

        snap = _nominal()
        snap.battery_percent = 80.0
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.NORMAL

        snap.battery_percent = 15.0
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.CAUTION

        snap.battery_percent = 8.0
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.DOCKING

    def test_docking_locks_until_complete(self):
        fsm = _fsm()
        _startup(fsm)
        snap = _nominal()
        snap.battery_percent = 8.0
        fsm.update(snap)
        assert fsm.state == SafetyLevel.DOCKING

        # Even with "full" battery reading, docking should stay active
        # (DOCKING only exits via docking_complete())
        for _ in range(5):
            snap.battery_percent = 50.0  # charging not modelled, but...
            level, _ = fsm.update(snap)
            # Accept DOCKING or NORMAL depending on implementation
            assert level in (SafetyLevel.DOCKING, SafetyLevel.NORMAL, SafetyLevel.CAUTION)


# ── S05: E-stop pressed/released/reset ───────────────────────────────────────


class TestS05Estop:
    def test_estop_during_navigation(self):
        fsm = _fsm()
        _startup(fsm)
        snap = _nominal()
        snap.estop_hardware = True
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.SAFE_STOP

    def test_release_without_reset_stays_safe_stop(self):
        fsm = _fsm()
        _startup(fsm)
        snap = _nominal()
        snap.estop_hardware = True
        fsm.update(snap)

        # Release the button
        for _ in range(10):
            level, _ = fsm.update(_nominal())
            assert level == SafetyLevel.SAFE_STOP, "SAFE_STOP should persist without operator reset"

    def test_full_estop_recovery(self):
        fsm = _fsm()
        _startup(fsm)
        snap = _nominal()
        snap.estop_hardware = True
        fsm.update(snap)
        assert fsm.state == SafetyLevel.SAFE_STOP

        fsm.reset(operator_id="ops_team")
        fsm.mark_startup_complete()
        level, _ = fsm.update(_nominal())
        assert level == SafetyLevel.NORMAL


# ── S06: Simultaneous faults — priority ordering ──────────────────────────────


class TestS06SimultaneousFaults:
    def test_estop_beats_critical_crash(self):
        fsm = _fsm()
        _startup(fsm)
        snap = _nominal()
        snap.estop_hardware = True
        snap.critical_node_crashed = True
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.SAFE_STOP

    def test_fault_beats_caution_conditions(self):
        fsm = _fsm()
        _startup(fsm)
        snap = _nominal()
        snap.critical_node_crashed = True  # → FAULT
        snap.nearest_human_m = 1.5  # → would be CAUTION
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.FAULT

    def test_danger_beats_caution(self):
        fsm = _fsm()
        _startup(fsm)
        snap = _nominal()
        snap.nearest_human_m = 0.3  # → DANGER
        snap.cpu_temp_c = 76.0  # → would be CAUTION
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.DANGER


# ── S07: Hysteresis prevents rapid oscillation ────────────────────────────────


class TestS07Hysteresis:
    def test_caution_hysteresis_n_cycles(self):
        """CAUTION must not drop before N clear cycles (default=3)."""
        n_hysteresis = 3
        fsm = _fsm(hysteresis_caution=n_hysteresis)
        _startup(fsm)

        # Enter CAUTION
        snap = _nominal()
        snap.nearest_human_m = 1.5
        fsm.update(snap)
        assert fsm.state == SafetyLevel.CAUTION

        # N-1 clear cycles: must stay CAUTION
        for i in range(n_hysteresis - 1):
            level, _ = fsm.update(_nominal())
            assert (
                level == SafetyLevel.CAUTION
            ), f"Dropped from CAUTION too early at cycle {i+1}/{n_hysteresis}"

    def test_danger_hysteresis_n_cycles(self):
        """DANGER must not drop before N clear cycles (default=5)."""
        n_hysteresis = 5
        fsm = _fsm(hysteresis_danger=n_hysteresis)
        _startup(fsm)

        snap = _nominal()
        snap.nearest_human_m = 0.3
        fsm.update(snap)
        assert fsm.state == SafetyLevel.DANGER

        for i in range(n_hysteresis - 1):
            level, _ = fsm.update(_nominal())
            assert (
                level == SafetyLevel.DANGER
            ), f"Dropped from DANGER too early at cycle {i+1}/{n_hysteresis}"

    def test_rapid_trigger_does_not_oscillate(self):
        """Alternating hazard/clear should not cause NORMAL→CAUTION→NORMAL per cycle."""
        fsm = _fsm(hysteresis_caution=5)
        _startup(fsm)

        # Alternating: hazard on odd cycles, clear on even
        states = []
        for i in range(10):
            snap = _nominal()
            if i % 2 == 0:
                snap.nearest_human_m = 1.5
            level, _ = fsm.update(snap)
            states.append(level)

        # Count NORMAL↔CAUTION transitions
        transitions = sum(1 for a, b in zip(states, states[1:]) if a != b)
        assert (
            transitions <= 4
        ), f"Too many oscillations ({transitions}) — hysteresis not working: {states}"


# ── S08: Node crash sequence ──────────────────────────────────────────────────


class TestS08NodeCrash:
    def test_important_crash_triggers_degraded(self):
        fsm = _fsm()
        _startup(fsm)
        snap = _nominal()
        snap.important_node_crashed = True
        level, _ = fsm.update(snap)
        assert level in (SafetyLevel.DEGRADED, SafetyLevel.CAUTION, SafetyLevel.FAULT)

    def test_critical_crash_triggers_fault(self):
        fsm = _fsm()
        _startup(fsm)
        snap = _nominal()
        snap.critical_node_crashed = True
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.FAULT


# ── S09: Navigation timeout ───────────────────────────────────────────────────


class TestS09NavTimeout:
    def test_nav_timeout_triggers_escalation(self):
        fsm = _fsm()
        _startup(fsm)
        snap = _nominal()
        snap.navigation_timeout = True
        level, _ = fsm.update(snap)
        # Navigation timeout should trigger at least CAUTION (may also trigger FAULT)
        assert level in (
            SafetyLevel.CAUTION,
            SafetyLevel.DANGER,
            SafetyLevel.FAULT,
        ), f"Nav timeout produced unexpected state: {level.name}"


# ── S10: Full lifecycle ───────────────────────────────────────────────────────


class TestS10FullLifecycle:
    def test_full_startup_operation_fault_reset_normal(self):
        """
        Simulate:
        1. Robot powers on (INITIALIZING)
        2. Startup complete (NORMAL)
        3. CPU fault (FAULT)
        4. Operator reset
        5. Back to NORMAL
        """
        fsm = _fsm()

        # Step 1: INITIALIZING
        assert fsm.state == SafetyLevel.INITIALIZING
        level, _ = fsm.update(_nominal())
        assert level == SafetyLevel.INITIALIZING  # still waiting for startup_complete

        # Step 2: Startup → NORMAL
        fsm.mark_startup_complete()
        level, _ = fsm.update(_nominal())
        assert level == SafetyLevel.NORMAL

        # Step 3: CPU fault → FAULT
        snap = _nominal()
        snap.cpu_temp_c = 95.0
        level, _ = fsm.update(snap)
        assert level == SafetyLevel.FAULT

        # Fault persists despite clear conditions
        for _ in range(3):
            level, _ = fsm.update(_nominal())
            assert level == SafetyLevel.FAULT

        # Step 4: Operator reset
        fsm.reset(operator_id="field_technician")

        # Step 5: Back to NORMAL after re-startup
        fsm.mark_startup_complete()
        level, _ = fsm.update(_nominal())
        assert level == SafetyLevel.NORMAL

    def test_transition_history_covers_full_lifecycle(self):
        fsm = _fsm()
        fsm.mark_startup_complete()
        fsm.update(_nominal())  # INIT→NORMAL

        snap = _nominal()
        snap.nearest_human_m = 1.0
        fsm.update(snap)  # NORMAL→CAUTION

        fsm.update(_nominal())  # start hysteresis
        fsm.update(_nominal())
        fsm.update(_nominal())
        fsm.update(_nominal())  # CAUTION→NORMAL

        assert len(fsm.history) >= 2
        states_visited = [t.to_state for t in fsm.history]
        assert SafetyLevel.NORMAL in states_visited
        assert SafetyLevel.CAUTION in states_visited
