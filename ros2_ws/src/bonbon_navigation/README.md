# bonbon_navigation

Autonomous navigation module for the **BonBon** service robot.  
Provides full Nav2 integration, RTAB-Map SLAM/localization, human-aware planning,
precision docking, stuck recovery, and battery-aware routing — all behind a
safety-gated velocity pipeline.

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                        NavigationNode                              │
│                      (ROS2 LifecycleNode)                          │
│                                                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │
│  │ GoalManager  │  │StuckDetector │  │   RecoveryExecutor       │ │
│  │ priority deq │  │rolling window│  │ wait→clear→backup→spin   │ │
│  │ preempt      │  │ zero-vel chk │  │ →replan→announce→escalate│ │
│  └──────┬───────┘  └──────┬───────┘  └────────────┬─────────────┘ │
│         │                 │                        │               │
│  ┌──────▼───────────────────────────────────────────────────────┐  │
│  │                   _nav_loop()  10 Hz                         │  │
│  │  expire persons → alerts → docking tick → recovery tick      │  │
│  │  → timeout check → stuck check → battery routing             │  │
│  │  → activate next goal → check Nav2 result                    │  │
│  └──────────────────────────────┬───────────────────────────────┘  │
│                                 │                                   │
│  ┌──────────────────┐  ┌────────▼──────────┐  ┌────────────────┐  │
│  │DockingController │  │  BatteryRouter    │  │LocalizationMon │  │
│  │APPROACH→ALIGN    │  │ OK/LOW/CRITICAL   │  │RTAB-Map+AMCL   │  │
│  │→FINAL→CONTACT    │  │ nearest charger   │  │cov trace track │  │
│  └──────────────────┘  └───────────────────┘  └────────────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │           HumanAwareCostmapLayer                             │  │
│  │  PersonObstacle → exponential inflation → OccupancyGrid      │  │
│  │  passing alerts → TTS "Excuse me, may I pass?"               │  │
│  └──────────────────────────────────────────────────────────────┘  │
└──────────────────────────────┬─────────────────────────────────────┘
                               │  /navigation/cmd_vel_request
                               ▼
                    ┌──────────────────────┐
                    │   SafetyStopBridge   │  ← /bonbon/safety/state
                    │  DANGER/FAULT → 0    │
                    │  CAUTION   → 0.30m/s │
                    │  DOCKING   → 0.15m/s │
                    │  NORMAL    → 0.80m/s │
                    └──────────┬───────────┘
                               │  /bonbon/safety_gate/cmd_vel
                               ▼
                    ┌──────────────────────┐
                    │    SafetyGateNode    │
                    └──────────┬───────────┘
                               │  /cmd_vel
                               ▼
                          Motor Controllers
