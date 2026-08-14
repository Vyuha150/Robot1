# Hardware Telemetry Metrics Plan

`bonbon_hardware_telemetry` gives every physical hardware component a
real metrics/trigger story: base-mobility wheel motors, arm joints
(shoulder/elbow/wrist), head joints (pan/tilt), battery, and per-Pi
(ui_supervisor_pi / ai_interaction_pi / navigation_safety_pi) system
resources.

**Ground rule for this whole package**: every metric below comes from a
real, already-wired sensor or driver reading. Nothing here is inferred,
estimated, or fabricated from data that doesn't actually carry it. Where
the hardware genuinely cannot measure something, that field is listed
under Tier 2 and reported as `nan`/absent by the real driver already,
not by this package.

## Tier 1 -- shipped, from real sensors

### Base mobility (2x Cytron MDDS30 wheel motor channels)

Source: `bonbon_hal.nodes.motor_node.MotorNode`,
`/bonbon/motor/wheel_state` (`std_msgs/Float32MultiArray`:
`[left_mps, right_mps, left_distance_m, right_distance_m]`).

| Metric | Type | Notes |
|---|---|---|
| `left_mps` / `right_mps` | float | Commanded/estimated velocity -- open-loop, no encoder feedback exists on this hardware (`CytronMDDS30Driver.has_encoders == False`) |
| `left_distance_m` / `right_distance_m` | float | Open-loop distance estimate |
| topic staleness | trigger | `WHEEL_STATE_STALE` (WARN) if no update in `liveness.stale_after_sec` |

No stall/mismatch trigger is computed from velocity values -- there is
no feedback sensor to confirm one, and inferring a fault from an
open-loop estimate would fabricate a signal the hardware cannot back.

### Arm/head joints (2x NEMA17 closed-loop steppers, 3x PCA9685 PWM servos)

Source: `bonbon_hal.nodes.{stepper_node,servo_node}`,
`bonbon_msgs/ServoStateArray` on `/bonbon/stepper/state`,
`/bonbon/servo/neck/state`, `/bonbon/servo/arm/state`.

Steppers (`HEAD_PAN=id1`, `RIGHT_SHOULDER=id2`) are the only joints with
a real, ALM-pin-backed fault signal:

| Metric | Type | Notes |
|---|---|---|
| `position_rad` | float | Real closed-loop position |
| `error_code == 1` | trigger | `STEPPER_LOST_SYNC` (ERROR) -- confirmed stall/lost-sync, ALM GPIO pin |
| `torque_enabled` | metrics-only | Not auto-forwarded as a fault -- gesture/safety logic disables it deliberately elsewhere; treating every disable as a hardware fault would manufacture noise |
| topic staleness | trigger | `JOINT_STATE_STALE` (WARN) per topic |

PCA9685 servos (`HEAD_TILT=id1`, `RIGHT_ELBOW=id2`, `RIGHT_WRIST=id3`)
have **no feedback sensor at all** (`pca9685_servo_driver.py`'s own
docstring): `velocity_rads`/`load_percent`/`temperature_c`/`voltage_v`
are `nan`, `error_code` is hardwired to `0` and therefore never a fault
source for this family. Only `position_rad` (last commanded value) and
`torque_enabled` are real.

### Battery (INA226 power monitor, 3S LiPo pack)

Source: `bonbon_hal.nodes.battery_node.BatteryNode`,
`/bonbon/battery/state` (`sensor_msgs/BatteryState`).

Thresholds are derived directly from
`bonbon_hal.drivers.battery.battery_driver._VOLTAGE_TABLE` (11.1V
nominal, 12.6V=100%, 9.9V=0%) -- not independently chosen numbers.

