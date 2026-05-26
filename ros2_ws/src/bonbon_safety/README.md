# bonbon_safety — Safety Supervisor Package

Production-grade safety subsystem for the BonBon service robot.  
Implements an 8-state deterministic FSM, hardware e-stop integration,  
node watchdog, and declarative YAML safety policy.

---

## Package Contents

```
bonbon_safety/
├── bonbon_safety/
│   ├── core/
│   │   ├── safety_state_machine.py   # Pure-Python 8-state FSM
│   │   ├── safety_policy.py          # PolicyAction enum + SafetyPolicy loader
│   │   ├── default_policy.py         # Built-in conservative policy rules
│   │   ├── threat_assessor.py        # Aggregates sensor callbacks → SensorSnapshot
│   │   └── incident_logger.py        # Append-only SQLite audit log
│   ├── nodes/
│   │   ├── safety_supervisor_node.py # ROS2 lifecycle node — orchestrates FSM
│   │   ├── watchdog_node.py          # 2 Hz heartbeat monitor
│   │   └── estop_node.py             # 50 Hz GPIO e-stop poller
│   └── config/
│       ├── safety_params.yaml        # ROS2 parameter values for all 3 nodes
│       └── safety_policy.yaml        # Declarative per-state action rules
├── launch/
│   └── safety.launch.py              # Launch file for all 3 nodes
├── tests/
│   ├── test_safety_state_machine.py  # FSM unit tests (no ROS2)
│   ├── test_safety_policy.py         # Policy loading tests
│   ├── test_threat_assessor.py       # Sensor aggregation tests
│   ├── test_watchdog.py              # Watchdog logic tests
│   ├── integration/
│   │   └── test_safety_integration.py   # launch_testing ROS2 integration
│   └── simulation/
│       └── test_failure_scenarios.py    # Chaos / failure scenario tests
├── package.xml
├── setup.py
└── setup.cfg
```

---

## Nodes

### `safety_supervisor_node`

| Property | Value |
|----------|-------|
| Type | LifecycleNode |
| Rate | 10 Hz FSM evaluation |
| Namespace | `/bonbon` |
| Publishes | `/bonbon/safety/state` (SafetyState, RELIABLE/TRANSIENT_LOCAL) |
| Publishes | `/bonbon/safety/event` (SafetyEvent, RELIABLE/depth-50) |
| Publishes | `/bonbon/cmd_vel/safe` (Twist) |
| Subscribes | `/bonbon/lidar/scan`, `/bonbon/imu/data_raw`, `/bonbon/bumper/state` |
| Subscribes | `/bonbon/battery/state`, `/bonbon/temperature/readings` |
| Subscribes | `/bonbon/servo/neck/state`, `/bonbon/servo/arm/state` |
| Subscribes | `/bonbon/perception/persons`, `/bonbon/estop/state` |
| Subscribes | All 14 `ModuleHealth` topics (watchdog integration) |
| Service | `/bonbon/safety/reset` (SafetyReset.srv) |

### `watchdog_node`

| Property | Value |
|----------|-------|
| Type | LifecycleNode |
| Rate | 2 Hz check cycle |
| Monitors | 14 managed nodes across 4 crash classes |
| Publishes | `/bonbon/safety/critical_node_crashed` (Bool) |
| Publishes | `/bonbon/safety/important_node_crashed` (Bool) |
| Publishes | `/bonbon/safety/watchdog_node/health` (ModuleHealth) |

### `estop_node`

| Property | Value |
|----------|-------|
| Type | LifecycleNode |
| Rate | 50 Hz GPIO poll (20 ms max latency) |
| GPIO in | BCM pin 17 — e-stop button (active LOW) |
| GPIO out | BCM pin 18 — motor power relay (active HIGH) |
| Publishes | `/bonbon/estop/state` (Bool, RELIABLE/TRANSIENT_LOCAL) |
| Subscribes | `/bonbon/safety/state` — asserts relay on SAFE_STOP |

---

## Safety States

See [SAFETY_STATE_MACHINE.md](SAFETY_STATE_MACHINE.md) for the full state diagram.

| State | Actuation | Navigation | Max Vel | Manual Reset |
|-------|-----------|------------|---------|--------------|
| INITIALIZING | ✗ | ✗ | 0.0 m/s | No |
| NORMAL | ✓ | ✓ | 0.8 m/s | No |
| CAUTION | ✓ | ✓ | 0.3 m/s | No |
| DANGER | ✗ | ✗ | 0.0 m/s | No |
| DOCKING | ✓ | ✓ | 0.2 m/s | No |
| DEGRADED | ✓ | ✓ | 0.3 m/s | No |
| FAULT | ✗ | ✗ | 0.0 m/s | **Yes** |
| SAFE_STOP | ✗ | ✗ | 0.0 m/s | **Yes** |

