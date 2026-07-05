"""bonbon_fault_manager.core.component_rules
===============================================
Concrete, per-real-component classification of HalFault events into the
FaultLevel taxonomy plus actionable recovery guidance.

This intentionally does NOT try to be a generic "map severity to level"
function for its primary cases -- that would defeat the purpose (the
project brief explicitly asked for per-component detection, not generic
boilerplate). Every device/error_code pair that a real driver in this
BOM can actually emit (see docs/HARDWARE_SOFTWARE_GAP_REPORT.md and the
`bonbon_hal/drivers/*` DriverFault call sites) has an explicit entry
below. Only device/error_code combinations NOT anticipated fall back to
classify()'s severity-based default, which is honest about being
unclassified rather than guessing at a specific severity.

`device` values come from bonbon_hal's HalNodeBase.DEVICE_NAME (the
field HalFault.device actually carries) -- coarse categories such as
"camera"/"microphone"/"stepper", not the specific chip. error_code is
what actually distinguishes e.g. a PCA9685 servo fault from a Dynamixel
one, since driver-specific DriverFault error codes already encode that
detail (e.g. "I2C_INIT_FAILED" only PCA9685 raises; "PORT_OPEN_FAILED"
only Dynamixel raises).
"""

from __future__ import annotations

from dataclasses import dataclass

from .fault_taxonomy import FaultLevel


@dataclass(frozen=True)
class ComponentInfo:
    subsystem: str
    affected_pi: str


# Which Pi/subsystem owns each HAL device category, per the confirmed BOM
# (docs/HARDWARE_SOFTWARE_GAP_REPORT.md, THREE_PI_ROS2_NODE_GRAPH.md).
DEVICE_INFO: dict[str, ComponentInfo] = {
    "microphone": ComponentInfo("audio", "pi2"),  # ReSpeaker XVF3800
    "camera": ComponentInfo("vision", "pi2"),  # OAK-D Lite
    "speaker": ComponentInfo("audio", "pi2"),  # 4ohm speaker + PAM8610
    "motor": ComponentInfo("navigation", "pi3"),  # Cytron MDDS30 + Rhino motors
    "lidar": ComponentInfo("navigation", "pi3"),  # RPLiDAR A2M12
    "stepper": ComponentInfo("actuation", "pi3"),  # NEMA17 closed-loop
    "servo": ComponentInfo("actuation", "pi3"),  # PCA9685 (+ Dynamixel backend)
    "battery": ComponentInfo("power", "shared"),
    "imu": ComponentInfo("navigation", "pi3"),
    "estop": ComponentInfo("safety", "pi3"),
}
_UNKNOWN_INFO = ComponentInfo("unknown", "unknown")