| Metric | Type | Threshold (default) |
|---|---|---|
| `percent` | float | -- |
| `voltage_v` | float | -- |
| `current_a` | float | -- |
| `low_warn` | trigger | `BATTERY_LOW` (WARN) at `percent <= 20%` (10.8V row) |
| `low_error` | trigger | `BATTERY_CRITICALLY_LOW` (ERROR) at `percent <= 5%` (10.2V row) |
| `undervoltage` | trigger | `BATTERY_UNDERVOLTAGE` (ERROR) at `voltage_v <= 10.2V`, independent of percent |
| `overcurrent` | trigger | `BATTERY_OVERCURRENT` (WARN) at `abs(current_a) >= 18A` while discharging (headroom under `Ina226Driver`'s own `max_a=20.0` calibration ceiling) |
| topic staleness | trigger | `BATTERY_STATE_STALE` (WARN) |

### Per-Pi system resources (all 3 Pis)

Source: `bonbon_safety.core.resource_monitor.ResourceMonitor` (reused
unchanged), sampled locally on whichever Pi the node runs on.

| Metric | Type | Threshold (mirrors `ResourceSnapshot` exactly) |
|---|---|---|
| `cpu_percent` | float | `cpu_elevated` >=75%, `cpu_overloaded` >=90% |
| `memory_percent` | float | `memory_pressure` >=85% |
| `disk_free_percent` | float | `disk_low` <=10% |
| `available` | bool | `False` when `psutil` is missing -- readings are safe-degraded placeholders |

**CPU/memory/disk pressure is deliberately NOT forwarded as a
`bonbon_msgs/HalFault`.** That signal already has a dedicated,
already-acting-on-it pipeline: `bonbon_edge_ai_runtime.resource_guard`,
`bonbon_perception_efficiency.LoadSheddingController`/
`DegradedModeManager`, and `bonbon_llm.Pi2LLMGuard` all consume
`ResourceMonitor` snapshots on these exact thresholds and take real
load-shedding action. Duplicating the same reading into
`bonbon_fault_manager`'s HAL-device-fault taxonomy would give it two
independently-diverging meanings -- exactly the duplicate-pipeline
problem this workstream has repeatedly avoided elsewhere (see
`docs/DUPLICATE_PIPELINE_AUDIT.md`).

Two genuinely new triggers ARE forwarded, since nothing else already
reports them:

| Trigger | Severity | Meaning |
|---|---|---|
| `PI_RESOURCE_MONITOR_DEGRADED` | INFO | `psutil` unavailable -- every number in the snapshot is a placeholder, not a real reading |
| `PI_RESOURCE_SNAPSHOT_STALE` | WARN | No resource snapshot in `heartbeat_stale_after_sec` (mirrors `bonbon_distributed_safety.core.heartbeat_monitor`'s own 1.5s default) |

## Tier 2 -- needs new physical sensors, not implemented

These fields are not fabricated anywhere in this package. They require
hardware this robot's current BOM does not have:

- **Per-motor current draw** (wheel motors, servos) -- needs an
  in-line current sensor per channel; the shared INA226 only measures
  total pack current.
- **Motor/servo temperature** -- needs a thermistor per actuator;
  PCA9685 servos and Cytron wheel motors have no thermal sensor today.
- **Wheel encoders** -- needs quadrature encoders on the drive wheels;
  today's velocity/distance values are open-loop estimates.
- **Pi CPU temperature** -- `ResourceMonitor`/`psutil` does not expose
  a portable thermal reading across all 3 Pi roles today; this would
  need a `vcgencmd`/`/sys/class/thermal` reader per Pi.

## Architecture

- **New package**: `ros2_ws/src/bonbon_hardware_telemetry` (ament_python,
  matches `bonbon_edge_ai_runtime`'s skeleton exactly).
- **`core/*_metrics.py`**: pure Python, no rclpy -- `wheel_metrics.py`,
  `joint_metrics.py`, `battery_metrics.py`, `pi_metrics.py`. Each takes
  a real reading + `ThresholdConfig` and returns a metrics snapshot plus
  a list of `core.trigger.TelemetryTrigger`.
- **`core/threshold_config.py`** + `config/hardware_telemetry/thresholds.yaml`:
  every number traced to an existing authoritative source (voltage
  table, `ResourceSnapshot`, `HeartbeatConfig`) rather than invented.
- **`nodes/hardware_telemetry_node.py`**: the one ROS2 node. Subscribes
  to the real HAL state topics (`navigation_safety_pi` only -- the one
  Pi that actually runs `bonbon_hal`), samples per-Pi resources on every
  Pi role, publishes a JSON status snapshot on
  `/bonbon/hardware_telemetry/status` and real `bonbon_msgs/HalFault`
  events on the already-existing `/bonbon/hal/fault` ingestion topic
  (`bonbon_fault_manager` classifies/aggregates them -- no second
  alerting mechanism is built here).
- **Device names** on published `HalFault`s match
  `bonbon_hal.nodes.*.HalNodeBase.DEVICE_NAME` exactly (`"motor"`,
  `"stepper"`, `"servo"`, `"battery"`) so
  `bonbon_fault_manager.core.component_rules.DEVICE_INFO` classifies
  them correctly, not as unknown.
- **Launch**: wired into all three `launch/edge_ai/*_pi_edge.launch.py`
  files with the matching `pi_role` parameter.
- **Dashboard**: `GET /api/v1/hardware-telemetry/status` REST endpoint
  and the `hardware-telemetry` WebSocket channel, both relaying the real
  state `hardware_telemetry_node` published (cached by
  `ros2_bridge.py`) -- never a freshly-constructed, always-empty view.

## Tests

- `tests/hardware_telemetry/test_threshold_config.py` -- checked-in
  YAML matches dataclass defaults, and every threshold is verified
  against the real module it's required to mirror (`ResourceSnapshot`,
  `HeartbeatConfig`, the battery voltage table).
- `tests/hardware_telemetry/test_wheel_metrics.py`,
  `test_joint_metrics.py`, `test_battery_metrics.py`,
  `test_pi_metrics.py` -- pure logic, no rclpy needed.
- `tests/hardware_telemetry/test_dashboard_hardware_telemetry.py` --
  the dashboard relay function honestly reports unavailable with no
  bridge/message, and relays real state verbatim when present.
- `hardware_telemetry_node.py` itself is syntax-checked via
  `py_compile` only (needs a real ROS2 environment to run, matching
  every other rclpy node in this repo's established convention).
