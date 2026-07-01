# bonbon_base_controller

The kinematics/policy layer above `bonbon_hal`'s raw Cytron MDDS30 motor
driver — same HAL/policy split used everywhere else in this repo
(`camera_node` vs `vision_node`, `microphone_node` vs `speech_node`).

Fixes [`docs/HARDWARE_SOFTWARE_GAP_REPORT.md`](../../../docs/HARDWARE_SOFTWARE_GAP_REPORT.md)
item 1 (CRITICAL) alongside `bonbon_hal`'s `CytronMDDS30Driver`/
`motor_node`: before both existed, nothing in the repo could turn an
approved velocity command into physical wheel motion.

## What it does

- Subscribes `/cmd_vel` — the **final, already safety_gate_node-approved**
  `geometry_msgs/Twist`. This node has no motion authority of its own; it
  only converts an already-approved command into per-wheel speeds. It
  never originates motion and is not a second path to the motors.
- Converts to left/right wheel speeds (`DiffDriveKinematics`), publishing
  `/bonbon/motor/wheel_command` for `bonbon_hal`'s `motor_node` to execute.
- Integrates `bonbon_hal`'s wheel distance readings
  (`/bonbon/motor/wheel_state`) into a 2D pose (`OdometryIntegrator`),
  publishing `nav_msgs/Odometry` on `/bonbon/odometry/wheels` for Nav2.

## `wheel_base_m` needs hardware verification

The default (0.40 m) is a placeholder. Getting it wrong distorts both
directions: a requested turn radius on the way out (`Twist` → wheels), and
the estimated pose on the way back (wheels → odometry). Verify against the
physical robot during Pi-3 hardware bring-up before trusting Nav2's
localization on real hardware.

## No confirmed wheel encoders

`CytronMDDS30Driver.read_wheels()` is an **open-loop estimate** (integrates
the last commanded speed over elapsed time) — the MDDS30 itself reports no
encoder ticks, and whether the Rhino motors have encoders fitted is not
yet confirmed. `has_encoders=False` on that driver reflects this honestly.
Odometry from this package inherits that same accuracy ceiling: useful for
short-range dead reckoning, not a substitute for a real localization
source once one exists (AMCL against LiDAR, etc.).

## Core logic (fully unit-tested, no rclpy dependency)

- `core/diff_drive_kinematics.py` — `DiffDriveKinematics`. Clamping a
  too-fast command scales **both** wheels by the same factor rather than
  independently clipping the faster one, which would silently distort the
  requested turning radius. 15 tests.
- `core/odometry_integrator.py` — `OdometryIntegrator`. Mid-point (2nd-
  order) integration, correct first-call baselining (an absolute encoder
  reading is never misread as a delta), correct angle wrapping. 8 tests.