---

## Build & Install

```bash
# From workspace root
cd ~/ros2_ws
colcon build --packages-select bonbon_safety --symlink-install
source install/setup.bash
```

---

## Launch

```bash
# Standard launch (hardware)
ros2 launch bonbon_safety safety.launch.py

# Simulation mode (no GPIO access)
ros2 launch bonbon_safety safety.launch.py simulation:=true

# Custom robot ID
ros2 launch bonbon_safety safety.launch.py robot_id:=bonbon-02

# Custom safety policy
ros2 launch bonbon_safety safety.launch.py \
    policy_file:=/etc/bonbon/hospital_policy.yaml

# Site-specific parameter overrides
ros2 launch bonbon_safety safety.launch.py \
    override_params_file:=/etc/bonbon/site_params.yaml
```

---

## Run Tests

```bash
# Fast unit tests (no ROS2 needed)
cd ros2_ws/src/bonbon_safety
pytest tests/ -v --ignore=tests/integration -k "not integration"

# Integration tests (ROS2 required)
colcon test --packages-select bonbon_safety
colcon test-result --verbose

# Specific test file
pytest tests/test_safety_state_machine.py -v

# Failure scenario chaos tests
pytest tests/simulation/test_failure_scenarios.py -v
```

---

## Configuration

### Key safety thresholds (`safety_params.yaml`)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `human_caution_m` | 2.0 m | Distance triggering CAUTION |
| `human_danger_m` | 0.5 m | Distance triggering DANGER (full stop) |
| `battery_caution_pct` | 20 % | Battery level entering CAUTION |
| `battery_dock_pct` | 10 % | Battery level forcing DOCKING |
| `cpu_temp_caution_c` | 75 °C | CPU temp throttling AI |
| `cpu_temp_fault_c` | 90 °C | CPU temp triggering FAULT |
| `lidar_stale_danger` | true | LIDAR loss → DANGER (vs CAUTION) |
| `hysteresis_cycles_caution` | 3 | Clear cycles before CAUTION→NORMAL |
| `hysteresis_cycles_danger` | 5 | Clear cycles before DANGER→CAUTION |
| `supervisor_rate_hz` | 10.0 | FSM evaluation frequency |
| `startup_timeout_sec` | 15.0 | Max time in INITIALIZING before FAULT |

### Policy customization

The safety policy is fully declarative. To change robot behaviour per deployment  
**without touching Python code**, edit `config/safety_policy.yaml` or provide a  
custom policy via the `policy_file` launch argument.

```yaml
# Example: change CAUTION to not announce audio in quiet areas
rules:
  CAUTION:
    on_enter:
      - cap_velocity
      - update_led_eyes
      - update_display
      - notify_operator
      - log_incident
    # (removed announce_audio)
    led_state: "alert"
    display_text: "⚠ Slowing down"
```

---

## Operator Reset

When the robot enters FAULT or SAFE_STOP, a manual reset is required:

```bash
# Via ROS2 service CLI
ros2 service call /bonbon/safety/reset bonbon_srvs/srv/SafetyReset \
    "{operator_id: 'ops_id_123', reason: 'Cleared obstacle and inspected robot'}"

# Expected response
# success: True
# message: "Reset accepted. Transitioning to INITIALIZING."
```

The robot will then re-run the startup sequence before returning to NORMAL.

---

## Incident Log

All state transitions and safety events are logged to SQLite:

```bash
# Default path
/var/lib/bonbon/safety_incidents.db

# Query recent incidents
sqlite3 /var/lib/bonbon/safety_incidents.db \
    "SELECT timestamp, robot_id, from_state, to_state, reason FROM incidents ORDER BY id DESC LIMIT 20;"
```

---

## Monitoring

```bash
# Watch safety state in real-time
ros2 topic echo /bonbon/safety/state

# Watch safety events
ros2 topic echo /bonbon/safety/event

# Check e-stop status
ros2 topic echo /bonbon/estop/state

# Check watchdog health
ros2 topic echo /bonbon/safety/watchdog_node/health

# Check all safety-related topics
ros2 topic list | grep bonbon/safety
```

---

## Hardware Notes

- **E-stop wiring**: Button is wired to BCM GPIO 17 (active LOW with pull-up).  
  Relay coil is on BCM GPIO 18 (active HIGH cuts 24V motor power).  
  The hardware path cuts power independently of software — e-stop is fail-safe.

- **LIDAR**: RPLIDAR S2 at 10 Hz. Staleness threshold = 0.5 s.  
  Loss of LIDAR with `lidar_stale_danger=true` triggers immediate DANGER.

- **IMU**: MPU-6050 at 100 Hz. Staleness threshold = 0.1 s.

- **Person detection**: Orbbec Astra Mini at 30 FPS. Person tracks coast 1.0 s.

---

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common issues and solutions.
