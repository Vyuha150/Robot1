# BonBon Safety State Machine

Version 1.0 — matches `bonbon_safety.core.safety_state_machine`

---

## Overview

The safety FSM is the single source of truth for what the robot is allowed to do.  
Every 100 ms (10 Hz) the supervisor node feeds a `SensorSnapshot` into `SafetyStateMachine.update()`.  
The machine returns the new state and, if a transition occurred, a `StateTransition` record.

**Design principles:**

1. **Single point of authority** — no node bypasses the FSM to enable motion.
2. **Conservative default** — unknown sensor data is treated as a hazard.
3. **Deterministic** — given identical input sequences, output is identical.
4. **No I/O** — the FSM has no ROS2 dependency; external effects are dispatched by the supervisor after reading the transition.
5. **Audit trail** — every transition is recorded with timestamp, reason, and full sensor snapshot.

---

## State Diagram

```
                          ┌─────────────────── e-stop (any state) ────────────────────────────────────┐
                          │                                                                             ▼
  ┌──────────────┐        │   ┌──────────────┐                                                  ┌───────────┐
  │ INITIALIZING │ ───────┼──►│    NORMAL    │◄─────── hysteresis clear ────────────────────────│ SAFE_STOP │
  └──────┬───────┘    startup │              │                                                  └───────────┘
         │            complete└──┬───────┬───┘
         │                       │       │
         │   cpu_temp > 90°C     │       │ human < 2m
         │   critical crash      │       │ battery 10-20%
         │   servo/odrive fault  │       │ cpu_temp > 75°C
         ▼                       │       │ sensor WARN
     ┌───────┐                   ▼       ▼
     │ FAULT │◄──────────── ┌─────────────┐
     └───┬───┘  (also from  │   CAUTION   │◄───── cleared + hysteresis ──── DANGER
         │      CAUTION,    └─────┬───────┘
         │      DANGER,           │
         │      DEGRADED)         │ human < 0.5m
         │                        │ bumper hit
  reset()│                        │ cliff detected
  + mark │                        │ lidar stale (danger mode)
  startup│                        │ imu stale
  complete                        ▼
         │                  ┌─────────────┐
         └──────────────────│   DANGER    │──────── e-stop ──────► SAFE_STOP
                            └──────┬──────┘
                         hysteresis│cleared
                           (5 cyc.)│
                                   ▼
                             CAUTION or NORMAL
                             (via hysteresis)


  NORMAL ──── battery < 10% ──────────────────────────────────────────► DOCKING
                                                                         │
                                                                docking_complete()
                                                                         │
                                                                         ▼
                                                                      NORMAL

  NORMAL/CAUTION ── important node crash ──────────────────────────► DEGRADED
  DEGRADED       ── node recovers        ──────────────────────────► CAUTION/NORMAL
```

---

## States

### INITIALIZING (0)

**Entry condition:** System power-on or post-reset.

**What happens:**
- Actuation is disabled; no motion permitted.
- Supervisor waits for all critical sensor streams to come online.
- Each sensor callback calls `_check_startup_sensors()` to complete startup early.
- If sensors do not come online within `startup_timeout_sec` (default 15 s), FSM transitions to **FAULT**.

**Exit conditions:**
- `mark_startup_complete()` called + next update with valid sensors → **NORMAL**
- Startup timeout exceeded → **FAULT**
- E-stop pressed → **SAFE_STOP**

---

### NORMAL (1)

**Entry condition:** All sensors healthy, no hazards detected.

**Capabilities:** Full actuation, full navigation, max 0.8 m/s.

**Exit conditions:**
| Trigger | Next State |
|---------|-----------|
| Human < 2.0 m | CAUTION |
| Battery 10–20 % | CAUTION |
| CPU temp 75–90 °C | CAUTION |
| Sensor in WARN state | CAUTION |
| Human < 0.5 m | DANGER |
| Bumper hit | DANGER |
| Cliff detected | DANGER |
| LIDAR stale (`danger` mode) | DANGER |
| Battery < 10 % | DOCKING |
| Critical node crash | FAULT |
| CPU temp > 90 °C | FAULT |
| Servo/ODrive hardware fault | FAULT |
| E-stop pressed | SAFE_STOP |

