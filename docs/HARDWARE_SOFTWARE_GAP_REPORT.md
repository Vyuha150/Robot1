# Hardware/Software Gap Report (Three-Pi Split)

**Date:** 2026-07-01
**Scope:** Every case where physical hardware named in the three-Pi brief has
no corresponding software today, ranked by severity. Read-only audit output —
no code was changed to produce this report.

## Severity ranking

1. **CRITICAL — blocks the robot from moving at all**
2. **HIGH — blocks a named capability entirely**
3. **MEDIUM — capability works via a generic fallback but loses fidelity**
4. **LOW — cosmetic/optimization**

---

## 1. RESOLVED (Phase 6): Pi-3 base-drive actuation now implemented

**Hardware:** Cytron SmartDrive MDDS30 dual 30A motor driver + Rhino 24V
60RPM 100W drive motors.

**Original finding (2026-07-01):** No file in the repository mentioned
"cytron", "mdds30", or any wheel/base motor controller — the single most
severe gap in the entire repo, true regardless of the 3-Pi split.

**Resolution (Phase 6, same date):**
- `bonbon_hal/drivers/motor/cytron_mdds30_driver.py` —
  `CytronMDDS30Driver`, using Cytron's documented Simplified Serial
  Interface (one byte per channel over UART). Mirrors every other real
  driver's lazy-SDK-import + honest-`DriverFault` pattern
  (`OrbbecDriver`, `RplidarDriver`, `OAKDLiteDriver`). `has_encoders =
  False` honestly, since the MDDS30 reports no encoder ticks and whether
  the Rhino motors have encoders fitted is unconfirmed —
  `read_wheels()` is an explicit open-loop estimate, never fabricated
  closed-loop odometry. `bonbon_hal/nodes/motor_node.py` is the thin
  ROS2 wrapper, added to `hal.launch.py` behind a new `launch_motor` flag
  (defaults on; explicitly disabled in Pi-2's `human_ai_bringup.launch.py`
  since it's Pi-3 hardware).
- New `bonbon_base_controller` package (kinematics/policy layer, same
  HAL/policy split as `camera_node`/`vision_node`): `DiffDriveKinematics`
  converts the safety-gate-approved `/cmd_vel` into per-wheel speeds
  (clamping preserves the requested turn ratio rather than independently
  clipping the faster wheel); `OdometryIntegrator` dead-reckons wheel
  distance readings into `nav_msgs/Odometry` for Nav2. 30 tests, both
  pure Python with no rclpy dependency.

**Still open:** `wheel_base_m` (default 0.40m) is a placeholder pending
physical measurement during Pi-3 hardware bring-up — see
`bonbon_base_controller/README.md`. Neither driver has been run against
real hardware in this session (no Pi-3 board available); `has_encoders`
honesty means odometry accuracy is capped until real encoders (if any)
are confirmed and wired in.

## 2. CRITICAL: Pi-3 has no NEMA 17 stepper support

**Hardware:** NEMA 17 closed-loop steppers (role in the robot not fully
specified by the brief beyond "actuation").

**Finding:** Zero matches for "nema" or "stepper" anywhere in the repository.

**Impact:** Unknown severity until it's confirmed which joint(s) the steppers
drive — if they're load-bearing for arm/head motion alongside the Dynamixel
servos, this is CRITICAL; if they're a planned-but-not-yet-required future
joint, it's lower. Flagging as CRITICAL pending clarification since the
brief lists it alongside the drive motors as core Pi-3 hardware.

**Required development:** new stepper driver (likely via TMC-family closed-
loop driver + step/dir GPIO, or CAN/serial if the steppers have integrated
controllers) and a `bonbon_stepper_controller` node, per the brief's
Phase 6 package naming.

## 3. HIGH: OAK-D Lite camera has no driver

**Hardware:** Luxonis OAK-D Lite autofocus camera (Pi-2).

**Finding:** `bonbon_hal/drivers/camera/` contains `orbbec_driver.py` (Orbbec
Astra Mini RGB-D) and `usb_camera_driver.py` (generic V4L2/OpenCV). No
`depthai` import, no OAK-D/Luxonis driver anywhere. The camera node's backend
selector (`camera_node.py`) only recognizes `"usb"`, `"orbbec"`, `"mock"`.

**Impact:** On real Pi-2 hardware, an OAK-D Lite plugged in over USB will
likely enumerate as a generic UVC device and partially work through
`UsbCameraDriver` (RGB stream only), but loses: the depth stream, onboard
autofocus control, and any on-device neural inference the OAK-D's own Myriad
X chip could offload (a secondary, optional benefit — Hailo is still the
primary accelerator per the architecture).

**Required development:** new `OAKDLiteDriver` using the `depthai` Python
SDK, added as a third real backend (`"oakd"`) alongside `orbbec`/`usb`/
`mock`, non-duplicating the existing camera_node's single-owner-of-the-device
pattern.

## 4. MEDIUM: PAM8610 amplifier has no dedicated control

**Hardware:** 4Ω 10W speaker driven by a PAM8610 2×10W amplifier (Pi-2).

**Finding:** `AlsaSpeakerDriver` (`bonbon_hal/drivers/speaker/`) plays audio
through generic ALSA/`amixer` volume control. No PAM8610-specific gain
staging, mute-pin control, or power-state management.

**Impact:** Audio output works today through the generic path. The gap is
optimization/fidelity, not a missing capability — LOW-to-MEDIUM depending on
whether the PAM8610's mute/standby pins are wired to a GPIO that needs
explicit software control (unknown without hardware access — this must be
verified on real Pi-2 hardware, not assumed).

**Required development:** optional PAM8610-aware extension to
`AlsaSpeakerDriver`, or confirm during Phase 9 hardware bring-up that generic
ALSA control is sufficient and downgrade this item.

## 5. MEDIUM: Face recognition has no standalone identity API

**Hardware/software boundary:** not a hardware gap, but a software-surface
gap relevant to Pi-2's "face recognition" responsibility.

**Finding:** Real face detection+recognition (`bonbon_vision/face/
face_pipeline.py`) runs inline inside `vision_node`, producing `face_id`
embedded in `PersonState`. The standalone `bonbon_perception/nodes/
face_node.py` is explicitly quarantined (orphaned duplicate, zero
dependents, disabled in bringup — comment at the top of the file says so).

**Impact:** Face identity is being computed but is not independently
queryable (e.g. no REST `/perception/faces/identify` endpoint) — it rides
along inside person-tracking output only.

**Required development:** none required for the underlying capability to
work; Phase 8 (dashboard integration) should surface `face_id` as part of
person-tracking dashboard cards rather than resurrecting the quarantined
node.

## 6. LOW: 10.1" touchscreen kiosk mode not configured

**Hardware:** 10.1" HDMI capacitive touchscreen (Pi-1).

**Finding:** No kiosk-launch script, no fullscreen/autologin config, no
touch-gesture handling in the React frontend.

**Impact:** The dashboard works in a normal browser window; it does not yet
auto-launch fullscreen on boot or handle touch-specific interaction patterns
(long-press, swipe).

**Required development:** deployment-layer only (Chromium `--kiosk --app=
http://localhost:8000/dashboard`, autologin `.desktop` entry, display
resolution config) — not a ROS2/backend change. Belongs in Phase 8/13
deployment docs, not core software.

## 7. LOW: Dynamixel servo torque rating not confirmed against 25kgcm spec

**Hardware:** 25kgcm digital servos (head/arm), Pi-3.

**Finding:** `bonbon_hal/drivers/servo/dynamixel_driver.py` implements a
generic Dynamixel Protocol 2.0 driver. Dynamixel XL-series servos commonly
used in hobbyist/service robots are in the 20-25kgcm torque range, which is
compatible, but the exact part number/torque spec is not pinned down in
config.

**Impact:** Likely fine as-is; flagged for hardware bring-up verification
rather than as a code gap.

**Required development:** none unless hardware bring-up reveals a mismatch.

---

## Summary table

| # | Gap | Severity | Pi | New package needed |
|---|---|---|---|---|
| 1 | ~~No Cytron MDDS30 / Rhino drive-motor control~~ | **RESOLVED** (Phase 6) | Pi-3 | `bonbon_hal` (`CytronMDDS30Driver`+`motor_node`) + `bonbon_base_controller` |
| 2 | No NEMA 17 stepper support | CRITICAL (pending role clarification) | Pi-3 | `bonbon_stepper_controller` |
| 3 | ~~No OAK-D Lite driver~~ | **RESOLVED** (Phase 5) | Pi-2 | `OAKDLiteDriver` in `bonbon_hal` |
| 4 | No PAM8610-specific amp control | MEDIUM | Pi-2 | optional extension to `AlsaSpeakerDriver` |
| 5 | No standalone face-identity API | MEDIUM | Pi-2 | dashboard endpoint only, Phase 8 |
| 6 | No kiosk-mode touchscreen config | LOW | Pi-1 | deployment script only |
| 7 | Servo torque spec unconfirmed | LOW | Pi-3 | hardware verification only |
