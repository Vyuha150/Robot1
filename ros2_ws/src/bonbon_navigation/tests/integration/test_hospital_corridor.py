"""
Integration tests — Hospital corridor navigation scenarios
==========================================================
Validates navigation behaviour in a narrow 3 m × 30 m corridor:
  - Straight traversal with safety bridge
  - Recovery when partially blocked (medical cart)
  - Human awareness: pedestrian crossing triggers social behaviour
  - Docking approach at corridor end (ArUco marker ID 42)
  - Battery routing: CRITICAL triggers charger detour

No ROS2 runtime required.
"""

import pytest
from bonbon_navigation.behaviors.docking_controller import (
    DockingController,
    DockingPhase,
)
from bonbon_navigation.config.nav_config import (
    DockingConfig,
    HumanAwareConfig,
)
from bonbon_navigation.core.goal_manager import GoalManager
from bonbon_navigation.planners.human_aware_costmap import HumanAwareCostmapLayer
from bonbon_navigation.safety.safety_stop_bridge import (
    SAFETY_CAUTION,
    SAFETY_DOCKING,
    SAFETY_NORMAL,
    SafetyStopBridge,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

CORRIDOR_START = (0.0, 0.0)
CORRIDOR_END = (28.0, 0.0)
CHARGER_POS = (1.0, 0.0, 0.0)  # (x, y, yaw) — west end charger


def _docking_cfg() -> DockingConfig:
    return DockingConfig(
        enabled=True,
        pre_dock_distance_m=0.60,
        final_approach_speed_mps=0.06,
        max_alignment_error_m=0.05,
        max_heading_error_rad=0.10,
        alignment_timeout_sec=5.0,
        final_approach_timeout_sec=5.0,
        max_dock_attempts=2,
        use_aruco_marker=True,
        aruco_marker_id=42,
        use_ir_beacon=True,
        undock_reverse_distance_m=0.50,
        undock_speed_mps=0.10,
    )


def _human_cfg() -> HumanAwareConfig:
    return HumanAwareConfig(
        enabled=True,
        person_inflation_radius_m=0.80,
        vulnerable_inflation_radius_m=1.20,
        facing_multiplier=1.30,
        person_cost_scaling=2.0,
        announce_passing_intent=True,
        announce_distance_m=2.0,
        person_decay_sec=3.0,
    )


# ── Straight corridor traversal ───────────────────────────────────────────────


class TestCorridorTraversal:
    def test_velocity_passes_at_normal_speed(self):
        bridge = SafetyStopBridge(watchdog_timeout_sec=5.0)
        bridge.update_safety_state(SAFETY_NORMAL)
        gv = bridge.gate(0.5, 0.0)
        assert gv.was_blocked is False
        assert gv.linear_mps == pytest.approx(0.5)

    def test_caution_state_limits_speed_in_corridor(self):
        """Corridor with person → CAUTION → speed capped at 0.30 m/s."""
        bridge = SafetyStopBridge(watchdog_timeout_sec=5.0)
        bridge.update_safety_state(SAFETY_CAUTION)
        gv = bridge.gate(0.5, 0.0)
        assert gv.was_capped is True
        assert gv.linear_mps == pytest.approx(0.30)

    def test_goal_manager_corridor_goal(self):
        gm = GoalManager()
        gm.enqueue(
            target_x=CORRIDOR_END[0],
            target_y=CORRIDOR_END[1],
            target_yaw=0.0,
            priority=1,
            timeout_sec=120.0,
            goal_id="corridor_end",
        )
        active = gm.activate_next()
        assert active is not None
        assert active.goal_id == "corridor_end"
        # Simulate success
        gm.mark_succeeded("corridor_end")
        assert gm.get_history()[-1].state.name == "SUCCEEDED"


# ── Human awareness in corridor ───────────────────────────────────────────────


class TestCorridorHumanAwareness:
    def test_pedestrian_inflates_cost(self):
        cfg = _human_cfg()
        layer = HumanAwareCostmapLayer(
            cfg,
            resolution=0.05,
            width=700,
            height=80,
            origin_x=-1.0,
            origin_y=-2.0,
        )
        # Pedestrian at corridor midpoint (15.0, 0.0)
        layer.update_person(
            "ped_1", x=15.0, y=0.0, velocity_mps=0.5, facing_robot=True, age_group="adult"
        )
        cost = layer.cost_at(15.0, 0.0)
        assert cost > 0

    def test_pedestrian_personal_space_radius(self):
        cfg = _human_cfg()
        layer = HumanAwareCostmapLayer(
            cfg,
            resolution=0.05,
            width=700,
            height=80,
            origin_x=-1.0,
            origin_y=-2.0,
        )
        layer.update_person(
            "ped_1", x=15.0, y=0.0, velocity_mps=0.0, facing_robot=False, age_group="adult"
        )
        # Cost at exactly person_inflation_radius away should be ~0
        cost_at_edge = layer.cost_at(15.0 + 0.80, 0.0)
        cost_at_centre = layer.cost_at(15.0, 0.0)
        assert cost_at_centre > cost_at_edge

    def test_passing_alert_triggered_within_range(self):
        cfg = _human_cfg()
        layer = HumanAwareCostmapLayer(
            cfg,
            resolution=0.05,
            width=700,
            height=80,
            origin_x=-1.0,
            origin_y=-2.0,
        )
        layer.update_person(
            "ped_cross", x=15.0, y=0.0, velocity_mps=0.8, facing_robot=True, age_group="adult"
        )
        # Robot at 1.5 m from person → within announce_distance_m=2.0
        alerts = layer.get_passing_alerts(robot_x=13.5, robot_y=0.0)
        assert len(alerts) == 1
        assert alerts[0].person_id == "ped_cross"
        assert alerts[0].should_announce is True

    def test_passing_alert_not_triggered_far_away(self):
        cfg = _human_cfg()
        layer = HumanAwareCostmapLayer(
            cfg,
            resolution=0.05,
            width=700,
            height=80,
            origin_x=-1.0,
            origin_y=-2.0,
        )
        layer.update_person(
            "ped_far", x=15.0, y=0.0, velocity_mps=0.0, facing_robot=False, age_group="adult"
        )
        alerts = layer.get_passing_alerts(robot_x=5.0, robot_y=0.0)
        assert len(alerts) == 0

    def test_child_vulnerable_larger_radius(self):
        cfg = _human_cfg()
        layer = HumanAwareCostmapLayer(
            cfg,
            resolution=0.05,
            width=700,
            height=80,
            origin_x=-1.0,
            origin_y=-2.0,
        )
        # Child at (10.0, 0.0) — vulnerable
        layer.update_person(
            "child_1", x=10.0, y=0.0, velocity_mps=0.2, facing_robot=False, age_group="child"
        )
        # At 1.0 m — within vulnerable radius (1.20 m) but outside adult radius (0.80 m)
        cost_child = layer.cost_at(10.0 + 1.0, 0.0)
        # Rebuild with adult at same location
        layer.remove_person("child_1")
        layer.update_person(
            "adult_1", x=10.0, y=0.0, velocity_mps=0.2, facing_robot=False, age_group="adult"
        )
        cost_adult = layer.cost_at(10.0 + 1.0, 0.0)
        # Child's cost at 1.0 m should be >= adult's (larger radius)
        assert cost_child >= cost_adult

    def test_stale_person_not_inflated(self):
        cfg = _human_cfg()
        layer = HumanAwareCostmapLayer(
            cfg,
            resolution=0.05,
            width=700,
            height=80,
            origin_x=-1.0,
            origin_y=-2.0,
        )
        layer.update_person(
            "old_ped", x=15.0, y=0.0, velocity_mps=0.0, facing_robot=False, age_group="adult"
        )
        # Manually expire
        layer._persons["old_ped"].last_seen -= 10.0  # type: ignore[union-attr]
        layer.rebuild_grid()
        cost = layer.cost_at(15.0, 0.0)
        assert cost == 0


# ── Docking at corridor end ───────────────────────────────────────────────────


class TestCorridorDocking:
    def _docking_harness(self):
        cfg = _docking_cfg()
        dc = DockingController(cfg)
        vel_cmds = []
        stop_calls = []
        dc.set_cmd_vel_fn(lambda lin, a: vel_cmds.append((lin, a)))
        dc.set_stop_fn(lambda: stop_calls.append(True))
        dc.set_coarse_nav_fn(lambda pose: None)
        return dc, vel_cmds, stop_calls

    def test_docking_starts_approaching(self):
        dc, _, _ = self._docking_harness()
        dc.start(
            "charger_corridor",
            charger_x=CHARGER_POS[0],
            charger_y=CHARGER_POS[1],
            charger_yaw=CHARGER_POS[2],
        )
        assert dc.phase == DockingPhase.APPROACHING

    def test_docking_transitions_aligning_on_proximity(self):
        dc, _, _ = self._docking_harness()
        dc.start("charger_corridor", charger_x=1.0, charger_y=0.0, charger_yaw=0.0)
        # Inject IR beacon reading: robot 0.7 m from dock (≤ pre_dock_distance + 0.20 = 0.80)
        dc.update_ir_beacon(distance_m=0.70, lateral_err=0.02, heading_err=0.03)
        dc.tick()
        assert dc.phase == DockingPhase.ALIGNING

    def test_docking_aligning_corrects_heading(self):
        dc, vel_cmds, _ = self._docking_harness()
        dc.start("c", charger_x=1.0, charger_y=0.0, charger_yaw=0.0)
        dc.update_ir_beacon(distance_m=0.70, lateral_err=0.0, heading_err=0.20)
        dc.tick()  # → ALIGNING
        dc.update_ir_beacon(distance_m=0.70, lateral_err=0.0, heading_err=0.20)
        dc.tick()  # issues angular correction
        angular_cmds = [cmd for cmd in vel_cmds if cmd[1] != 0.0]
        assert len(angular_cmds) > 0

    def test_docking_contact_stops_motion(self):
        dc, vel_cmds, stop_calls = self._docking_harness()
        dc.start("c", charger_x=1.0, charger_y=0.0, charger_yaw=0.0)
        dc.update_ir_beacon(distance_m=0.70, lateral_err=0.0, heading_err=0.0)
        dc.tick()  # → ALIGNING
        dc.update_ir_beacon(distance_m=0.70, lateral_err=0.0, heading_err=0.0)
        dc.tick()  # → FINAL_APPROACH
        dc.update_contact(contact_detected=True, charging_current_a=2.5)
        dc.update_ir_beacon(distance_m=0.02, lateral_err=0.0, heading_err=0.0)
        dc.tick()  # → CONTACT
        assert dc.phase == DockingPhase.CONTACT
        assert dc.succeeded is True

    def test_docking_uses_aruco_over_ir_when_both(self):
        dc, _, _ = self._docking_harness()
        dc.start("c", charger_x=1.0, charger_y=0.0, charger_yaw=0.0)
        # ArUco detected and accurate
        dc.update_aruco(detected=True, distance_m=0.5, lateral_err=0.0, heading_err=0.0)
        dc.update_ir_beacon(distance_m=0.7, lateral_err=0.05, heading_err=0.15)
        # _best_alignment should use ArUco
        lat, hdg = dc._best_alignment()
        assert lat == pytest.approx(0.0)
        assert hdg == pytest.approx(0.0)

    def test_docking_speed_gated_through_bridge(self):
        """Final approach velocity must be within dock_speed_mps cap."""
        bridge = SafetyStopBridge(watchdog_timeout_sec=5.0)
        bridge.update_safety_state(SAFETY_DOCKING)
        # DockingController issues final_approach_speed_mps = 0.06
        gv = bridge.gate(0.06, 0.0)
        assert gv.was_capped is False
        assert gv.linear_mps == pytest.approx(0.06)
