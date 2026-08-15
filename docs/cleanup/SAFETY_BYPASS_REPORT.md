# Safety Bypass Report

**Phase 5.** The single most important question this entire cleanup audit asked: **can any UI, LLM, or AI-Pi-origin code reach motor/servo/Nav2 control without going through the required safety chain?** This report answers it with direct evidence, not architectural intent.

## Required safe flow (from the cleanup brief) — verified as REAL, not aspirational

```
UI / AI / LLM request
  ↓
Behavior Proposal
  ↓
Safety Gateway on Navigation Pi   (bonbon_motion_approval_gateway)
  ↓
Safety Supervisor validation      (bonbon_safety)
  ↓
Validated navigation/actuation command
  ↓
Execution                         (bonbon_hal)
```

## Evidence, package by package

**`bonbon_safety`** — `safety_gate_node` is confirmed the **sole publisher** of `/cmd_vel` and all gated servo/stepper command topics repo-wide (`nodes/safety_gate_node.py:423`, `_pub_vel.publish(scaled)`). Repo-wide grep for any other `create_publisher(Twist, "/cmd_vel"...)` or equivalent servo/stepper publisher returns nothing else. `safety_supervisor_node.py`'s only Nav2 ActionClient usage is to **cancel** goals on danger — it never sends goals.

**`bonbon_motion_approval_gateway`** — confirmed the **sole subscriber** of `/bonbon/behavior/proposal` and `/bonbon/operator/proposal`, and the sole publisher of `/bonbon/safety/approval` and `/bonbon/motion/approved_command`. Fail-closed: rejects everything if no `SafetyState` has been received (`nodes/motion_approval_gateway_node.py:61-70`). Makes no independent safety determination of its own — defers entirely to `bonbon_safety`'s published `SafetyState`.

**`bonbon_hal`** — the only package that writes to physical motor/servo/stepper hardware. `MotorDriver.set_wheel_speeds()` (`drivers/motor/motor_driver.py:54`) is called only from `motor_node._cb_wheel_command`, which subscribes only to `/bonbon/motor/wheel_command` — itself published only by `bonbon_base_controller`, which is fed only by `/cmd_vel` (the gated topic). Servo/stepper nodes subscribe only to gated, non-`_raw` topic names.

**`bonbon_actuation`** — publishes only to `*_command_raw` topics (`_publish_servo_commands`, `nodes/actuation_node.py:527`), which still route through `safety_gate_node` before reaching HAL. Own docstring: "no direct path to the HAL; the safety gate is never bypassed."

**`bonbon_base_controller`** — own docstring: "This node has NO authority of its own... never originates motion." Subscribes only to `/cmd_vel`, confirmed to have exactly one producer (`safety_gate_node`).

**`bonbon_navigation`** — enqueues Nav2 goals **exclusively** from `/bonbon/motion/approved_command` (`_on_approved_command` docstring: "The ONLY path that enqueues a Nav2 goal... never directly from /perception/behavior," `nodes/navigation_node.py:704-708`). Publishes velocity only to `/bonbon/cmd_vel_raw`, itself gated. `safety/safety_stop_bridge.py:8`: "navigation node NEVER publishes directly to /cmd_vel."

**`bonbon_llm`** — `llm_orchestrator_node.py:50`: "LLM output NEVER reaches cmd_vel, nav2, or GPIO directly." `safety/command_filter.py` regex-blocks cmd_vel/nav2/motor patterns in any LLM-originated text before it can become a command. Confirmed zero `cmd_vel`/servo/Nav2-client code anywhere in the package.

**`bonbon_perception_ai`** — zero `cmd_vel`, servo-command, or ActionClient references found anywhere.

**`bonbon_patient_kiosk`** — `ros2_bridge.py:16`: "never publishes to `/cmd_vel`"; only publishes TTS requests.

**`bonbon_operator_api`** — no hardware/nav topic references found anywhere; pure API/dashboard layer with `safety/command_validator.py` gating what it does dispatch, and even the commands it dispatches (`command_api.py`) go through `_check_bridge_result`, which itself calls into the same gated ROS2 graph, not a direct hardware write.

**`bonbon_behavior_engine`** (aggregates LLM/perception/affective input) — publishes only to `/bonbon/behavior/proposal` (→ gateway) and `/bonbon/behavior/actuation` (→ `bonbon_actuation`, itself gated). No direct servo/motor/`cmd_vel` publisher anywhere in the package.

## Conclusion

**No bypass path exists.** Every motion-intent source in this repository — LLM, dashboard UI, patient kiosk, perception fusion, behavior engine — funnels through exactly one route: `proposal → bonbon_motion_approval_gateway (fail-closed) → /bonbon/motion/approved_command → bonbon_navigation / bonbon_actuation → *_raw topics → bonbon_safety/safety_gate_node → bonbon_hal`. This was checked by direct grep and docstring/code cross-reference across the full 44-package tree in this audit, not assumed from the architecture documentation alone.

**One residual item, not a bypass:** `bonbon_actions`' `ExecuteMotionSequence.action` interface has no consuming node located anywhere in the repo (interface-only, `bonbon_actions` package contains just the `.action` definition). This means it's currently inert — nothing can misuse it because nothing uses it at all. Flagged so that if a future task wires a consumer for it, that consumer is built to route through the gate from day one, not retrofitted later. See `UNSAFE_CONTROL_PATH_FIX_REPORT.md`.