```

> **Security constraint**: `NavigationNode` **never** publishes directly to `/cmd_vel`.
> Every velocity command passes through `SafetyStopBridge` first.

---

## Topics

### Subscribed

| Topic | Type | Description |
|---|---|---|
| `/perception/behavior` | `bonbon_msgs/BehaviorRecommendation` | LLM navigation requests |
| `/bonbon/safety/state` | `bonbon_msgs/SafetyState` | Live safety FSM state |
| `/perception/persons` | `bonbon_msgs/PersonStateArray` | Tracked persons for human-aware nav |
| `/odom` | `nav_msgs/Odometry` | Odometry for stuck detection |
| `/amcl_pose` | `geometry_msgs/PoseWithCovarianceStamped` | AMCL localization quality |
| `/rtabmap/localization_pose` | `geometry_msgs/PoseWithCovarianceStamped` | RTAB-Map localization quality |
| `/battery/state` | `sensor_msgs/BatteryState` | Battery level for routing |

### Published

| Topic | Type | Description |
|---|---|---|
| `/navigation/status` | `bonbon_msgs/NavigationStatus` | Goal state, progress, ETA (5 Hz) |
| `/navigation/goal` | `bonbon_msgs/NavigationGoal` | Active goal descriptor |
| `/navigation/docking_status` | `bonbon_msgs/DockingStatus` | Docking phase / sensor data |
| `/navigation/recovery_status` | `bonbon_msgs/RecoveryStatus` | Active recovery behavior |
| `/bonbon/safety_gate/cmd_vel` | `geometry_msgs/Twist` | Gated velocity → SafetyGateNode |
| `/bonbon/tts/request` | `bonbon_msgs/TTSRequest` | Text-to-speech announcements |
| `/health/navigation` | `diagnostic_msgs/DiagnosticStatus` | Health heartbeat (1 Hz) |

### Services

| Service | Type | Description |
|---|---|---|
| `/navigation/navigate_to` | `bonbon_srvs/NavigateTo` | Send a navigation goal |
| `/navigation/cancel` | `bonbon_srvs/CancelNavigation` | Cancel goal(s) by ID or all |
| `/navigation/get_nearest_charger` | `bonbon_srvs/GetNearestCharger` | Query nearest available charger |

---

## Parameters

### Robot

| Parameter | Default | Description |
|---|---|---|
| `robot_radius_m` | `0.35` | Robot footprint radius (m) |
| `robot_height_m` | `1.30` | Robot height (m) |
| `max_speed_mps` | `0.80` | Maximum linear speed in NORMAL state |
| `caution_speed_mps` | `0.30` | Speed cap in CAUTION / DEGRADED states |
| `dock_speed_mps` | `0.15` | Speed cap in DOCKING state |

### Nav2

| Parameter | Default | Description |
|---|---|---|
| `nav2_goal_tolerance_m` | `0.10` | XY arrival tolerance |
| `nav2_yaw_tolerance_rad` | `0.15` | Yaw arrival tolerance (~8.6°) |
| `global_planner` | `GridBased` | Nav2 global planner plugin |
| `local_controller` | `FollowPath` | Nav2 local controller plugin |

### RTAB-Map / Localization

| Parameter | Default | Description |
|---|---|---|
| `rtabmap_database_path` | `/var/lib/bonbon/rtabmap.db` | RTAB-Map database |
| `localization_mode` | `localization` | `"slam"` or `"localization"` |
| `localization_quality_threshold` | `2` | Max quality level to navigate (1=GOOD, 2=DEGRADED) |
| `localization_cov_warning` | `0.10` | Covariance trace warning threshold |

### Stuck Detection

| Parameter | Default | Description |
|---|---|---|
| `stuck_window_sec` | `5.0` | Rolling window for progress check |
| `stuck_min_progress_m` | `0.10` | Minimum movement to consider "not stuck" |
| `stuck_threshold_count` | `3` | Consecutive failures before declaring stuck |
| `stuck_zero_vel_window_sec` | `2.0` | Window for zero-velocity detection |

### Recovery

| Parameter | Default | Description |
|---|---|---|
| `recovery_enabled` | `true` | Enable recovery cascade |
| `recovery_max_retries` | `10` | Max total attempts across all behaviors |
| `recovery_behavior_sequence` | `[wait, clear_costmap, backup, spin, replan, announce, escalate]` | Ordered cascade |
| `recovery_wait_sec` | `3.0` | Pause duration in `wait` behavior |
| `recovery_backup_distance_m` | `0.30` | Backup distance |
| `recovery_backup_speed_mps` | `0.10` | Backup speed |
| `recovery_spin_speed_rps` | `0.50` | Spin angular speed (rad/s) |
| `recovery_spin_rotations` | `1` | Full rotations in spin behavior |
| `recovery_announce_repeat_sec` | `5.0` | TTS repeat interval in `announce` behavior |

### Docking

| Parameter | Default | Description |
|---|---|---|
| `docking_enabled` | `true` | Enable precision docking |
| `docking_pre_dock_distance_m` | `0.60` | Pre-dock waypoint offset from charger |
| `docking_final_approach_speed_mps` | `0.06` | Speed during final approach |
| `docking_max_alignment_error_m` | `0.05` | Max lateral error for alignment |
| `docking_max_heading_error_rad` | `0.10` | Max heading error for alignment |
| `docking_alignment_timeout_sec` | `30.0` | Alignment phase timeout |
| `docking_final_approach_timeout_sec` | `20.0` | Final approach timeout |
| `docking_max_attempts` | `3` | Max dock retries before FAILED |
| `docking_use_aruco_marker` | `true` | Use ArUco marker (ID 42) for alignment |
| `docking_use_ir_beacon` | `true` | Use IR beacon for distance/alignment |
| `docking_undock_reverse_distance_m` | `0.50` | Reverse distance for undocking |
| `docking_undock_speed_mps` | `0.10` | Undocking reverse speed |

### Battery Routing

| Parameter | Default | Description |
|---|---|---|
| `battery_low_threshold_pct` | `20.0` | Plan dock route when ≤ this value |
| `battery_critical_threshold_pct` | `10.0` | Abort current goal and dock immediately |
| `battery_resume_threshold_pct` | `80.0` | Resume normal navigation at this charge |
| `battery_routing_enabled` | `true` | Enable battery-aware routing |

### Human-Aware Navigation

| Parameter | Default | Description |
|---|---|---|
| `human_aware_enabled` | `true` | Enable human costmap layer |
| `person_inflation_radius_m` | `0.80` | Personal space radius (adults) |
| `vulnerable_inflation_radius_m` | `1.20` | Personal space radius (children/elderly) |
| `facing_multiplier` | `1.30` | Radius multiplier when person faces robot |
| `person_cost_scaling` | `2.0` | Exponential cost falloff factor |
| `announce_passing_intent` | `true` | Announce TTS when approaching persons |
| `announce_distance_m` | `2.0` | Distance threshold for passing announcement |
| `person_decay_sec` | `3.0` | Remove person after this many seconds without update |

### Safety

| Parameter | Default | Description |
|---|---|---|
| `safety_watchdog_timeout_sec` | `2.0` | Block motion if no SafetyState received for this long |

### Goal Queue

| Parameter | Default | Description |
|---|---|---|
| `max_queued_goals` | `10` | Maximum goals in queue (drops lowest priority when full) |
| `default_goal_timeout_sec` | `120.0` | Default goal timeout |
| `default_arrival_tolerance_m` | `0.15` | Default XY arrival tolerance |

---

## Safety Pipeline

All velocity commands pass through three enforced layers:

```
Layer 1 — SafetyStopBridge (this package)
  • DANGER / FAULT / SAFE_STOP  →  linear=0, angular=0 (immediate stop)
  • CAUTION / DEGRADED          →  linear capped at 0.30 m/s
  • DOCKING                     →  linear capped at 0.15 m/s
  • NORMAL                      →  linear capped at 0.80 m/s
  • Watchdog timeout (2 s)      →  linear=0, angular=0

