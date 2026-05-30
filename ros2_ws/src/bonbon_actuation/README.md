# bonbon_actuation

High-level **expressive motion control** for the BonBon service robot. Turns
named, semantic gesture requests (`wave`, `nod_yes`, `point_left`, `greeting_pose`,
…) into validated, safety-gated servo commands for the head and arms.

This package never touches hardware directly — it publishes validated
`ServoStateArray` commands to the HAL servo bus (`bonbon_hal`). It also never
makes autonomous decisions: it only **executes** gestures requested by
`bonbon_behavior_engine` (or an operator service call), after applying its own
independent safety layer.

---

## Responsibilities

| Capability | Module |
|---|---|
| Pre-defined expressive gesture library (head/arm keyframes) | `core/gesture_library.py` |
| Keyframe → time-stepped motion profile, speed-scalable | `core/motion_profile.py` |
| Servo position/velocity clamping to mechanical limits | `core/servo_validator.py` |
| Safety-level gating (priority vs. SafetyState) | `core/actuation_safety_gate.py` |
| Priority motion queue with preemption | `core/motion_queue.py` |
| Human-proximity & mode-based speed derating | `core/proximity_governor.py` |
| ROS2 LifecycleNode orchestration | `nodes/actuation_node.py` |

---

## Architecture

```
/bonbon/behavior/actuation (ActuationGesture)
        │
        ▼
┌──────────────────────────── ActuationNode ────────────────────────────┐
│ 1. E-stop gate         ← /bonbon/estop/state (Bool)                    │
│ 2. ActuationSafetyGate ← /bonbon/safety/state (SafetyState)            │
│ 3. ProximityGovernor   ← /bonbon/spatial/hints, /bonbon/spatial/entities│
│ 4. GestureLibrary      (resolve name → keyframes)                      │
│ 5. MotionQueue         (serialise / preempt)                           │
│ 6. MotionProfileGen    (keyframes → timed steps, speed-scaled)         │
│ 7. ServoValidator      (clamp to SERVO_LIMITS)                         │
└────────────────────────────────────────────────────────────────────────┘
        │                                   │
        ▼                                   ▼
/bonbon/hal/servo_commands           /bonbon/actuation/status
   (ServoStateArray)                    (ActuationStatus)
```

### Safety layering (defence in depth)

1. **Hardware e-stop** (`/bonbon/estop/state` = True) cancels the running
   gesture, clears the queue, and rejects everything except the
   `safe_folded_pose` recovery.
2. **Safety Supervisor** state ≥ DANGER cancels non-emergency gestures and
   clears the queue. `actuation_enabled=False` blocks all motion.
3. **Proximity governor** suppresses arm-sweeping gestures (`requires_clear_space`)
   when a person is inside the stop band, and derates speed in the slow/caution
   bands, in child-safe / elderly modes, and on `slow_down` / `stop` spatial hints.
4. **Servo validator** clamps every commanded position and velocity to the
   mechanical limits in `SERVO_LIMITS` — nothing reaches the HAL unclamped.

---

## Topics & Services

### Subscribed
| Topic | Type | Purpose |
|---|---|---|
| `/bonbon/behavior/actuation` | `bonbon_msgs/ActuationGesture` | gesture requests |
| `/bonbon/safety/state` | `bonbon_msgs/SafetyState` | safety gating |
| `/bonbon/estop/state` | `std_msgs/Bool` | hardware e-stop override |
| `/bonbon/spatial/hints` | `bonbon_msgs/SocialNavigationHint` | social slowdown/stop |
| `/bonbon/spatial/entities` | `bonbon_msgs/SpatialEntity` | person proximity |

### Published
| Topic | Type | Purpose |
|---|---|---|
| `/bonbon/hal/servo_commands` | `bonbon_msgs/ServoStateArray` | validated servo targets |
| `/bonbon/actuation/status` | `bonbon_msgs/ActuationStatus` | execution status / progress |

