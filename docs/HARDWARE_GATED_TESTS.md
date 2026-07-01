# Hardware-Gated Tests

The complete inventory of tests that require real hardware to actually
run, and the exact rule that keeps them from ever reporting a fake PASS.

## The rule

A hardware-gated test is decorated with a `pytest.mark.skipif` whose
condition checks (a) an explicit opt-in environment variable, **and** (b)
a **real** detector — never a mock — confirming the hardware is actually
present. Both false, or either false, the test **SKIPs** with a message
that says exactly what's missing and that this is "BLOCKED, not failed."
There is no code path that reports PASS without both conditions true.

```python
# tests/production/_hardware_gates.py
pi_gated = pytest.mark.skipif(not (_PI_HW_OPT_IN and _ON_PI), reason=...)
ai_hat_gated = pytest.mark.skipif(not (_HAILO_HW_OPT_IN and _REAL.usable), reason=...)
```

`_ON_PI` reads `/proc/device-tree/model` for "raspberry pi". `_REAL` is
`HailoDeviceDetector().detect()` — the same real (no mock) detector class
`bonbon_ai_runtime`'s own hardware-gated tests use.

## Full inventory (7 on-device tests total)

| Test | File | Gate | Opt-in |
|---|---|---|---|
| `test_hailo_device_detected_on_hardware` | `bonbon_ai_runtime/tests/test_hardware_gated.py` | `ai_hat_gated` | `BONBON_HAILO_HW_TEST=1` |
| `test_hailo_runtime_available_on_hardware` | same | `ai_hat_gated` | `BONBON_HAILO_HW_TEST=1` |
| `test_hailo_selected_on_hardware` | same | `ai_hat_gated` | `BONBON_HAILO_HW_TEST=1` + `BONBON_HAILO_HEF=<path>` |
| `test_real_estop_latency_under_full_ai_load` | `tests/production/test_safety_scenarios.py` | `pi_gated` | `BONBON_PI_HW_TEST=1` + `BONBON_ESTOP_LATENCY_LOG=<path>` |
| `test_real_sensor_unplug_triggers_degraded_mode` | `tests/production/test_sensor_failure_scenarios.py` | `pi_gated` | `BONBON_PI_HW_TEST=1` (manual action required) |
| `test_real_cpu_temperature_stability_under_load` | `tests/production/test_power_thermal_scenarios.py` | `pi_gated` | `BONBON_PI_HW_TEST=1` + `BONBON_THERMAL_LOG=<path>` |
| `test_real_hailo_runtime_selected_on_hardware` | `tests/production/test_pi_ai_hat_scenarios.py` | `ai_hat_gated` | `BONBON_HAILO_HW_TEST=1` |

The remaining 3 no-fake-PASS guards in `test_hardware_gated.py`
(`test_no_fake_hailo_pass_without_device`,
`test_benchmark_cli_marks_mock_fallback_nonzero`,
`test_explicit_mock_mode_is_zero_exit`) run **everywhere**, on or off
hardware — they assert the honesty property itself, not a hardware
result, so they are never gated.

## Environment-blocked (BLOCKED, not hardware-gated in the pytest-marker
sense, but still cannot run here)

`bonbon_vision`'s test suite requires a real `colcon build` to generate
`bonbon_msgs.msg.PerceptionBudget` — see
[KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md). Not a `pi_gated`/
`ai_hat_gated` marker because the blocker is the build toolchain, not the
robot itself; still correctly not counted as passing.

## Result in this environment (2026-07-01)

All 7 on-device tests **SKIP** with a stated BLOCKED reason. The 6
always-run no-fake-PASS guards (3 in `bonbon_ai_runtime`, plus the
equivalent honesty assertions inside each `pi_gated`/`ai_hat_gated`
production test file) all **PASS** — confirming the runtime/topology/
efficiency layers report their own unavailability honestly rather than
silently succeeding.

## Running on real hardware

```bash
bash scripts/pi_hardware_check.sh

BONBON_PI_HW_TEST=1 BONBON_HAILO_HW_TEST=1 \
BONBON_HAILO_HEF=/opt/bonbon/models/hailo/yolo_object_detection.hef \
BONBON_ESTOP_LATENCY_LOG=/tmp/estop_latencies.txt \
BONBON_THERMAL_LOG=/tmp/thermal_readings.txt \
  python -m pytest tests/production ros2_ws/src/bonbon_ai_runtime/tests -m hardware_gated -v
```