Layer 2 — SafetyGateNode (bonbon_safety package)
  • Hardware e-stop integration
  • Publishes to /cmd_vel only when gate open

Layer 3 — Nav2 Collision Monitor
  • Real-time lidar footprint check
  • Slowdown and stop polygons
```

---

## Navigation Goal Priority

Goals are queued in a priority-sorted deque (max 10). Within the same priority, FIFO ordering applies.

| Priority | Value | Typical Source |
|---|---|---|
| EMERGENCY | 3 | Safety system, CRITICAL battery |
| HIGH | 2 | Staff override, explicit service request |
| NORMAL | 1 | LLM behavior recommendation |
| LOW | 0 | Scheduled maintenance routes |

A new goal with priority ≥ HIGH can preempt the currently-active goal when `enqueue(preempt=True)`.

---

## Recovery Cascade

When the robot becomes stuck or a plan fails, the recovery cascade runs:

```
1. wait          — pause 3 s for dynamic obstacle to clear
2. clear_costmap — clear local costmap, retry plan
3. backup        — reverse 0.30 m at 0.10 m/s
4. spin          — rotate 360° to re-perceive environment
5. replan        — request fresh global plan from Nav2
6. announce      — TTS: "Excuse me, could you please step aside?"
7. escalate      — publish staff alert + TTS: "I've alerted a staff member"
                   → goal permanently failed (RESULT_PLAN_FAILED)
```

Each behavior has a configurable attempt limit. After `recovery_max_retries` total attempts, the goal is declared permanently failed regardless of cascade position.

---

## Docking Phases

```
IDLE → APPROACHING → ALIGNING → FINAL_APPROACH → CONTACT
                        ↑               |
                        └─ retry ───────┘ (on timeout, up to max_dock_attempts)
                                        ↓ on failure
                                      FAILED

CONTACT → (charging confirmed) → UNDOCKING → IDLE
```

Sensor fusion priority: **ArUco marker > IR beacon**

---

## Human-Aware Costmap

Each tracked person generates an exponential cost inflation in the local costmap:

```
cost(d) = 100 × exp(-scaling × (1 - ratio)) × ratio
  where ratio = 1 - d/radius
        d     = distance to person centre
        radius = person_inflation_radius_m (adult)
               = vulnerable_inflation_radius_m (child/elderly)
               × facing_multiplier (if person faces robot)
```

When the robot approaches within `announce_distance_m` (2.0 m), a TTS announcement is triggered once per person encounter.

---

## Launch

### Full navigation stack (localization mode)
```bash
ros2 launch bonbon_navigation navigation.launch.py \
    map:=$(ros2 pkg prefix bonbon_navigation)/share/bonbon_navigation/maps/cafe_map.yaml \
    rtabmap_db:=/var/lib/bonbon/rtabmap.db \
    use_sim_time:=false