# (device, error_code) -> (FaultLevel, recovery_action). Every action
# string names a concrete next step, not "check the logs."
_RULES: dict[tuple[str, str], tuple[FaultLevel, str]] = {
    # ── ReSpeaker XVF3800 (mic array, Pi-2) ─────────────────────────────
    ("microphone", "USB_DISCONNECTED"): (
        FaultLevel.CRITICAL,
        "Reseat/replace the ReSpeaker USB connection and verify udev "
        "permissions; ASR has no audio input until reconnected.",
    ),
    ("microphone", "CONNECT_ERROR"): (
        FaultLevel.FAULT,
        "Check ReSpeaker XVF3800 USB enumeration (lsusb) and that "
        "sounddevice can see the 4-mic input device; restart mic_node.",
    ),
    ("microphone", "READ_ERROR"): (
        FaultLevel.DEGRADED,
        "Transient audio read failure -- node auto-reconnects after "
        "consecutive-error threshold; escalate if this repeats.",
    ),
    ("microphone", "SDK_MISSING"): (
        FaultLevel.BLOCKED,
        "sounddevice not installed on Pi-2 -- ASR unusable until "
        "'pip install sounddevice' and node restart.",
    ),
    ("microphone", "RECONNECT_EXHAUSTED"): (
        FaultLevel.CRITICAL,
        "Automatic reconnect exhausted -- manually power-cycle the " "ReSpeaker/Pi-2 USB hub.",
    ),
    # ── OAK-D Lite camera (Pi-2) ─────────────────────────────────────────
    ("camera", "SDK_MISSING"): (
        FaultLevel.BLOCKED,
        "depthai SDK not installed on Pi-2 -- face recognition/vision "
        "unusable until 'pip install depthai' and node restart.",
    ),
    ("camera", "READ_ERROR"): (
        FaultLevel.DEGRADED,
        "OAK-D Lite pipeline read failure (possible low FPS/USB "
        "bandwidth contention) -- check the USB3 port and whether "
        "other USB devices share its controller.",
    ),
    ("camera", "RECONNECT_EXHAUSTED"): (
        FaultLevel.CRITICAL,
        "OAK-D Lite unreachable after repeated reconnects -- check "
        "autofocus lens obstruction, the USB-C cable, and power draw.",
    ),
    # ── PAM8610 amp + speaker (Pi-2) ─────────────────────────────────────
    ("speaker", "PAM8610_GPIO_INIT_FAILED"): (
        FaultLevel.WARNING,
        "Amp mute-pin GPIO claim failed -- plain ALSA playback still "
        "works; verify mute-pin wiring/GPIO permissions if amp mute "
        "control is actually required on this unit.",
    ),
    ("speaker", "SDK_MISSING"): (
        FaultLevel.BLOCKED,
        "sounddevice not installed on Pi-2 -- TTS output unusable.",
    ),
    ("speaker", "PLAY_ERROR"): (
        FaultLevel.DEGRADED,
        "One utterance failed to play -- transient unless this "
        "repeats across consecutive TTS requests.",
    ),
    ("speaker", "DEVICE_NOT_FOUND"): (
        FaultLevel.FAULT,
        "Configured ALSA output device not found -- verify "
        "'aplay -l'/'amixer' lists the PAM8610 output.",
    ),
    # ── Cytron MDDS30 + Rhino drive motors (Pi-3) ───────────────────────
    ("motor", "SERIAL_OPEN_FAILED"): (
        FaultLevel.CRITICAL,
        "Cytron MDDS30 serial port unavailable -- check the "
        "USB-to-serial/UART cable and port permissions (dialout group).",
    ),
    ("motor", "WRITE_ERROR"): (
        FaultLevel.FAULT,
        "Motor command write failed -- base_controller must treat "
        "this as navigation-halting; verify the serial cable.",
    ),
    ("motor", "SDK_MISSING"): (
        FaultLevel.BLOCKED,
        "pyserial not installed on Pi-3 -- drive motors unusable.",
    ),
    ("motor", "RECONNECT_EXHAUSTED"): (
        FaultLevel.CRITICAL,
        "Base motors unreachable after repeated reconnects -- "
        "navigation must fall back to full stop.",
    ),
    # ── RPLiDAR A2M12 (Pi-3) ─────────────────────────────────────────────
    ("lidar", "HEALTH_ERROR"): (
        FaultLevel.FAULT,
        "RPLiDAR reports an internal health warning/error -- check "
        "for motor spin-down or an obstruction; may need power-cycle.",
    ),
    ("lidar", "SCAN_ENDED"): (
        FaultLevel.DEGRADED,
        "Scan iterator ended unexpectedly -- verify the lidar motor "
        "is spinning and USB bandwidth is sufficient.",
    ),
    ("lidar", "READ_ERROR"): (
        FaultLevel.DEGRADED,
        "Transient scan read failure -- watch for repeats before " "escalating.",
    ),
    ("lidar", "SDK_MISSING"): (
        FaultLevel.BLOCKED,
        "rplidar SDK not installed on Pi-3 -- obstacle avoidance " "unusable.",
    ),
    ("lidar", "RECONNECT_EXHAUSTED"): (
        FaultLevel.CRITICAL,
        "RPLiDAR unreachable after repeated reconnects -- autonomous "
        "navigation must be disabled until resolved.",
    ),
    # ── NEMA17 closed-loop steppers -- HEAD pan + RIGHT ARM shoulder (Pi-3) ──
    ("stepper", "STALLED"): (
        FaultLevel.FAULT,
        "One or more stepper joints lost sync (stall/alarm asserted) "
        "-- inspect the joint for mechanical obstruction, then call "
        "clear_stall() once physically clear.",
    ),
    ("stepper", "GPIO_INIT_FAILED"): (
        FaultLevel.CRITICAL,
        "Stepper GPIO init failed -- check STEP/DIR/ENABLE/ALM pin " "wiring.",
    ),
    ("stepper", "RECONNECT_EXHAUSTED"): (
        FaultLevel.CRITICAL,
        "Stepper bus unreachable -- gestures using stepper joints "
        "(head pan, right shoulder) must be suppressed.",
    ),
    # ── PCA9685 servo (+ Dynamixel backend) -- elbow/wrist/head-tilt (Pi-3) ──
    ("servo", "I2C_INIT_FAILED"): (
        FaultLevel.CRITICAL,
        "PCA9685 I2C init failed -- verify the I2C bus/address "
        "(default 0x40) and wiring/pull-ups.",
    ),
    ("servo", "I2C_WRITE_ERROR"): (
        FaultLevel.FAULT,
        "PCA9685 write failed -- possible I2C bus contention/noise; "
        "servo commands may be silently dropped until this clears.",
    ),
    ("servo", "SDK_MISSING"): (
        FaultLevel.BLOCKED,
        "smbus2 not installed on Pi-3 -- PWM servo control unusable.",
    ),
    ("servo", "PORT_OPEN_FAILED"): (
        FaultLevel.CRITICAL,
        "Dynamixel serial port unavailable -- verify port/baud config "
        "(Dynamixel is a selectable backend, not the primary hardware "
        "per the real BOM).",
    ),
    ("servo", "BAUD_FAILED"): (
        FaultLevel.CRITICAL,
        "Dynamixel baud-rate configuration failed -- verify port "
        "config (selectable backend, not primary BOM hardware).",
    ),
    # ── Battery monitor -- INA226 (shared) ──────────────────────────────
    ("battery", "I2C_CONNECT_FAILED"): (
        FaultLevel.CRITICAL,
        "Battery monitor (INA226) unreachable -- power telemetry "
        "lost; verify I2C wiring/address.",
    ),
    ("battery", "WRONG_DEVICE"): (
        FaultLevel.CRITICAL,
        "Unexpected device ID at the INA226 I2C address -- verify "
        "wiring/address is not shared with another peripheral.",
    ),
    ("battery", "I2C_READ_ERROR"): (
        FaultLevel.DEGRADED,
        "Transient battery telemetry read failure -- watch for " "repeats before escalating.",
    ),
    ("battery", "SDK_MISSING"): (
        FaultLevel.BLOCKED,
        "smbus2 not installed -- battery telemetry unusable.",
    ),
    # ── IMU -- MPU6050 (Pi-3) ────────────────────────────────────────────
    ("imu", "I2C_CONNECT_FAILED"): (
        FaultLevel.CRITICAL,
        "IMU unreachable -- odometry/base_controller orientation "
        "estimate degraded; verify I2C wiring/address.",
    ),
    ("imu", "WRONG_DEVICE"): (
        FaultLevel.CRITICAL,
        "Unexpected device ID at the MPU6050 I2C address -- verify " "wiring/address.",
    ),
    ("imu", "I2C_READ_ERROR"): (
        FaultLevel.DEGRADED,
        "Transient IMU read failure -- watch for repeats before " "escalating.",
    ),
    ("imu", "SDK_MISSING"): (
        FaultLevel.BLOCKED,
        "smbus2 not installed -- IMU unusable.",
    ),
    # ── E-stop (Pi-3, safety-critical -- any fault here is severe) ──────
    ("estop", "GPIO_INIT_FAILED"): (
        FaultLevel.BLOCKED,
        "E-stop GPIO init failed -- SAFETY CRITICAL: the robot must "
        "not be allowed to move without a verified e-stop path.",
    ),
}

