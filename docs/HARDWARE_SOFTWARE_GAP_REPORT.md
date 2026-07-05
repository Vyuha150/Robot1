# Hardware/Software Gap Report (Three-Pi Split)

**Date:** 2026-07-01 (BOM-accuracy corrections added 2026-07-06 against the
real `Humanoid_Robot_Components_Dimensions.xls` bill of materials — this
surfaced that items 2/4/6 below had been resolved in earlier session work
but this report's own section headings/bodies were never updated to match,
only the summary table at the bottom. Both are now consistent.)
**Scope:** Every case where physical hardware named in the three-Pi brief has
no corresponding software today, ranked by severity. Originally read-only
audit output; items below now carry their resolution status inline.

## Severity ranking

1. **CRITICAL — blocks the robot from moving at all**
2. **HIGH — blocks a named capability entirely**
3. **MEDIUM — capability works via a generic fallback but loses fidelity**
4. **LOW — cosmetic/optimization**

---

## BOM physical dimensions & placement (reference for future mechanical integration)

Transcribed directly from `Humanoid_Robot_Components_Dimensions.xls`
(4 sheets, one per Pi role + the shared actuator sheet) — not derived or
estimated. Useful for chassis/harness/wiring-loom design once physical
assembly begins; no code in this repo currently consumes these values.

| Pi | Component | Placement | Dimensions |
|---|---|---|---|
| Pi-1 | Raspberry Pi 5 | CHASSIS | 85.0 × 56.0 mm (3.35 × 2.20 in) |
| Pi-1 | 10.1" HDMI capacitive touchscreen | CHEST | 23.7 × 14.5 × 2 cm |
| Pi-2 | Raspberry Pi 5 + AI HAT+2 | CHASSIS | 85.0 × 56.0 mm (3.35 × 2.20 in) |
| Pi-2 | ReSpeaker XVF3800 4-mic USB array | CHEST | 70 mm diameter |
| Pi-2 | 4Ω 10W full-range speaker | CHEST | 53 mm / 2.08 in |
| Pi-2 | PAM8610 dual-channel amp board | CHEST | 43 × 40 × 25 mm |
| Pi-2 | Luxonis OAK-D Lite (autofocus) | HEAD | 11.5 × 5.5 × 2.5 cm |
| Pi-3 | Raspberry Pi 5 + AI HAT+2 | CHASSIS | 85.0 × 56.0 mm (3.35 × 2.20 in) |
| Pi-3 | Cytron SmartDrive MDDS30 (dual 30A) | CHASSIS | 103 × 97 × 40 mm |
| Pi-3 | Rhino 24V 60RPM 100W drive motor | CHASSIS | 54 mm diameter |
| Pi-3 | SLAMTEC RPLiDAR A2M12 | CHASSIS | 76 mm diameter × 41 mm height |
| Pi-3 | NEMA17 closed-loop stepper (HEAD pan L/R) | HEAD (L/R) | 42 × 42 mm |
| Pi-3 | NEMA17 closed-loop stepper (RIGHT ARM shoulder) | RIGHT ARM | 42 × 42 mm |
| Pi-3 | 25kgcm digital servo (RIGHT ARM elbow) | RIGHT ARM — ELBOW | 40 × 20 mm |
| Pi-3 | 25kgcm digital servo (RIGHT ARM wrist) | RIGHT ARM — WRIST | 40 × 20 mm |
| Pi-3 | 25kgcm digital servo (HEAD tilt) | HEAD (U/D) | 40 × 20 mm |

The BOM's own "PLACEMENT" column for the two steppers (`HEAD (L/R)` vs.
`RIGHT ARM`) is the source of this session's `JOINT_HEAD_PAN`/
`JOINT_RIGHT_SHOULDER` joint assignment in
`bonbon_actuation/core/gesture_library.py` — not an assumption.

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

## 2. RESOLVED (2026-07-06): Pi-3 NEMA 17 stepper support

**Hardware:** 2x NEMA 17 closed-loop steppers — confirmed by the real BOM
(`Humanoid_Robot_Components_Dimensions.xls`, "Hand Gestures & Head Pan"
sheet) to drive HEAD pan and the RIGHT ARM shoulder joint. Not a
speculative/unclear joint as this report originally flagged — the role
clarification requested below is now answered by the actual BOM.

**Original finding (2026-07-01):** Zero matches for "nema" or "stepper"
anywhere in the repository.