```

### SLAM mode (build map while driving)
```bash
ros2 launch bonbon_navigation slam.launch.py \
    rtabmap_db:=/var/lib/bonbon/rtabmap.db \
    visualize:=true
```

### Localization only (verify before starting nav)
```bash
ros2 launch bonbon_navigation localization.launch.py \
    map:=/path/to/cafe_map.yaml \
    rtabmap_db:=/var/lib/bonbon/rtabmap.db \
    use_amcl:=true
```

### Simulation (café world)
```bash
ros2 launch bonbon_navigation navigation.launch.py \
    use_sim_time:=true \
    map:=$(ros2 pkg prefix bonbon_navigation)/share/bonbon_navigation/maps/cafe_map.yaml
```

---

## Lifecycle Management

`NavigationNode` is a ROS2 `LifecycleNode`. State transitions:

| Transition | Action |
|---|---|
| `configure` | Create subsystems, subscribers, publishers, services; load map |
| `activate` | Start nav_timer (10 Hz), status_timer (5 Hz), health_timer (1 Hz) |
| `deactivate` | Cancel active goals, cancel Nav2, stop timers |
| `cleanup` | Destroy all handles; reset subsystems |
| `shutdown` | Emergency stop (publish zero velocity) |

```bash
# Lifecycle management via CLI
ros2 lifecycle set /bonbon_navigation_node configure
ros2 lifecycle set /bonbon_navigation_node activate
ros2 lifecycle set /bonbon_navigation_node deactivate
```

---

## Sending Navigation Goals

### Via service
```bash
ros2 service call /navigation/navigate_to bonbon_srvs/srv/NavigateTo \
  '{goal_id: "delivery_1", named_location: "table_5", timeout_sec: 60.0, enqueue: false}'
```

### Via topic (from LLM / BehaviorRecommendation)
The `NavigationNode` subscribes to `/perception/behavior` and automatically converts `navigate_to_goal` / `serve_item` behavior classes into navigation goals. See `bonbon_llm/tools` for tool schemas.

---

## Simulation Worlds

| World | File | Scenario |
|---|---|---|
| Standard café | `worlds/cafe.world` | 14 m × 12 m café with 10 tables, 2 chargers |
| Hospital corridor | `worlds/hospital_corridor.world` | 3 m × 30 m corridor, medical carts, narrow passages |
| Crowded café | `worlds/crowded_cafe.world` | Standard café + 3+ pedestrian models for human-awareness tests |

---

## Tests

```bash
# Unit tests (no ROS2 required)
cd ros2_ws/src/bonbon_navigation
python -m pytest tests/ -v

# Integration tests only
python -m pytest tests/integration/ -v

# Simulation-level tests
python -m pytest tests/simulation/ -v