### Services
| Service | Type | Purpose |
|---|---|---|
| `~/perform_gesture` | `bonbon_srvs/PerformGesture` | request a gesture synchronously |
| `~/set_mode` | `bonbon_srvs/SetMode` | switch operating mode (child_safe …) |
| `~/health_check` | `bonbon_srvs/HealthCheck` | health + telemetry snapshot |

---

## Gesture priorities

| Priority | Meaning | Behaviour |
|---|---|---|
| 0 | low (idle scan) | runs only when nothing else pending |
| 5 | normal (wave, nod) | standard expressive gestures |
| 10 | high | preempts normal gestures |
| 20 | emergency | always preempts; bypasses proximity derate |

---

## Operating modes (`~/set_mode`)

| Mode | Speed cap | Notes |
|---|---|---|
| `normal` | 1.00× | default |
| `elderly` | 0.70× | gentler, slower motion |
| `child_safe` | 0.55× | slowest; larger proximity stop band for children |
| `degraded` | 0.50× | reduced-capability fallback |
| `demo` | 1.00× | showcase |
| `emergency` | 1.00× | emergency gestures stay crisp |

---

## Running

```bash
# Build
cd ros2_ws && colcon build --packages-select bonbon_actuation

# Launch (auto-configures + activates the lifecycle node)
ros2 launch bonbon_actuation actuation.launch.py

# Request a gesture from the CLI
ros2 service call /actuation_node/perform_gesture bonbon_srvs/srv/PerformGesture \
  "{gesture: {gesture_name: 'wave', priority: 5, speed_scale: 1.0}}"

# Switch to child-safe mode
ros2 service call /actuation_node/set_mode bonbon_srvs/srv/SetMode \
  "{mode: 'child_safe', operator_id: 'op1'}"
```

The node runs fully in **mock/simulation mode** with no hardware: if no servo
node subscribes to `/bonbon/hal/servo_commands`, gestures still validate, queue,
derate, and report status — they simply have no physical effect.

---

## Testing

```bash
cd ros2_ws/src/bonbon_actuation
python -m pytest tests/ -q          # unit + integration (98 tests)
```

- `tests/test_gesture_library.py` — gesture registry & in-limit keyframes
- `tests/test_servo_validator.py` — position/velocity clamping
- `tests/test_motion_profile.py` — keyframe → timed steps, speed scaling
- `tests/test_actuation_safety_gate.py` — priority gating per safety level
- `tests/test_motion_queue.py` — priority ordering, eviction, preemption
- `tests/test_proximity_governor.py` — proximity bands, modes, vulnerable categories
- `tests/integration/test_actuation_integration.py` — full pipeline end-to-end

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Gesture rejected: "e-stop engaged" | `/bonbon/estop/state` is `True` | Release the hardware e-stop; verify `bonbon_hal` estop node is publishing `False`. |
| Gesture rejected: "proximity: person … ≤ stop band" | A person (or child) is too close for an arm sweep | Expected safety behaviour. Move back, or request a head-only gesture (`nod_yes`, `listening_pose`). |
| All gestures rejected with priority message | Safety level too high (CAUTION/DANGER) for the gesture's priority | Check `/bonbon/safety/state`; only emergency-priority gestures run in DANGER. |
| Gestures run but robot doesn't move | No servo node subscribed to `/bonbon/hal/servo_commands` | Start `bonbon_hal` servo node, or accept mock behaviour in simulation. |
| Motion is unexpectedly slow | Operating mode is `child_safe`/`elderly`, or a person is nearby | Check `~/health_check` → `mode` and `derates`; call `~/set_mode normal` if appropriate. |
| Queue depth keeps growing | Gestures arriving faster than they execute | Expected backpressure; low-priority entries are evicted when `motion_queue_depth` is exceeded. |
| `Unknown gesture` errors | Requested name not in `GestureLibrary` | Use `GestureLibrary.list_names()`; see `core/gesture_library.py` for the catalogue. |

### Diagnostics

`~/health_check` returns a status string with live telemetry:
`gesture`, `mode`, `queue` depth, `safety` level, and counters
(`run`, `rejected`, `derates`). Warnings flag an engaged e-stop or a person
within 1 m.
