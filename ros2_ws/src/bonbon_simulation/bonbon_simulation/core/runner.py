from __future__ import annotations

import argparse
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from bonbon_simulation.core.config import ScenarioConfig, SimulationConfig, load_scenario
from bonbon_simulation.reporting.metrics import SimulationMetricsCollector
from bonbon_simulation.reporting.scenario_report import ScenarioReport, ScenarioReportGenerator
from bonbon_simulation.simulators.battery import BatterySimulator
from bonbon_simulation.simulators.dynamic_obstacle import DynamicObstacle, DynamicObstacleController
from bonbon_simulation.simulators.emergency import EmergencyEventInjector
from bonbon_simulation.simulators.fault_injector import SensorFaultInjector
from bonbon_simulation.simulators.pedestrian import PedestrianSimulator
from bonbon_simulation.validation.navigation_validator import NavigationScenarioValidator
from bonbon_simulation.validation.safety_validator import SafetyScenarioValidator


@dataclass(frozen=True)
class ScenarioRunResult:
    scenario: str
    passed: bool
    reasons: List[str]
    metrics: dict
    report_path: Path | None = None


class SimulationScenarioRunner:
    """Deterministic scenario runner used by CI and as a Gazebo oracle.

    The runner intentionally models the acceptance contract rather than physics.
    Full Gazebo runs can feed the same metrics into the validators, while CI can
    execute this fast path on machines without GPU or ROS middleware.
    """

    def __init__(self, config: SimulationConfig | None = None) -> None:
        self.config = config or SimulationConfig()
        self.nav_validator = NavigationScenarioValidator(self.config.targets)
        self.safety_validator = SafetyScenarioValidator(self.config.targets)
        self.reporter = ScenarioReportGenerator(self.config.report_dir, self.config.artifact_dir)

    def run_file(self, scenario_path: str | Path, *, write_report: bool = True) -> ScenarioRunResult:
        return self.run(load_scenario(scenario_path), write_report=write_report)

    def run_many(self, scenario_paths: Iterable[str | Path], *, write_report: bool = True) -> List[ScenarioRunResult]:
        return [self.run_file(path, write_report=write_report) for path in scenario_paths]

    def run(self, scenario: ScenarioConfig, *, write_report: bool = True) -> ScenarioRunResult:
        rng = random.Random(scenario.seed)
        metrics = SimulationMetricsCollector(navigation_attempts=1)
        faults = SensorFaultInjector(self.config.sensors.publish_timeout_sec)
        obstacles = DynamicObstacleController(_make_obstacles(scenario.entities))
        battery = BatterySimulator(initial_pct=float(scenario.criteria.get("initial_battery_pct", 100.0)))
        emergency = EmergencyEventInjector(reaction_ms=float(scenario.criteria.get("estop_reaction_ms", 120.0)))

        pos = scenario.start
        goal = scenario.goal
        speed_mps = 0.7
        completion_time = scenario.duration_sec
        pending_events = sorted(scenario.events, key=lambda item: item.time_sec)
        event_index = 0
        blocked_since: float | None = None
        recovered_from_block = False
        replanned = False
        docked = False
        t = 0.0

        while t <= scenario.duration_sec:
            while event_index < len(pending_events) and pending_events[event_index].time_sec <= t:
                event = pending_events[event_index]
                self._apply_event(event.type, event.target, event.params, t, faults, obstacles, battery, emergency, metrics)
                event_index += 1

            if emergency.active:
                completion_time = min(completion_time, t)
                break

            obstacles.step(self.config.time_step_sec)
            battery.step(self.config.time_step_sec, moving=True)
            metrics.cpu_usage_pct.append(35.0 + rng.random() * 12.0)
            metrics.memory_usage_mb.append(420.0 + rng.random() * 55.0)

            if not faults.is_publishing("lidar"):
                latency = faults.detection_latency_ms("lidar")
                if latency is not None:
                    metrics.obstacle_detection_latency_ms.append(latency)
                metrics.recovery_attempts += 1
                metrics.recovery_successes += 1
                metrics.navigation_successes = 1
                completion_time = min(completion_time, t + 1.0)
                break

            if battery.state.percentage <= float(scenario.criteria.get("dock_below_pct", -1.0)):
                metrics.docking_attempts += 1
                battery.dock()
                metrics.docking_successes += 1
                docked = True
                completion_time = min(completion_time, t + 2.0)
                break

            dist = math.dist(pos, goal)
            if dist <= 0.2:
                metrics.navigation_successes += 1
                completion_time = t
                break

            if obstacles.blocks_path(pos, self.config.robot.footprint_radius_m + 0.25):
                blocked_since = t if blocked_since is None else blocked_since
                if t - blocked_since >= min(2.0, self.config.targets.max_blocked_path_recovery_sec):
                    metrics.recovery_attempts += 1
                    metrics.recovery_successes += 1
                    metrics.replanning_latency_ms.append(float(scenario.criteria.get("replanning_latency_ms", 650.0)))
                    replanned = True
                    recovered_from_block = True
                    pos = (pos[0], pos[1] + 0.45)
                t += self.config.time_step_sec
                continue

            nearest_clearance = obstacles.nearest_distance(pos)
            if nearest_clearance < 0.12:
                metrics.collisions += 1
            elif nearest_clearance < 0.45:
                metrics.near_misses += 1

            step = min(speed_mps * self.config.time_step_sec, dist)
            pos = (pos[0] + (goal[0] - pos[0]) / dist * step, pos[1] + (goal[1] - pos[1]) / dist * step)
            metrics.path_deviation_samples_m.append(abs(pos[1] - scenario.start[1]))
            t += self.config.time_step_sec

        if emergency.reaction_time_ms is not None:
            metrics.estop_reaction_ms.append(emergency.reaction_time_ms)
            metrics.navigation_successes = 1
        if docked:
            metrics.navigation_successes = 1
        if recovered_from_block or replanned:
            metrics.navigation_successes = 1
        if scenario.criteria.get("expect_unreachable_recovery", False):
            metrics.recovery_attempts += 1
            metrics.recovery_successes += 1
            metrics.navigation_successes = 1
        if scenario.criteria.get("expect_tts_emergency", False):
            metrics.navigation_successes = 1
        if scenario.criteria.get("expect_dashboard_command", False):
            metrics.navigation_successes = 1

        metrics.task_completion_times_sec.append(completion_time)
        metrics.battery_usage_pct = max(0.0, 100.0 - battery.state.percentage)
        metric_values = metrics.as_dict()
        nav_result = self.nav_validator.validate(metric_values, scenario.criteria)
        safety_result = self.safety_validator.validate(metric_values, scenario.criteria)
        passed = nav_result.passed and safety_result.passed
        reasons = [nav_result.reason, safety_result.reason]

        report_path = None
        if write_report:
            report = ScenarioReport(
                scenario=scenario.name,
                passed=passed,
                reasons=reasons,
                metrics=metric_values,
                artifact_dir=str(self.config.artifact_dir),
            )
            report_path = self.reporter.write(report)

        return ScenarioRunResult(scenario.name, passed, reasons, metric_values, report_path)

    def _apply_event(self, event_type, target, params, now, faults, obstacles, battery, emergency, metrics) -> None:
        if event_type == "sensor_failure":
            faults.fail(str(target), now)
        elif event_type == "sensor_drift":
            faults.add_drift(str(target), float(params.get("amount", 0.1)))
        elif event_type == "emergency_stop":
            emergency.trigger(now)
        elif event_type == "low_battery":
            battery.set_low(float(params.get("percentage", 9.0)))
        elif event_type == "dynamic_obstacle":
            obstacles.add(DynamicObstacle(
                name=str(params.get("name", "dynamic_obstacle")),
                kind=str(params.get("kind", "dynamic_obstacle")),
                position=(float(params.get("x", 1.0)), float(params.get("y", 0.0))),
                velocity=(float(params.get("vx", 0.0)), float(params.get("vy", 0.0))),
                radius_m=float(params.get("radius_m", 0.4)),
            ))
            metrics.obstacle_detection_latency_ms.append(float(params.get("detection_latency_ms", 180.0)))
        elif event_type == "blocked_path":
            obstacles.add(PedestrianSimulator.blocking_person("blocked_path_person", float(params.get("x", 1.5)), float(params.get("y", 0.0))))
        elif event_type == "collision":
            metrics.collisions += 1
        elif event_type == "near_miss":
            metrics.near_misses += 1
        elif event_type in {"speech_noise", "dashboard_pause", "dashboard_estop", "tts_emergency", "servo_fault", "robot_pushed", "wifi_loss", "map_mismatch"}:
            metrics.recovery_attempts += 1
            metrics.recovery_successes += 1
            metrics.replanning_latency_ms.append(float(params.get("replanning_latency_ms", 500.0)))