---

### CAUTION (2)

**Entry condition:** Human nearby, sensor degraded, or battery/thermal warning.

**Capabilities:** Actuation on, navigation on, max **0.3 m/s**.

**Policy actions on entry:** `cap_velocity`, `announce_audio`, `update_led_eyes`,  
`update_display`, `notify_operator`, `log_incident`

**Hysteresis:** CAUTION does not drop to NORMAL until **3 consecutive clear cycles** (300 ms at 10 Hz).  
This prevents rapid flicker when a person is exactly at the 2.0 m boundary.

**Exit conditions:**
| Trigger | Next State |
|---------|-----------|
| Human < 0.5 m | DANGER |
| Any DANGER-class trigger | DANGER |
| Battery < 10 % | DOCKING |
| Critical crash | FAULT |
| E-stop | SAFE_STOP |
| All clear × 3 cycles | NORMAL |

---

### DANGER (3)

**Entry condition:** Imminent hazard — human very close, bumper contact, cliff edge, or critical sensor loss.

**Capabilities:** All motion STOPPED. Actuation disabled. Navigation cancelled.

**Policy actions on entry:** `zero_velocity`, `cancel_navigation`, `disable_actuation`,  
`announce_audio`, `update_led_eyes`, `update_display`, `log_incident`, `notify_operator`

**Hysteresis:** DANGER requires **5 consecutive clear cycles** (500 ms) before relaxing  
to CAUTION. This prevents the robot from resuming motion too quickly after a person walks away.

**Exit conditions:**
| Trigger | Next State |
|---------|-----------|
| All clear × 5 cycles | CAUTION (then NORMAL if still clear) |
| Critical crash | FAULT |
| E-stop | SAFE_STOP |

---

### DOCKING (4)

**Entry condition:** Battery below `battery_dock_pct` (10 %).

**Capabilities:** Actuation on, navigation on, max **0.2 m/s** (slow approach to dock).

**Policy actions on entry:** `cancel_navigation` (current goal), `initiate_docking`,  
`announce_audio`, `update_led_eyes`, `update_display`, `notify_operator`

**Special rule:** DOCKING does NOT exit automatically when battery reads higher  
(charging not stable until `docking_complete()` is confirmed). It exits only when  
the docking controller calls `fsm.docking_complete()`.

**Exit conditions:**
| Trigger | Next State |
|---------|-----------|
| `docking_complete()` | NORMAL |
| Critical crash | FAULT |
| E-stop | SAFE_STOP |

---

### DEGRADED (5)

**Entry condition:** A CLASS_B/CLASS_C (ESSENTIAL or IMPORTANT) node has crashed  
and cannot be restarted within `max_restart_attempts`.

**Capabilities:** Actuation on, navigation on, max **0.3 m/s**.  
Specific capability depends on which module crashed (navigation planner vs. LLM).

**Policy actions on entry:** `cap_velocity`, `update_led_eyes`, `update_display`,  
`notify_operator`, `log_incident`

**Exit conditions:**
| Trigger | Next State |
|---------|-----------|
| Module recovers | NORMAL or CAUTION |
| Critical crash | FAULT |
| E-stop | SAFE_STOP |

---

### FAULT (6)

**Entry condition:** Hardware fault, critical software crash, overheating, or startup timeout.

**Capabilities:** ALL MOTION STOPPED. Manual operator intervention required.

**Policy actions on entry:** `zero_velocity`, `cancel_navigation`, `disable_actuation`,  
`announce_audio`, `update_led_eyes`, `update_display`, `log_incident`,  
`notify_operator`, `request_human_help`

