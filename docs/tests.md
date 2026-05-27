# Testing

BonBon uses package-local pytest suites, ROS2 launch/integration tests, simulation tests, and DevOps contract tests.

## Required Test Policy

Run tests for every package you touch.

Required package commands:

```bash
cd ros2_ws/src/bonbon_operator_api
python -m pytest tests/ -q

cd ../bonbon_data_stores
python -m pytest tests/ -q
```

If you touch safety-critical paths, run:

```bash
cd ros2_ws/src/bonbon_operator_api
python -m pytest tests/test_safety_gate.py tests/test_commands.py -q
```

If you touch simulation/deployment:

```bash
cd ros2_ws/src/bonbon_simulation
python -m pytest tests/ -q

cd ../../../..
python -m pytest devops/tests -q
```

## Test Categories

Unit tests:

- pure Python state machines
- validators
- stores/repositories
- command validation
- auth/RBAC
- safety gates
- scenario runners

Integration tests:

- ROS2 launch behavior
- package node interaction
- operator API with ROS2 bridge stubs
- data store/API coupling

Failure injection tests:

- sensor loss
- low battery
- e-stop
- blocked path
- dynamic obstacle
- missing config
- bad release checksum
- service startup failure

Stress tests:

- repeated config validation
- repeated scenario regression
- long-duration simulation
- repeated release version generation

Latency benchmarks:

- emergency stop reaction
- lidar failure detection
- navigation replanning
- TTS/STT/perception/LLM latency metrics
- pre/post deployment checker runtime

Simulation tests:

- robot spawn
- sensor publication
- navigation success
- collision-free navigation
- low battery docking
- dashboard command scenarios
- 8-hour endurance scenario

## CI Pipeline Tests

GitHub Actions performs:

- ruff lint
- black check
- mypy
- rosdep dependency check
- colcon build
- unit tests
- integration tests
- safety tests
- simulation smoke tests
- Docker build
- Trivy security scan
- artifact upload
- signed release workflow

## Current Local Validation Commands

```powershell
.venv\Scripts\python.exe -m pytest devops\tests -q
.venv\Scripts\python.exe -m compileall devops\scripts devops\tests
```

ROS2/Gazebo/colcon validation should run on Ubuntu 22.04 with ROS2 Humble.