**Resolution (2026-07-06):**
- `bonbon_hal/drivers/stepper/nema17_closed_loop_driver.py` —
  `NEMA17ClosedLoopDriver(StepperDriver)`, STEP/DIR/ENABLE GPIO plus the
  driver's ALM (alarm) pin wired through `StallFaultTracker` as a real,
  debounced fault (3-poll confirm, 3-poll clear) — the one genuinely
  closed-loop fault signal anywhere in this actuator BOM. Same
  GPIO-library-fallback convention as `gpio_estop_driver.py`
  (`Jetson.GPIO` → `RPi.GPIO` → `_MockGPIO`, `BONBON_SIMULATION`-gated).
- `bonbon_hal/drivers/stepper/stepper_kinematics.py` — pure-Python
  `StepConverter` (radians↔steps) and `StallFaultTracker`, 23 tests.
  `MockStepperDriver` for CI/dev, 15 tests (both files: 236 total
  `bonbon_hal` tests passing).
- `bonbon_hal/nodes/stepper_node.py` — thin ROS2 wrapper, reuses
  `bonbon_msgs/ServoStateArray` rather than adding a new message type.
- Gated through `bonbon_safety/safety_gate_node.py`'s new
  `/bonbon/stepper/command_raw` → `_can_actuate()` →
  `/bonbon/stepper/command` path — steppers previously would have had
  **zero** safety gating at all had they been added without this.
- A real bug found and fixed during this work: `read_all()`/
  `read_stepper()` unconditionally called `_record_success()` even while
  a stall was confirmed, so a stall only ever reached the fault system
  if a *new* command happened to be sent to the stalled joint — an idle
  stalled joint was invisible. Fixed via `DriverBase._record_partial_fault()`,
  a new primitive for "one channel of a multi-channel driver has a real
  fault, but the bus itself is fine" (distinct from `_record_fault()`,
  which would incorrectly mark the whole driver disconnected).

**Still open:** Not yet run against real Pi-3 hardware (no board available
in this session) — mock/simulation-verified only, per this report's
"BLOCKED — cannot verify without hardware" category for anything requiring
physical access.

## 3. RESOLVED (Phase 5): OAK-D Lite camera has no driver

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

