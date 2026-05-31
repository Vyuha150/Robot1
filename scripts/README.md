# scripts/ — canonical developer & CI entry points

This directory is the **stable interface** the team and CI use. Dev-workflow
scripts are implemented here directly; production-ops scripts delegate to the
battle-tested implementations in `devops/scripts/` (which are also baked into
the Docker images), so there is a single source of truth for each operation.

## Developer workflow (run locally + in CI)

| Script | What it does |
|---|---|
| `lint.sh [--fix]` | `ruff check .` (config in `pyproject.toml`) |
| `typecheck.sh` | `mypy` on the rclpy-free cores (mirrors CI) |
| `test.sh --no-ros2` | run all pure-Python suites (safety, behavior, actuation, spatial, gesture, affective_ai) + scenarios — **no ROS2/hardware** |
| `test.sh` | full suites via `devops/scripts/run_tests.sh` (needs a sourced ROS2 workspace) |
| `build.sh` | colcon build the ROS2 workspace → `devops/scripts/build_ros2.sh` |
| `simulation_smoke_test.sh [scenario]` | headless sim smoke → `devops/scripts/run_simulation_smoke.sh` |
| `validate_config.py --all \| --env <e>` | validate deployment config for one/all environments |

## Production operations (delegate to devops/scripts/)

| Script | Purpose | Safety gate |
|---|---|---|
| `install_dependencies.sh` | system + Python + ROS2 deps | — |
| `deploy_to_robot.sh` | deploy a release to a robot | runs `pre_deploy_check.py`: refuses unless safety supervisor + e-stop + rollback version are available |
| `rollback_robot.sh` | roll back to the previous release | — |
| `health_check.sh` | check the running stack | — |
| `collect_logs.sh` | bundle logs for diagnostics | — |

## Deployment environments

`validate_config.py` and `devops/config/<env>/` support the five targets:
`local_dev`, `simulation`, `lab_robot`, `staging_robot`, `production_robot`.
Each has a `runtime.env` (non-secret metadata) + `services.yaml` (subsystem
profile). Secrets (`BONBON_JWT_SECRET`, `BONBON_ADMIN_PASSWORD`) are **never**
committed — they are injected at runtime and checked with
`validate_config.py --env <e> --require-runtime-secrets` at deploy time.

## CI mapping (.github/workflows/ci.yml)

| CI job | Uses |
|---|---|
| `quality` | `ruff`, `black --check`, `mypy` |
| `python-tests` | `scripts/test.sh --no-ros2`, scenarios, latency budget gate, coverage ≥ 80% |
| `config-validation` | `scripts/validate_config.py --all` |
| `ros2-build-test` | colcon build + `colcon test` + sim smoke |
| `docker-security` | docker build + Trivy scan |

No change is deployable unless every job passes.
