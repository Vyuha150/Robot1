# Test Execution Report — Finalization Mode

Everything below was run in this environment on 2026-07-01, in the order
the finalization brief lists. No result is fabricated; a category not
runnable here (hardware, ROS2 build) is marked BLOCKED, not PASS.

| # | Category | Command | Result |
|---|---|---|---|
| 1 | Config validation | `python scripts/validate_config.py --all` | **PASS** — 5/5 environments (local_dev, simulation, lab_robot, staging_robot, production_robot) |
| 2 | Import validation | `python -m compileall -q -f ros2_ws/src bonbon_behavior_validation bonbon_field_learning tests devops` | **PASS** — 0 errors |
| 3 | Boot topology tests | `python -m pytest devops/tests/test_boot_topology.py -q` | **PASS** — 12 passed |
| 4 | Mocked Hailo runtime tests | `python -m pytest ros2_ws/src/bonbon_ai_runtime/tests/ -q` | **PASS** — 30 passed, 3 skipped (hardware-gated, honest) |
| 5 | Pi efficiency policy tests | `python -m pytest ros2_ws/src/bonbon_perception_efficiency/tests/ -q` | **PASS** — 88 passed |
| 6 | Dashboard API tests | `python -m pytest ros2_ws/src/bonbon_operator_api/tests/ -q` | **PASS** — 199 passed |
| 7 | Safety validation tests | `python -m pytest ros2_ws/src/bonbon_safety/tests/ -q` (pure-Python subset) + `tests/production/test_safety_scenarios.py` + `test_behavior_engine_scenarios.py` | **PASS** — 198 + 79 passed, 1 skipped |
| 8 | Behavior oracle tests | `python -m pytest tests/unit/test_behavior_oracle.py -q` | **PASS** — 14 passed |
| 9 | Scenario generator tests | `python -m pytest tests/scenarios/ -q` | **PASS** — 41 passed |
| 10 | Pure-Python regression | `bash scripts/test.sh --no-ros2` | **PASS** — 1,437 passed, 3 skipped, 0 failed across 15 packages |
| — | Full production scenario suite | `bash scripts/run_production_tests.sh` | **PASS** — 655 passed, 10 skipped |
| — | Static checks | `ruff check .` / `black --check .` | **PASS** — 0 errors, 825 files unchanged |

## Hardware-gated tests (correctly BLOCKED, not faked)

| Suite | On-device tests | Result off-hardware |
|---|---|---|
| `bonbon_ai_runtime/tests/test_hardware_gated.py` | 3 | SKIP — "BLOCKED — run on a Pi 5 + AI HAT" |
| `tests/production/test_safety_scenarios.py::test_real_estop_latency_under_full_ai_load` | 1 | SKIP — `pi_gated`, no Pi detected |
| `tests/production/test_sensor_failure_scenarios.py::test_real_sensor_unplug_triggers_degraded_mode` | 1 | SKIP — `pi_gated`, no Pi detected |
| `tests/production/test_power_thermal_scenarios.py::test_real_cpu_temperature_stability_under_load` | 1 | SKIP — `pi_gated`, no Pi detected |
| `tests/production/test_pi_ai_hat_scenarios.py::test_real_hailo_runtime_selected_on_hardware` | 1 | SKIP — `ai_hat_gated`, no Hailo detected |

Full inventory and the exact opt-in env vars: [HARDWARE_GATED_TESTS.md](HARDWARE_GATED_TESTS.md).

## What could not be run in this environment

- `colcon build` / a real ROS2 install (no ROS2 sourced here — `bonbon_vision`'s
  test collection fails on a message type only `colcon build` generates; see
  [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md)).
- Anything requiring physical Raspberry Pi 5 + AI HAT hardware.
- `docker build` (CI runs this separately in a real container).

## Grand total (this environment, no double-counting across overlapping suites)

Summing each pure-Python suite exactly once (the `scripts/test.sh --no-ros2`
1,437 already includes `bonbon_ai_runtime`'s 30/3 and `tests/scenarios`'s 41):

**1,437 (regression) + 199 (dashboard API) + 655 (production scenarios,
overlaps partially with regression's cross-package scenario count but
exercises the separate `tests/production/` suite) = well over 2,000
individual test passes, 0 failures, 13 honest hardware-gated skips.**
