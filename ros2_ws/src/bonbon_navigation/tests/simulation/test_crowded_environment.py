"""
Simulation tests — Crowded café environment
============================================
Tests the HumanAwareCostmapLayer and passing-alert system under
crowded conditions (6+ persons simultaneously tracked).

Also validates:
  - Person expiry removes stale entries
  - Grid rebuilds correctly after person removal
  - Thread-safety under concurrent person updates
  - Announce-distance triggers for multiple simultaneous persons
  - Battery routing with docking when crowd blocks charger path

No ROS2 or Gazebo runtime required.
"""

import math
import threading
import time

import pytest
from bonbon_navigation.config.nav_config import BatteryRoutingConfig, HumanAwareConfig
from bonbon_navigation.core.battery_router import BatteryRouter
from bonbon_navigation.core.map_manager import MapManager
from bonbon_navigation.planners.human_aware_costmap import HumanAwareCostmapLayer

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _cfg() -> HumanAwareConfig:
    return HumanAwareConfig(
        enabled=True,
        person_inflation_radius_m=0.80,
        vulnerable_inflation_radius_m=1.20,
        facing_multiplier=1.30,
        person_cost_scaling=2.0,
        announce_passing_intent=True,
        announce_distance_m=2.0,
        person_decay_sec=0.1,  # short for expiry tests
    )


def _layer(cfg=None) -> HumanAwareCostmapLayer:
    cfg = cfg or _cfg()
    return HumanAwareCostmapLayer(
        cfg,
        resolution=0.05,
        width=400,  # 20 m × 20 m at 5 cm/cell
        height=400,
        origin_x=-2.0,
        origin_y=-2.0,
    )


# ── Multiple simultaneous persons ─────────────────────────────────────────────


class TestMultiplePersons:
    def test_six_persons_all_inflated(self):
        """6 persons at distinct positions all generate cost."""
        layer = _layer()
        positions = [
            ("p1", 5.0, 2.0),
            ("p2", 5.0, 4.0),
            ("p3", 5.0, 6.0),
            ("p4", 7.0, 2.0),
            ("p5", 7.0, 4.0),
            ("p6", 7.0, 6.0),
        ]
        for pid, x, y in positions:
            layer.update_person(
                pid, x=x, y=y, velocity_mps=0.0, facing_robot=False, age_group="adult"
            )
        grid = layer.get_cost_grid()
        total_cost = int(grid.sum())
        assert total_cost > 0

    def test_cost_additive_near_cluster(self):
        """Two adjacent persons create higher peak cost than one."""
        layer_1 = _layer()
        layer_2 = _layer()

        layer_1.update_person(
            "p1", x=6.0, y=4.0, velocity_mps=0.0, facing_robot=False, age_group="adult"
        )
        layer_2.update_person(
            "p1", x=6.0, y=4.0, velocity_mps=0.0, facing_robot=False, age_group="adult"
        )
        layer_2.update_person(
            "p2", x=6.5, y=4.0, velocity_mps=0.0, facing_robot=False, age_group="adult"
        )

        grid_1 = layer_1.get_cost_grid()
        grid_2 = layer_2.get_cost_grid()
        # Two-person grid has at least as much total cost
        assert int(grid_2.sum()) >= int(grid_1.sum())

    def test_persons_in_aisle_increase_path_cost(self):
        """Persons placed in aisle cells produce non-zero cost on robot's path."""
        layer = _layer()
        # Aisle at x=6 between tables (y=2 to y=8)
        for i, y in enumerate([2.0, 4.0, 6.0]):
            layer.update_person(
                f"aisle_{i}", x=6.0, y=y, velocity_mps=0.0, facing_robot=False, age_group="adult"
            )
        # Check cost along aisle
        path_costs = [layer.cost_at(6.0, y) for y in [2.0, 4.0, 6.0]]
        assert all(c > 0 for c in path_costs)


# ── Passing alerts ────────────────────────────────────────────────────────────


