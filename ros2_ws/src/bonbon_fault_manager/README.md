# bonbon_fault_manager

Classifies raw hardware/safety fault signals into a single, live
per-component registry with the six-level taxonomy
`OK / WARNING / DEGRADED / FAULT / CRITICAL / BLOCKED`, plus concrete,
component-specific recovery guidance for every real part in the BOM
(ReSpeaker XVF3800, OAK-D Lite, PAM8610 amp, Cytron MDDS30, RPLiDAR
A2M12, NEMA17 closed-loop stepper, PCA9685 servo) — see
`core/component_rules.py` for the full rule table.

This does **not** duplicate anything that already exists:

- `/bonbon/hal/fault` (`HalFault`) is already published by every HAL node
  (`bonbon_hal/base/health_reporter.py`) on driver fault/recovery — this
  node only *classifies* those events, it never polls hardware itself.
- `bonbon_safety.nodes.watchdog_node` already monitors node-liveness
  heartbeats (`ModuleHealth`) and restarts stale nodes — this package
  answers "which physical component is broken and how bad," not "which
  ROS2 process is still alive."
- `bonbon_operator_api`'s existing `component-health` /
  `degraded-mode` / `distributed-status` dashboard channels are
  **extended** to also read `/bonbon/fault_manager/registry`, not
  replaced.

## What it publishes

`/bonbon/fault_manager/registry` (`bonbon_msgs/ComponentFaultArray`),
`RELIABLE`+`TRANSIENT_LOCAL` so a late-joining dashboard client gets the
current registry immediately — republished on every update and on a
1 Hz timer (`republish_rate_hz` param).

## What it subscribes to

- `/bonbon/hal/fault` (`bonbon_msgs/HalFault`) — every HAL driver fault
  and recovery event, from any Pi (all three Pis share `ROS_DOMAIN_ID`,
  so this works via normal DDS discovery with no bridging).
- `/bonbon/safety/state` (`bonbon_msgs/SafetyState`) — overall safety
  state (mapped via a conservative state-name table) and
  `degraded_modules` (reconciled each message: modules no longer listed
  are treated as recovered and removed from the registry).

## Core logic (fully unit-tested, no rclpy dependency — 48 tests)

- `core/fault_taxonomy.py` — the `FaultLevel` enum, `worst()` rollup,
  `is_actionable()`.
- `core/component_rules.py` — `classify(device, error_code, severity,
  is_recovered)`. Every `(device, error_code)` pair a real driver in
  this BOM can actually emit has an explicit rule with concrete
  recovery guidance; unanticipated pairs fall back to a deliberately
  conservative severity mapping (never auto-escalates to
  CRITICAL/BLOCKED without an explicit rule) and say so honestly in the
  returned action text.
- `core/fault_registry.py` — `FaultRegistry`, the live per-component
  state machine the node wraps. Three update paths: `update_from_hal_fault()`,
  `sync_degraded_modules()`, `update_safety_supervisor()`.

`nodes/fault_manager_node.py` is a thin ROS2 LifecycleNode adapter over
`FaultRegistry` — not importable/testable in this dev sandbox (no
`rclpy`), verified via `python -m py_compile` only.
