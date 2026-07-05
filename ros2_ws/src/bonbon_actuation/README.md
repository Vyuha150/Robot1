# bonbon_actuation

High-level **expressive motion control** for the BonBon service robot. Turns
named, semantic gesture requests (`wave`, `nod_yes`, `point_left`, `greeting_pose`,
…) into validated, safety-gated servo/stepper commands for the real BOM
topology: a single right arm (shoulder/elbow/wrist) + a 2-DOF head
(pan/tilt) — **not** a symmetric two-arm robot, which this package
incorrectly assumed until the 2026-07-06 BOM-accuracy pass corrected it
(see `core/gesture_library.py`'s `JOINT_ACTUATOR_TYPE`/`JOINT_LOCAL_ID`
global joint-ID map). HEAD pan and the RIGHT ARM shoulder are NEMA17
closed-loop steppers; HEAD tilt, RIGHT ARM elbow, and RIGHT ARM wrist are
PCA9685-driven PWM servos.

This package never touches hardware directly — it publishes validated
commands to `bonbon_safety`'s gated raw topics (never directly to
`bonbon_hal`). It also never makes autonomous decisions: it only
**executes** gestures requested by `bonbon_behavior_engine` (or an operator
service call), after applying its own independent safety layer.

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
│ 7. ServoValidator      (clamp to JOINT_LIMITS)                         │
│ 8. Route per-joint by JOINT_ACTUATOR_TYPE/JOINT_LOCAL_ID               │
└────────────────────────────────────────────────────────────────────────┘
        │                    │                    │            │
        ▼                    ▼                    ▼            ▼
/bonbon/stepper/     /bonbon/servo/neck/  /bonbon/servo/arm/  /bonbon/actuation/status
  command_raw            command_raw          command_raw        (ActuationStatus)
        │                    │                    │
        ▼                    ▼                    ▼
   bonbon_safety/safety_gate_node (CLASS-A, sole gated-actuation path)
        │                    │                    │
        ▼                    ▼                    ▼
/bonbon/stepper/     /bonbon/servo/neck/  /bonbon/servo/arm/
   command               command              command
        │                    │                    │
        ▼                    ▼                    ▼
              bonbon_hal (stepper_node / servo_node)
```

This node has **no direct path to `bonbon_hal`** — every command is
published to a `*_raw` topic and only reaches hardware after
`bonbon_safety/safety_gate_node` (CLASS-A) re-publishes it, exactly the
same gate every other actuation source (LLM, dashboard, behavior engine)
goes through. This replaces a 2026-07-06 bug fix: this node previously
published a single `ServoStateArray` to `/bonbon/hal/servo_commands`, a
topic nothing subscribed to — gestures never reached hardware at all,
with no error raised (ROS2 message publishers don't fail when nobody is
subscribed).

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
   mechanical limits in `JOINT_LIMITS` (alias `SERVO_LIMITS` kept for
   caller compatibility) — nothing reaches the HAL unclamped.
5. **`bonbon_safety/safety_gate_node`** (outside this package, but the
   final and authoritative gate) re-checks `_can_actuate()` on every raw
   command before it ever reaches `bonbon_hal` — including for steppers,
   which had zero safety gating at all before 2026-07-06.

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
| `/bonbon/stepper/command_raw` | `bonbon_msgs/ServoStateArray` | HEAD pan / RIGHT ARM shoulder targets (gated by `safety_gate_node`) |
| `/bonbon/servo/neck/command_raw` | `bonbon_msgs/ServoState` | HEAD tilt target (gated by `safety_gate_node`) |
| `/bonbon/servo/arm/command_raw` | `bonbon_msgs/ServoStateArray` | RIGHT ARM elbow/wrist targets (gated by `safety_gate_node`) |
| `/bonbon/actuation/status` | `bonbon_msgs/ActuationStatus` | execution status / progress (`progress_pct` 0-100, `head_pan_rad`/`head_tilt_rad`, `safety_blocked`) |

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

The node runs fully in **mock/simulation mode** with no hardware: if
`bonbon_safety`/`bonbon_hal` aren't running, gestures still validate,
queue, derate, and report status — they simply have no physical effect.

---

## Testing

```bash
cd ros2_ws/src/bonbon_actuation
python -m pytest tests/ -q          # unit + integration (92 tests)
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
| Gestures run but robot doesn't move | `bonbon_safety`/`bonbon_hal` not running, or safety state doesn't permit actuation | Start `bonbon_safety` + `bonbon_hal`; check `/bonbon/safety/state`'s `actuation_permitted` field. |
| Motion is unexpectedly slow | Operating mode is `child_safe`/`elderly`, or a person is nearby | Check `~/health_check` → `mode` and `derates`; call `~/set_mode normal` if appropriate. |
| Queue depth keeps growing | Gestures arriving faster than they execute | Expected backpressure; low-priority entries are evicted when `motion_queue_depth` is exceeded. |
| `Unknown gesture` errors | Requested name not in `GestureLibrary` | Use `GestureLibrary.list_names()`; see `core/gesture_library.py` for the catalogue. |

### Diagnostics

`~/health_check` returns a status string with live telemetry:
`gesture`, `mode`, `queue` depth, `safety` level, and counters
(`run`, `rejected`, `derates`). Warnings flag an engaged e-stop or a person
within 1 m.