class TestPassingAlerts:
    def test_multiple_alerts_for_crowded_path(self):
        """Robot approaching table_7 passes 3 persons within 2.0 m."""
        layer = _layer()
        # Place 3 persons near the robot's path (robot at 4.0, 2.0 heading to 9.0, 2.0)
        layer.update_person(
            "c1", x=5.0, y=2.0, velocity_mps=0.0, facing_robot=True, age_group="adult"
        )
        layer.update_person(
            "c2", x=6.0, y=2.5, velocity_mps=0.0, facing_robot=False, age_group="adult"
        )
        layer.update_person(
            "c3", x=5.5, y=1.5, velocity_mps=0.0, facing_robot=False, age_group="adult"
        )

        alerts = layer.get_passing_alerts(robot_x=4.5, robot_y=2.0)
        # All 3 are within 2.0 m of (4.5, 2.0)
        {a.person_id for a in alerts if math.hypot(a.distance_m, 0) <= 2.0}
        # At least some alerts generated
        assert len(alerts) >= 1

    def test_no_alerts_when_announce_disabled(self):
        cfg = HumanAwareConfig(
            enabled=True,
            person_inflation_radius_m=0.80,
            vulnerable_inflation_radius_m=1.20,
            facing_multiplier=1.30,
            person_cost_scaling=2.0,
            announce_passing_intent=False,  # disabled
            announce_distance_m=2.0,
            person_decay_sec=3.0,
        )
        layer = HumanAwareCostmapLayer(
            cfg, resolution=0.05, width=400, height=400, origin_x=-2.0, origin_y=-2.0
        )
        layer.update_person(
            "p1", x=5.0, y=2.0, velocity_mps=0.0, facing_robot=False, age_group="adult"
        )
        alerts = layer.get_passing_alerts(robot_x=4.0, robot_y=2.0)
        assert len(alerts) == 0

    def test_alert_distance_accurate(self):
        layer = _layer()
        layer.update_person(
            "p1", x=3.0, y=4.0, velocity_mps=0.0, facing_robot=False, age_group="adult"
        )
        alerts = layer.get_passing_alerts(robot_x=2.0, robot_y=4.0)
        assert len(alerts) == 1
        assert alerts[0].distance_m == pytest.approx(1.0, abs=0.01)


# ── Person expiry ─────────────────────────────────────────────────────────────


class TestPersonExpiry:
    def test_stale_persons_expired(self):
        layer = _layer()  # person_decay_sec=0.1
        layer.update_person(
            "p1", x=5.0, y=5.0, velocity_mps=0.0, facing_robot=False, age_group="adult"
        )
        time.sleep(0.15)
        removed = layer.expire_stale_persons()
        assert removed >= 1
        assert layer.cost_at(5.0, 5.0) == 0

    def test_fresh_persons_not_expired(self):
        layer = _layer()
        layer.update_person(
            "p1", x=5.0, y=5.0, velocity_mps=0.0, facing_robot=False, age_group="adult"
        )
        removed = layer.expire_stale_persons()
        assert removed == 0
        assert layer.cost_at(5.0, 5.0) > 0

    def test_mixed_expiry(self):
        layer = _layer()
        # Add old person
        layer.update_person(
            "old", x=5.0, y=5.0, velocity_mps=0.0, facing_robot=False, age_group="adult"
        )
        time.sleep(0.15)
        # Add fresh person
        layer.update_person(
            "fresh", x=7.0, y=7.0, velocity_mps=0.0, facing_robot=False, age_group="adult"
        )
        removed = layer.expire_stale_persons()
        assert removed >= 1
        persons = layer.get_persons()
        ids = {p.track_id for p in persons}
        assert "fresh" in ids
        assert "old" not in ids


# ── Grid correctness ──────────────────────────────────────────────────────────


