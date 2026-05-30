# BonBon Test Strategy

Industry-grade test plan for the BonBon service robot. Defines the test
categories, where each lives, the shared utilities/mocks, CI commands, and
coverage targets. The goal: **no safety claim without a test that proves it.**

---

## 1. Test architecture

Three layers, each runnable independently:

```
            ┌─────────────────────────────────────────────────────────┐
  Layer 3   │ Behavioural scenario tests (cross-package, no hardware)   │
            │   bonbon_safety/tests/scenarios/test_realworld_scenarios  │
            │   — drive the real decision/safety cores end-to-end       │
            └─────────────────────────────────────────────────────────┘
            ┌─────────────────────────────────────────────────────────┐
  Layer 2   │ Per-package integration tests + ROS2 node / launch tests  │
            │   <pkg>/tests/integration/, launch_testing where present  │
            └─────────────────────────────────────────────────────────┘
            ┌─────────────────────────────────────────────────────────┐
  Layer 1   │ Per-module unit tests (pure logic, deterministic)         │
            │   <pkg>/tests/test_*.py                                   │
            └─────────────────────────────────────────────────────────┘
```

Layers 1 and 3 run in a **plain Python** environment (no ROS2/hardware) — the
decision/safety cores are deliberately rclpy-free. Layer 2 ROS2 node/launch
tests require a sourced workspace (CI `ros2-build-test` job).

---

## 2. Test categories → where implemented

| # | Category | Location / mechanism | Status |
|---|---|---|---|
| 1 | Unit tests | every `<pkg>/tests/test_*.py` (~110 files) | ✅ |
| 2 | Integration tests | `<pkg>/tests/integration/` (actuation, spatial, affective, gesture, behavior, hal, perception, safety) | ✅ |
| 3 | ROS2 node tests | node modules tested via stubs (affective) / launch_testing (safety, perception) | ✅ / 🔧 |
| 4 | Launch tests | `bonbon_bringup/tests/test_bringup_launch.py` (+ ROS2 functional when sourced) | ✅ |
| 5 | Simulation tests | `bonbon_simulation/tests/` + `scenarios/*.yaml` + Gazebo worlds | ✅ |
| 6 | Failure-injection tests | `bonbon_safety/tests/test_fault_handler.py`, `test_failure_catalog.py`; sim `fault_injector` | ✅ |
| 7 | Safety tests | `bonbon_safety/tests/test_safety_state_machine.py`, `test_safety_gate.py`, scenarios 15–21 | ✅ |
| 8 | Latency benchmark tests | `bonbon_safety/tests/benchmarks/bench_hotpaths.py` + per-pkg `bench_*` | ✅ |
| 9 | Regression tests | budget/catalog integrity tests pin behaviour (perf_targets, failure_catalog) | ✅ |
| 10 | HAL mock tests | `bonbon_hal/tests/` mock drivers; testkit `sensor_snapshot` faults | ✅ |

---

## 3. Test file structure (convention)

```
<package>/
  tests/
    __init__.py
    conftest.py                 # stubs/fixtures (e.g. affective ROS2 stubs)
    test_<module>.py            # unit tests, one per core module
    integration/
      __init__.py
      test_<pkg>_integration.py # cross-module pipeline
    benchmarks/                 # latency benches (optional)
      bench_<pkg>.py
  pytest.ini
```

Cross-package behavioural tests live in `bonbon_safety/tests/scenarios/`.

---

## 4. Test utilities & mock hardware

Shared, reusable, hardware-free — in `bonbon_safety/bonbon_safety/testkit/scenario.py`:

| Helper | Purpose |
|---|---|
| `seed(n)` | deterministic RNG (autouse fixture in scenario conftest) — **no flaky tests** |
| `person(distance, category, approaching, …)` | tracked-person signal for spatial cores |
| `hand(gesture)` | 21-pt hand landmarks for `stop_palm/wave/pointing/thumbs_up/fist` |
| `sensor_snapshot(**faults)` | `SensorSnapshot` for the safety FSM with injectable faults |
| `assert_at_least`, `assert_safe_response` | fallback-level / spatial-response assertions |

Hardware itself is mocked at the driver layer: every HAL device has a
`mock_*_driver.py` (camera, lidar, imu, battery, servo, microphone, estop,
speaker), selected with `simulation:=true`. AI backends fall back to mock
backends when models are absent. **No test touches real hardware.**

---

## 5. Real-world scenario coverage (30/30)

`bonbon_safety/tests/scenarios/test_realworld_scenarios.py` — each test carries a
docstring with purpose / input / expected / pass-fail / safety relevance.