# All tests with coverage
python -m pytest tests/ --cov=bonbon_navigation --cov-report=term-missing
```

### Test coverage

| Module | Tests | Coverage focus |
|---|---|---|
| `core/goal_manager` | `test_goal_manager.py` | Priority ordering, preemption, timeout, cancellation |
| `core/stuck_detector` | `test_stuck_detector.py` | Rolling window, zero-velocity, threshold counting |
| `core/recovery_executor` | `test_recovery_behaviors.py` | All 7 behaviors, cascade order, exhaustion |
| `core/battery_router` | `test_battery_router.py` | Classification thresholds, charger selection |
| `safety/safety_stop_bridge` | `test_safety_stop_bridge.py` | All 8 states, watchdog, angular scaling |
| `core/localization_monitor` | `test_localization_monitor.py` | Quality thresholds, consecutive lost, report fields |
| `core/map_manager` | `test_map_manager.py` | PGM/YAML load, coordinate transforms, named locations |
| Integration: timeout | `integration/test_navigation_timeout.py` | Goal→timeout→recovery→requeue pipeline |
| Integration: obstacle | `integration/test_obstacle_blocking.py` | Stuck→cascade→escalate, safety bridge during recovery |
| Integration: corridor | `integration/test_hospital_corridor.py` | Narrow corridor, docking, human awareness |
| Simulation: crowded | `simulation/test_crowded_environment.py` | 6+ persons, expiry, thread safety, battery routing |

---

## Package Layout

```
bonbon_navigation/
├── bonbon_navigation/
│   ├── __init__.py
│   ├── config/
│   │   ├── __init__.py
│   │   └── nav_config.py          # All configuration dataclasses
│   ├── core/
│   │   ├── __init__.py
│   │   ├── map_manager.py         # PGM/YAML loader, named-location registry
│   │   ├── localization_monitor.py# RTAB-Map + AMCL quality tracking
│   │   ├── stuck_detector.py      # Rolling window progress + zero-vel check
│   │   ├── goal_manager.py        # Priority queue, timeout, history
│   │   ├── battery_router.py      # Battery level classification + routing
│   │   └── recovery_executor.py   # 7-step recovery cascade
│   ├── planners/
│   │   ├── __init__.py
│   │   └── human_aware_costmap.py # Exponential person-cost inflation
│   ├── behaviors/
│   │   ├── __init__.py
│   │   └── docking_controller.py  # Precision docking state machine
│   ├── safety/
│   │   ├── __init__.py
│   │   └── safety_stop_bridge.py  # Velocity safety gating (all states)
│   └── nodes/
│       ├── __init__.py
│       └── navigation_node.py     # Main ROS2 LifecycleNode
├── config/
│   ├── nav_params.yaml            # NavigationNode parameters
│   ├── nav2_params.yaml           # Full Nav2 stack parameters
│   └── rtabmap_params.yaml        # RTAB-Map SLAM / localization parameters
├── launch/
│   ├── navigation.launch.py       # Full stack: Nav2 + RTAB-Map + NavigationNode
│   ├── slam.launch.py             # SLAM mode (map building)
│   └── localization.launch.py     # Localization-only mode
├── maps/
│   └── cafe_map.yaml              # Map descriptor (references cafe_map.pgm)
├── worlds/
│   ├── cafe.world                 # Standard café (Gazebo SDF)
│   ├── hospital_corridor.world    # Narrow corridor scenario
│   └── crowded_cafe.world         # Crowded café with pedestrians
└── tests/
    ├── test_goal_manager.py
    ├── test_stuck_detector.py
    ├── test_recovery_behaviors.py
    ├── test_battery_router.py
    ├── test_safety_stop_bridge.py
    ├── test_localization_monitor.py
    ├── test_map_manager.py
    ├── integration/
    │   ├── test_navigation_timeout.py
    │   ├── test_obstacle_blocking.py
    │   └── test_hospital_corridor.py
    └── simulation/
        └── test_crowded_environment.py
```

---

## Dependencies

| Package | Required | Fallback |
|---|---|---|
| `rclpy` | Yes | — |
| `nav2_simple_commander` | Yes | Logged warning; Nav2 goals disabled |
| `rtabmap_slam` | Yes | AMCL localization used instead |
| `nav2_*` | Yes | Navigation disabled |
| `bonbon_msgs` | Yes | Node fails to start |
| `bonbon_srvs` | Yes | Services not registered |
| `numpy` | Yes | HumanAwareCostmapLayer disabled |
| `tf2_ros` / `tf2_geometry_msgs` | Yes | — |

---

## Extension Guide

### Add a named location
```python
# In nav_params.yaml:
named_locations:
  - "my_new_location:x_val,y_val,yaw_val"

# Or at runtime:
map_manager.add_location("breakroom", x=12.0, y=3.0, yaw=0.0)
```

### Add a recovery behavior
1. Add behavior name to `recovery_behavior_sequence` in `nav_params.yaml`
2. Add handler branch in `RecoveryExecutor._execute_behavior()`
3. Wire callback via `set_*_fn()` in `NavigationNode.on_configure()`

### Replace the local controller
Update `config/nav2_params.yaml → controller_server → controller_plugins` and add the new plugin's parameter block.

### Add a simulation world
1. Create `worlds/myworld.world` (SDF format)
2. Register in `setup.py` under `data_files`
3. Pass `world:=myworld.world` to the navigation launch file

---

## Security Notes

- `NavigationNode` **never** publishes to `/cmd_vel` directly. Attempting to route around `SafetyStopBridge` will result in zero-velocity output or a watchdog block.
- All navigation goals are validated against the safety state before execution. Goals received in `DANGER`, `FAULT`, or `SAFE_STOP` states are immediately rejected.
- The LLM (`bonbon_llm`) issues navigation commands only through `BehaviorRecommendation` messages — never via direct actuator control.
- Battery `CRITICAL` (≤10%) triggers immediate goal abort and emergency docking regardless of current task priority.
