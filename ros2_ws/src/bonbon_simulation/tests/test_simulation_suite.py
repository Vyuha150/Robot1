from __future__ import annotations

import json
from pathlib import Path

import pytest
from bonbon_simulation.core.config import SimulationConfig, load_scenario
from bonbon_simulation.core.robot_spawn_manager import RobotSpawnManager
from bonbon_simulation.core.world_launcher import WorldLauncher
from bonbon_simulation.simulators.fault_injector import SensorFaultInjector
from conftest import scenario_path


def run_named(runner, package_root: Path, name: str):
    result = runner.run_file(scenario_path(package_root, name), write_report=True)
    assert result.passed, result.reasons
    return result


def test_basic_robot_spawn(package_root: Path):
    cfg = SimulationConfig.from_file(package_root / "config" / "simulation_params.yaml")
    manager = RobotSpawnManager(
        package_root / "models" / "bonbon_robot" / "urdf" / "bonbon_robot.urdf.xacro", cfg.robot
    )
    request = manager.create_spawn_request(x=1.0, y=2.0, yaw=0.5)
    assert request.robot_name == "bonbon"
    assert request.pose == (1.0, 2.0, 0.5)
    assert request.parameters["footprint_radius_m"] > 0.0


def test_all_sensors_publishing():
    faults = SensorFaultInjector()
    for sensor in ["lidar", "imu", "camera", "microphone", "servo", "wifi"]:
        assert faults.is_publishing(sensor)


def test_navigation_goal_success(runner, package_root: Path):
    result = run_named(runner, package_root, "hospital_corridor_navigation")
    assert result.metrics["navigation_success_rate"] >= 0.95


def test_collision_free_navigation(runner, package_root: Path):
    result = run_named(runner, package_root, "hospital_corridor_navigation")
    assert result.metrics["collision_count"] == 0


def test_emergency_stop_reaction(runner, package_root: Path):
    result = run_named(runner, package_root, "emergency_stop")
    assert result.metrics["emergency_stop_reaction_time_ms"] < 300


def test_lidar_failure_detection(runner, package_root: Path):
    result = run_named(runner, package_root, "lidar_failure_navigation")
    assert result.metrics["obstacle_detection_latency_ms"] <= 1000


def test_camera_failure_detection(runner, package_root: Path):
    result = run_named(runner, package_root, "camera_failure_interaction")
    assert result.metrics["navigation_success_rate"] >= 0.95


def test_low_battery_docking(runner, package_root: Path):
    result = run_named(runner, package_root, "low_battery_docking")
    assert result.metrics["docking_success_rate"] >= 0.95


def test_blocked_path_recovery(runner, package_root: Path):
    result = run_named(runner, package_root, "blocked_path_recovery")
    assert result.metrics["recovery_success_rate"] >= 0.95


def test_child_sudden_obstacle(runner, package_root: Path):
    result = run_named(runner, package_root, "child_sudden_obstacle")
    assert result.metrics["obstacle_detection_latency_ms"] < 300


def test_slow_pedestrian_behavior(runner, package_root: Path):
    result = run_named(runner, package_root, "elderly_slowdown")
    assert result.metrics["collision_count"] == 0


def test_dynamic_obstacle_replanning(runner, package_root: Path):
    result = run_named(runner, package_root, "dynamic_obstacle_replanning")
    assert result.metrics["replanning_latency_ms"] <= 1000


def test_map_mismatch_recovery(runner, package_root: Path):
    result = run_named(runner, package_root, "map_mismatch")
    assert result.metrics["recovery_success_rate"] >= 0.95


def test_dashboard_command_simulation(runner, package_root: Path):
    result = run_named(runner, package_root, "dashboard_pause_command")
    assert result.metrics["navigation_success_rate"] >= 0.95


def test_tts_emergency_announcement(runner, package_root: Path):
    result = run_named(runner, package_root, "tts_emergency_announcement")
    assert result.metrics["navigation_success_rate"] >= 0.95


def test_servo_fault_event(runner, package_root: Path):
    result = run_named(runner, package_root, "servo_fault_interaction")
    assert result.metrics["recovery_success_rate"] >= 0.95


def test_robot_pushed_event(runner, package_root: Path):
    result = run_named(runner, package_root, "robot_pushed")
    assert result.metrics["replanning_latency_ms"] <= 1000


@pytest.mark.endurance
def test_long_duration_stability(runner, package_root: Path):
    result = run_named(runner, package_root, "eight_hour_endurance")
    assert result.metrics["collision_count"] == 0


def test_repeated_scenario_regression(runner, package_root: Path):
    path = scenario_path(package_root, "hospital_corridor_navigation")
    results = [runner.run_file(path, write_report=False) for _ in range(5)]
    assert all(result.passed for result in results)
    assert len({json.dumps(result.metrics, sort_keys=True) for result in results}) == 1


def test_ci_headless_run(runner, package_root: Path):
    world = WorldLauncher(package_root / "worlds").plan("hospital_corridor", headless=True)
    scenario = load_scenario(scenario_path(package_root, "hospital_corridor_navigation"))
    result = runner.run(scenario, write_report=True)
    assert world.headless is True
    assert "hospital_corridor.world" in str(world.world_path)
    assert result.report_path and result.report_path.exists()