| # | Scenario | Safety relevance |
|---|---|---|
| 1 | happy greeting | low |
| 2 | user waves | low |
| 3 | user raises hand | HIGH (attention → supervisor) |
| 4 | stop palm | CRITICAL (halt signal) |
| 5 | user points | low |
| 6 | user angry | medium (de-escalate) |
| 7 | user distressed | HIGH |
| 8 | confusing command | HIGH (no motion on ambiguity) |
| 9 | child runs near | CRITICAL (freeze arms) |
| 10 | elderly slow | medium |
| 11 | person blocks path | medium |
| 12 | wheelchair clearance | HIGH |
| 13 | too close to human | CRITICAL (social stop) |
| 14 | restricted zone entry | HIGH (escalate) |
| 15 | camera lost | medium (CAUTION) |
| 16 | microphone lost | low |
| 17 | LIDAR lost | CRITICAL (→ DANGER) |
| 18 | IMU drift | medium |
| 19 | servo fault | HIGH (→ DEGRADED) |
| 20 | low battery | medium |
| 21 | emergency stop | CRITICAL (→ SAFE_STOP) |
| 22 | LLM hallucinated movement | CRITICAL (blocked) |
| 23 | dashboard unsafe command | CRITICAL (rejected) |
| 24 | noisy environment | HIGH |
| 25 | low light | low |
| 26 | multiple people speaking | HIGH |
| 27 | conflicting gestures | CRITICAL (safety wins) |
| 28 | vector DB unavailable | low (DEGRADED) |
| 29 | SQLite locked | low (DEGRADED) |
| 30 | shutdown during write | medium (SAFE_PAUSE) |

---

## 6. CI test commands

```bash
# ── Layer 1 + 3: pure-Python (no ROS2) — fast, run on every push ──
python -m pytest ros2_ws/src/bonbon_safety/tests \
                 ros2_ws/src/bonbon_actuation/tests \
                 ros2_ws/src/bonbon_spatial/tests \
                 ros2_ws/src/bonbon_affective_ai/tests \
                 ros2_ws/src/bonbon_gesture/tests \
                 ros2_ws/src/bonbon_behavior_engine/tests \
                 -q -p no:cacheprovider \
                 --ignore=ros2_ws/src/bonbon_safety/tests/integration \
                 --ignore=ros2_ws/src/bonbon_safety/tests/test_watchdog.py \
                 --ignore=ros2_ws/src/bonbon_safety/tests/test_safety_gate.py

# ── Scenario suite only ──
python -m pytest ros2_ws/src/bonbon_safety/tests/scenarios -q

# ── Latency benchmark gate (fails CI if a budget is exceeded) ──
python -m pytest ros2_ws/src/bonbon_safety/tests/benchmarks/bench_hotpaths.py -q

# ── Layer 2: ROS2 node/launch/sim (sourced workspace, CI ros2 job) ──
cd ros2_ws && colcon build && . install/setup.bash
colcon test --packages-select bonbon_safety bonbon_hal bonbon_simulation
colcon test-result --verbose

# ── Coverage ──
python -m pytest <paths above> \
    --cov=bonbon_safety --cov=bonbon_behavior_engine --cov=bonbon_actuation \
    --cov=bonbon_spatial --cov=bonbon_gesture --cov=bonbon_affective_ai \
    --cov-report=term-missing --cov-report=html --cov-fail-under=80
```

(Requires `pytest-cov`. The 3 pre-existing rclpy-dependent node tests in
`bonbon_safety` — watchdog, safety_gate, safety_integration — are excluded from
the pure-Python job and run in the sourced ROS2 job.)

---

## 7. Coverage targets

- **Core decision/safety logic: ≥ 80 %** line coverage (the rclpy-free modules
  under each package's `core/`, `logic/`, `fusion/`, `analyzers/`). These hold
  the safety-critical behaviour and are fully unit + scenario tested.
- **Node modules**: covered by ROS2 node/launch tests in the sourced job;
  excluded from the line-coverage gate because they are thin I/O wiring over the
  tested cores.
- **Regression protection**: `test_failure_catalog.py` and `test_perf_targets.py`
  pin the failure-mode set and latency budgets, so neither can silently change.

---

## 8. Anti-flakiness rules

1. Every randomised input is seeded (`testkit.seed`, autouse).
2. No `time.sleep`-based timing assertions — injectable clocks everywhere
   (Watchdog, BlockageDetector, OperatorAlerter, LatencyTimer).
3. Continuous-sensor behaviour (FSM hysteresis) is driven to settle over a fixed
   number of cycles, never asserted on a single transient frame.
4. ML/hardware are mocked deterministically; benchmarks measure decision logic,
   not wall-clock-sensitive model inference.