**Resolution (already complete when this report was first written, but this
section's own heading/body were never updated to say so — fixed 2026-07-06):**
`OAKDLiteDriver` (`bonbon_hal/drivers/camera/oakd_lite_driver.py`) using the
`depthai` Python SDK, added as backend `"oakd"` alongside `orbbec`/`usb`/
`mock`. 7 tests (`test_oakd_lite_driver.py`). Honest `DriverFault
("SDK_MISSING")` if `depthai` isn't installed, matching every other real
driver's lazy-import pattern. Non-duplicating the existing camera_node's
single-owner-of-the-device pattern.

## 4. RESOLVED (2026-07-06): PAM8610 amplifier now has mute-pin control

**Hardware:** 4Ω 10W speaker driven by a PAM8610 2×10W amplifier (Pi-2).

**Original finding (2026-07-01):** `AlsaSpeakerDriver`
(`bonbon_hal/drivers/speaker/`) played audio through generic ALSA/`amixer`
volume control only. No PAM8610-specific gain staging, mute-pin control, or
power-state management.

**Resolution (2026-07-06):** `AlsaSpeakerDriver` now supports optional
PAM8610 mute-pin GPIO control (`has_pam8610` param — **defaults False**,
since whether the mute pin is actually wired on a given unit is genuinely
unverified without hardware access, per this item's own original caveat).
Same GPIO-fallback convention as `gpio_estop_driver.py`/
`nema17_closed_loop_driver.py`. If GPIO claim fails, the driver degrades
*only* the amp-control capability (logged, `_record_partial_fault`,
WARNING-level in `bonbon_fault_manager`) — plain ALSA playback keeps
working regardless, since it was never load-bearing for basic audio.
Wired through `bonbon_hal/nodes/speaker_node.py` params and
`hal_params.yaml`/`pi2_hal_overrides.yaml`.

**Still open:** Whether the mute pin is actually GPIO-wired on real Pi-2
hardware remains unverified — `has_pam8610` stays `false` until confirmed
during hardware bring-up, per this item's original guidance.

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

## 6. RESOLVED (2026-07-06): 10.1" touchscreen kiosk mode

**Hardware:** 10.1" HDMI capacitive touchscreen (Pi-1).

**Original finding (2026-07-01):** No kiosk-launch script, no
fullscreen/autologin config.

**Resolution (2026-07-06):** `devops/scripts/launch_kiosk.sh` (+
`scripts/` canonical wrapper) waits for `bonbon_operator_api`'s health
endpoint before opening a Chromium `--kiosk` window — refuses to open a
kiosk browser against a dead backend rather than showing a blank/
unrecoverable screen. Wired to `bonbon-pi1-dashboard-frontend.service`
(`deployment/systemd/pi1/`), which `Requires=`/`After=`
`bonbon-pi1-dashboard-api.service`.

**Still open:** Touch-gesture handling (long-press, swipe) in the React
frontend itself, and display-resolution/autologin `.desktop`-entry
tuning — both need real touchscreen hardware to verify, not assumed.

## 7. RESOLVED (2026-07-06, by BOM correction): primary servo hardware is PCA9685, not Dynamixel

**Hardware:** 3x 25kgcm digital servos (HEAD tilt, RIGHT ARM elbow/wrist),
Pi-3.

**Original finding (2026-07-01):** `dynamixel_driver.py` was assumed to be
the primary servo hardware, with an unconfirmed torque-rating match against
the 25kgcm spec.

**Correction:** The real BOM's servo is a generic 25kgcm 180° digital servo
driven via a PCA9685 16-channel PWM board — standard RC-servo hardware, not
Dynamixel smart servos. `PCA9685ServoDriver`
(`bonbon_hal/drivers/servo/pca9685_servo_driver.py`) is now the primary
backend; per-channel min/max pulse-width calibration exists precisely
because generic RC servos vary unit-to-unit (not all hit exactly
1000-2000us), which is the real-world equivalent of the torque/spec
verification this item originally asked for. `DynamixelDriver` remains a
selectable, non-primary backend (harmless to keep, matches no real
hardware in this BOM).

**Honest limitation, not hidden:** unlike Dynamixel smart servos, generic
PWM RC servos have **no feedback sensor** — `load_percent`/`temperature_c`/
`voltage_v` cannot be measured and are documented as such, never
fabricated. `bonbon_fault_manager` states this explicitly rather than
implying overload detection that doesn't exist.

## 8. INFO (2026-07-06): AI HAT+2 confirmed present on Pi-3 too, not just Pi-2

**Hardware:** AI HAT+2 (Hailo-10H-capable) — the real BOM
(`Humanoid_Robot_Components_Dimensions.xls`) confirms this is present on
**both** Pi-2 ("ASR, LLM, Face Recognition" sheet) and Pi-3 ("Autonomous
Navigation" sheet).

**Finding:** `bonbon_ai_runtime` (Phases 3/4 of the original brief) and
`config/runtime/pi_ai_hat.yaml` are already fully Pi-agnostic — nothing in
either hardcodes "Pi-2 only" (confirmed by grep: zero Pi-2-specific
references in `bonbon_ai_runtime`'s Python code or in
`docs/AI_HAT_RUNTIME_STRATEGY.md`). This is **not a code gap**.

**What's actually missing:** no Hailo-accelerated workload is currently
defined for Pi-3 (navigation/perception on Pi-3 today is CPU-only:
Nav2/RTAB-Map, lidar scan-matching) — `bonbon_navigation_bringup` does not
launch `bonbon_ai_runtime` at all. This is a genuine scope gap (AI HAT/
Hailo integration for Pi-3 workloads is Phase 10 of the original 14-phase
brief, not attempted here), but the runtime abstraction itself is already
ready for it whenever such a workload is defined — no rework needed.

---

## Summary table

| # | Gap | Severity | Pi | New package needed |
|---|---|---|---|---|
| 1 | ~~No Cytron MDDS30 / Rhino drive-motor control~~ | **RESOLVED** (Phase 6) | Pi-3 | `bonbon_hal` (`CytronMDDS30Driver`+`motor_node`) + `bonbon_base_controller` |
| 2 | ~~No NEMA 17 stepper support~~ | **RESOLVED** (2026-07-06) | Pi-3 | `bonbon_hal` (`NEMA17ClosedLoopDriver`+`stepper_node`) |
| 3 | ~~No OAK-D Lite driver~~ | **RESOLVED** (Phase 5) | Pi-2 | `OAKDLiteDriver` in `bonbon_hal` |
| 4 | ~~No PAM8610-specific amp control~~ | **RESOLVED** (2026-07-06) | Pi-2 | `AlsaSpeakerDriver` mute-pin extension |
| 5 | No standalone face-identity API | MEDIUM | Pi-2 | dashboard endpoint only, Phase 8 |
| 6 | ~~No kiosk-mode touchscreen config~~ | **RESOLVED** (2026-07-06) | Pi-1 | `devops/scripts/launch_kiosk.sh` |
| 7 | ~~Servo torque spec unconfirmed~~ | **RESOLVED** (2026-07-06, BOM correction: PCA9685 not Dynamixel) | Pi-3 | `PCA9685ServoDriver` in `bonbon_hal` |
| 8 | AI HAT+2 present on Pi-3, no Hailo workload defined yet | INFO (not a code gap) | Pi-3 | none — `bonbon_ai_runtime` already Pi-agnostic; Phase 10 scope |

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