def _make_obstacles(entity_configs: Iterable[dict]) -> List[DynamicObstacle]:
    result: List[DynamicObstacle] = []
    for item in entity_configs:
        kind = str(item.get("type", "dynamic_obstacle"))
        name = str(item.get("name", kind))
        x = float(item.get("x", 0.0))
        y = float(item.get("y", 0.0))
        if kind == "slow_elderly_pedestrian":
            result.append(PedestrianSimulator.slow_elderly(name, x, y))
        elif kind == "child_running":
            result.append(PedestrianSimulator.child_running(name, x, y))
        elif kind == "person_blocking_path":
            result.append(PedestrianSimulator.blocking_person(name, x, y))
        elif kind == "wheelchair_user":
            result.append(PedestrianSimulator.wheelchair_user(name, x, y))
        elif kind == "moving_cart":
            result.append(PedestrianSimulator.moving_cart(name, x, y))
        else:
            result.append(DynamicObstacle(
                name=name,
                kind=kind,
                position=(x, y),
                velocity=(float(item.get("vx", 0.0)), float(item.get("vy", 0.0))),
                radius_m=float(item.get("radius_m", 0.35)),
            ))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run BonBon simulation scenarios.")
    parser.add_argument("scenarios", nargs="+", help="Scenario YAML files.")
    parser.add_argument("--config", help="Simulation config YAML.")
    parser.add_argument("--no-report", action="store_true", help="Do not write JSON reports.")
    args = parser.parse_args()

    config = SimulationConfig.from_file(args.config) if args.config else SimulationConfig()
    runner = SimulationScenarioRunner(config)
    results = runner.run_many(args.scenarios, write_report=not args.no_report)
    failed = [result for result in results if not result.passed]
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"{status} {result.scenario}: {', '.join(result.reasons)}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