**Locked:** FSM will NOT leave FAULT without an explicit `reset(operator_id, reason)` call.  
This call requires a human operator to positively acknowledge the fault.

**Exit conditions:**
| Trigger | Next State |
|---------|-----------|
| `reset()` called | INITIALIZING (re-runs startup) |
| E-stop (still reachable) | SAFE_STOP |

---

### SAFE_STOP (7)

**Entry condition:** Hardware e-stop button pressed OR software `trigger_estop` action.

**Capabilities:** ALL MOTION STOPPED. Motor power physically cut (relay asserted).

**Policy actions on entry:** `trigger_estop`, `update_led_eyes`, `update_display`,  
`log_incident`, `notify_operator`

**Locked:** FSM will NOT leave SAFE_STOP until:
1. E-stop button is physically released, AND
2. Operator calls `reset(operator_id, reason)`.

Releasing the e-stop button alone is **insufficient** — the operator must confirm  
via the reset service to prevent accidental restart.

**Exit conditions:**
| Trigger | Next State |
|---------|-----------|
| Button released AND `reset()` | INITIALIZING |

---

## Transition Priority (highest to lowest)

When multiple conditions are true simultaneously, this priority order applies:

```
1. E-stop hardware (→ SAFE_STOP)            [unconditional]
2. SAFE_STOP / FAULT guard (lock check)     [stay if locked]
3. INITIALIZING (wait for startup_complete) [stay if not ready]
4. DOCKING guard (stay until docking_complete)
5. Fault conditions                          (→ FAULT)
6. DANGER conditions                         (→ DANGER)
7. Battery forced docking                    (→ DOCKING)
8. Caution conditions                        (→ CAUTION)
9. Important node crash                      (→ DEGRADED)
10. All clear × hysteresis                   (→ relax state)
```

---

## Hysteresis Detail

Hysteresis prevents rapid state oscillation at threshold boundaries.

```
WITHOUT hysteresis (bad):
  cycle 1: human=1.9m → CAUTION
  cycle 2: human=2.1m → NORMAL   ← flip!
  cycle 3: human=1.9m → CAUTION  ← flip!
  (LED and audio announce firing 5×/sec)

WITH hysteresis (correct):
  cycle 1: human=1.9m → CAUTION   (clear_cycles=0)
  cycle 2: human=2.1m → CAUTION   (clear_cycles=1)
  cycle 3: human=2.1m → CAUTION   (clear_cycles=2)
  cycle 4: human=2.1m → NORMAL    (clear_cycles=3 ✓)
```

The `clear_cycles` counter resets to zero any time a new hazard is detected.

---

## Implementation Notes

### Pure Python, no I/O

The `SafetyStateMachine` class has zero external dependencies. This design enables:
- Unit testing without ROS2 (plain pytest, runs in CI without a robot)
- Deterministic replay of any scenario from logged sensor data
- Future migration to a different middleware without rewriting safety logic

### SensorSnapshot sentinel values

Fields with sentinel value `-1.0` mean "unknown / sensor offline":

```python
nearest_human_m = -1.0    # No person track (or tracker offline)
nearest_obstacle_m = -1.0  # LIDAR offline
```

The FSM treats unknown sensor data **conservatively**:
- `nearest_human_m == -1.0` → do NOT assume no humans present
- `nearest_obstacle_m == -1.0` → combined with `lidar_stale=True` → DANGER

### Thread safety

`SafetyStateMachine` is **not** thread-safe. The ROS2 supervisor node calls  
`update()` from a single timer callback. If you need to call `reset()` from a  
service callback running in a different thread, use `threading.Lock`.

---

## Adding a New State

1. Add the value to `SafetyLevel` enum.
2. Add a `SafetyStateProperties` entry in `STATE_PROPERTIES`.
3. Add entry/exit rules in `safety_policy.yaml` (and `default_policy.py`).
4. Add transition logic in `SafetyStateMachine._compute_next_state()`.
5. Add tests in `test_safety_state_machine.py`.
6. Update this document.