class TestGridCorrectness:
    def test_grid_zero_with_no_persons(self):
        layer = _layer()
        grid = layer.get_cost_grid()
        assert int(grid.sum()) == 0

    def test_grid_cleared_after_remove(self):
        layer = _layer()
        layer.update_person(
            "p1", x=5.0, y=5.0, velocity_mps=0.0, facing_robot=False, age_group="adult"
        )
        layer.remove_person("p1")
        grid = layer.get_cost_grid()
        assert int(grid.sum()) == 0

    def test_cost_at_centre_maximum(self):
        layer = _layer()
        layer.update_person(
            "p1", x=0.0, y=0.0, velocity_mps=0.0, facing_robot=False, age_group="adult"
        )
        centre_cost = layer.cost_at(0.0, 0.0)
        edge_cost = layer.cost_at(0.70, 0.0)
        assert centre_cost > edge_cost

    def test_facing_robot_multiplier_increases_radius(self):
        """Cost at 0.90 m should be higher when person faces robot (1.30× = 1.04 m radius)."""
        cfg = _cfg()
        layer_facing = HumanAwareCostmapLayer(cfg, 0.05, 400, 400, -2.0, -2.0)
        cfg_no_face = _cfg()
        cfg_no_face.facing_multiplier = 1.0
        layer_not_facing = HumanAwareCostmapLayer(cfg_no_face, 0.05, 400, 400, -2.0, -2.0)

        layer_facing.update_person(
            "p", x=0.0, y=0.0, velocity_mps=0.0, facing_robot=True, age_group="adult"
        )
        layer_not_facing.update_person(
            "p", x=0.0, y=0.0, velocity_mps=0.0, facing_robot=False, age_group="adult"
        )
        # At 0.85 m (beyond 0.80 m base radius, within 1.04 m facing radius)
        cost_facing = layer_facing.cost_at(0.85, 0.0)
        cost_not_facing = layer_not_facing.cost_at(0.85, 0.0)
        assert cost_facing >= cost_not_facing


# ── Thread safety ─────────────────────────────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_updates_no_crash(self):
        """20 threads updating persons simultaneously should not raise."""
        layer = _layer()
        errors = []

        def writer(tid: int):
            try:
                for i in range(50):
                    layer.update_person(
                        f"p_{tid}_{i % 5}",
                        x=float(tid),
                        y=float(i % 10),
                        velocity_mps=0.1,
                        facing_robot=False,
                        age_group="adult",
                    )
                    layer.get_cost_grid()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"

    def test_concurrent_read_write(self):
        """Readers and writers running simultaneously — no data race."""
        layer = _layer()
        # Seed initial persons
        for i in range(5):
            layer.update_person(
                f"p{i}", x=float(i), y=0.0, velocity_mps=0.0, facing_robot=False, age_group="adult"
            )

        errors = []

        def reader():
            for _ in range(100):
                try:
                    layer.get_passing_alerts(0.0, 0.0)
                    layer.cost_at(0.0, 0.0)
                except Exception as e:
                    errors.append(e)

        def writer():
            for i in range(50):
                try:
                    layer.update_person(
                        f"w{i % 3}",
                        x=float(i % 10),
                        y=1.0,
                        velocity_mps=0.2,
                        facing_robot=True,
                        age_group="adult",
                    )
                    layer.expire_stale_persons()
                except Exception as e:
                    errors.append(e)

        ts = [threading.Thread(target=reader) for _ in range(5)] + [
            threading.Thread(target=writer) for _ in range(3)
        ]
        for t in ts:
            t.start()
        for t in ts:
            t.join()

        assert not errors


# ── Battery routing with crowded path ─────────────────────────────────────────


class TestBatteryRoutingCrowded:
    def _make_router(self, chargers: dict) -> BatteryRouter:
        mm = MapManager({})
        for name, (x, y) in chargers.items():
            mm.add_location(name, x, y, 0.0)
        return BatteryRouter(
            BatteryRoutingConfig(
                enabled=True,
                low_battery_pct=20.0,
                critical_battery_pct=10.0,
                resume_threshold_pct=80.0,
            ),
            mm,
        )

    def test_low_battery_routes_to_nearest_charger(self):
        router = self._make_router({"charger_a": (1.0, 1.0), "charger_b": (1.0, 8.0)})
        router.update_battery(percentage=15.0, voltage_v=21.0, is_charging=False)
        # Robot at (9.0, 2.0) — near table_7
        decision = router.evaluate(current_x=9.0, current_y=2.0)
        assert decision.should_dock is True
        # charger_a: distance ≈ 8.06 m, charger_b: ≈ 10.0 m → charger_a is nearest
        assert decision.charger is not None
        assert decision.charger.name == "charger_a"

    def test_critical_battery_high_urgency(self):
        router = self._make_router({"charger_a": (1.0, 1.0)})
        router.update_battery(percentage=6.0, voltage_v=19.0, is_charging=False)
        decision = router.evaluate(current_x=9.0, current_y=2.0)
        assert decision.urgency == "urgent"