# Recovery announcements (is_recovered=True from HalNodeBase) always map
# to OK regardless of which error_code originally faulted.
_RECOVERED_LEVEL = FaultLevel.OK
_RECOVERED_ACTION = "Recovered -- no action needed."

# HalFault.severity (0=INFO..3=FATAL) -> FaultLevel, used ONLY for
# device/error_code combinations with no explicit rule above. Deliberately
# conservative (never auto-escalates to CRITICAL/BLOCKED) since those top
# two levels represent a judgment call this fallback cannot honestly make
# without a component-specific rule.
_SEVERITY_FALLBACK = {
    0: FaultLevel.OK,  # INFO
    1: FaultLevel.WARNING,  # WARN
    2: FaultLevel.DEGRADED,  # ERROR
    3: FaultLevel.FAULT,  # FATAL
}


def component_info(device: str) -> ComponentInfo:
    return DEVICE_INFO.get(device, _UNKNOWN_INFO)


def classify(
    device: str,
    error_code: str,
    severity: int,
    is_recovered: bool = False,
) -> tuple[FaultLevel, str]:
    """Classify one HalFault event into (FaultLevel, recovery_action).

    Recovery announcements always win over any stale rule lookup.
    Known (device, error_code) pairs get a rule with concrete, specific
    guidance. Unknown pairs fall back to the (deliberately conservative)
    severity mapping and say so honestly in the returned action text.
    """
    if is_recovered:
        return _RECOVERED_LEVEL, _RECOVERED_ACTION

    rule = _RULES.get((device, error_code))
    if rule is not None:
        return rule

    level = _SEVERITY_FALLBACK.get(severity, FaultLevel.DEGRADED)
    action = (
        f"No component-specific rule yet for {device}/{error_code} -- "
        "see logs; consider adding a rule to "
        "bonbon_fault_manager.core.component_rules."
    )
    return level, action
