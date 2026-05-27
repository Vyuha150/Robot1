# bonbon_simulation

`bonbon_simulation` is the pre-hardware validation suite for the BonBon service robot. It provides a deterministic CI runner plus Gazebo-ready worlds, robot model assets, scenario definitions, failure injection, metrics, and reports.

No real-world deployment should happen unless the approved simulation scenarios pass.

## Architecture

The suite has two execution modes:

1. Headless CI mode runs `SimulationScenarioRunner` directly from scenario YAML. It validates navigation, safety, sensor fault, speech, TTS, dashboard, docking, and endurance behavior without real hardware or a live Gazebo process.
2. Full simulation mode launches Gazebo, the BonBon robot model, Nav2, RTAB-Map, and the same scenario runner as the validation oracle.

Core components:

- `SimulationScenarioRunner`
- `WorldLauncher`
- `RobotSpawnManager`
- `SensorFaultInjector`
- `DynamicObstacleController`
- `PedestrianSimulator`
- `BatterySimulator`
- `EmergencyEventInjector`
- `NavigationScenarioValidator`
- `SafetyScenarioValidator`
- `SimulationMetricsCollector`
- `ScenarioReportGenerator`
- `SimulationConfig`

## Quick Start

Run deterministic CI scenarios:

```bash
cd ros2_ws/src/bonbon_simulation
python -m pytest tests/ -q
```

Run one scenario from the console entry point after building the workspace:

```bash
ros2 run bonbon_simulation scenario_runner \
  $(ros2 pkg prefix bonbon_simulation)/share/bonbon_simulation/scenarios/hospital_corridor_navigation.yaml \
  --config $(ros2 pkg prefix bonbon_simulation)/share/bonbon_simulation/config/simulation_params.yaml
```

Launch a full headless Gazebo run:

```bash
ros2 launch bonbon_simulation simulation.launch.py \
  world:=hospital_corridor \
  scenario:=hospital_corridor_navigation \
  headless:=true
```

## Documentation

See:

- [Simulation Overview](docs/simulation_overview.md)
- [Setup Guide](docs/setup_guide.md)
- [Gazebo and Isaac Options](docs/gazebo_isaac_options.md)
- [Robot Model Guide](docs/robot_model_guide.md)
- [Sensor Simulation Guide](docs/sensor_simulation_guide.md)
- [Scenario Writing Guide](docs/scenario_writing_guide.md)
- [Failure Injection Guide](docs/failure_injection_guide.md)
- [Metrics Guide](docs/metrics_guide.md)
- [CI Simulation Guide](docs/ci_simulation_guide.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Deployment Checklist](docs/deployment_checklist.md)
