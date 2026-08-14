"""bonbon_hardware_telemetry.core.joint_metrics -- arm/head joints, both
actuator families reused unchanged from bonbon_hal
.nodes.{stepper_node,servo_node}.py's own bonbon_msgs/ServoState fields:

- 2 NEMA17 closed-loop steppers (HEAD_PAN=id1, RIGHT_SHOULDER=id2):
  the ONLY joints with a real, ALM-pin-backed fault signal --
  error_code==1 means lost_sync/stall confirmed (stepper_node.py's own
  _LOST_SYNC_ERROR_CODE convention). load_percent/temperature_c/
  voltage_v are always 0.0 here (not measurable, per stepper_node.py).
- 3 PCA9685 PWM RC servos (HEAD_TILT=id1, RIGHT_ELBOW=id2,
  RIGHT_WRIST=id3): NO feedback sensor at all (see
  pca9685_servo_driver.py's own docstring) -- velocity_rads/
  load_percent/temperature_c/voltage_v are float('nan'), error_code is
  always 0 and therefore never a fault source for this family.
  torque_enabled is their one real, driver-confirmed state field.

Only the stepper lost_sync signal and per-topic staleness are emitted as
triggers here -- torque_enabled toggling is surfaced as a metrics field
for the dashboard, not auto-forwarded as a fault, because torque is
routinely and deliberately disabled/enabled by gesture and safety logic
elsewhere in this repo; treating every disable as a hardware fault would
manufacture noise fault_manager was never meant to carry.
"""

from __future__ import annotations

from dataclasses import dataclass

from .threshold_config import ThresholdConfig
from .trigger import Severity, TelemetryTrigger

_LOST_SYNC_ERROR_CODE = 1

STEPPER_JOINT_NAMES = {1: "head_pan", 2: "right_shoulder"}
SERVO_JOINT_NAMES = {1: "head_tilt", 2: "right_elbow", 3: "right_wrist"}


@dataclass(frozen=True)
class JointReading:
    """Mirrors bonbon_msgs/ServoState's fields exactly -- the ROS node
    layer maps a real ServoState message onto this before calling into
    this pure-Python module."""

    servo_id: int
    position_rad: float
    velocity_rads: float
    load_percent: float
    temperature_c: float
    voltage_v: float
    error_code: int
    torque_enabled: bool


@dataclass(frozen=True)
class JointMetrics:
    joint_name: str
    servo_id: int
    is_stepper: bool
    position_rad: float
    torque_enabled: bool
    lost_sync: bool
    velocity_rads: float
    load_percent: float
    temperature_c: float
    voltage_v: float


@dataclass(frozen=True)
class JointGroupMetrics:
    joints: tuple[JointMetrics, ...]
    is_stepper: bool
    age_sec: float
    stale: bool


def _joint_name(servo_id: int, is_stepper: bool) -> str:
    table = STEPPER_JOINT_NAMES if is_stepper else SERVO_JOINT_NAMES
    return table.get(servo_id, f"{'stepper' if is_stepper else 'servo'}_{servo_id}")


def compute_joint_metrics(reading: JointReading, is_stepper: bool) -> JointMetrics:
    return JointMetrics(
        joint_name=_joint_name(reading.servo_id, is_stepper),
        servo_id=reading.servo_id,
        is_stepper=is_stepper,
        position_rad=reading.position_rad,
        torque_enabled=reading.torque_enabled,
        lost_sync=is_stepper and reading.error_code == _LOST_SYNC_ERROR_CODE,
        velocity_rads=reading.velocity_rads,
        load_percent=reading.load_percent,
        temperature_c=reading.temperature_c,
        voltage_v=reading.voltage_v,
    )


def compute_joint_group_metrics(
    readings: list[JointReading],
    is_stepper: bool,
    age_sec: float,
    thresholds: ThresholdConfig,
) -> JointGroupMetrics:
    joints = tuple(compute_joint_metrics(r, is_stepper) for r in readings)
    return JointGroupMetrics(
        joints=joints,
        is_stepper=is_stepper,
        age_sec=age_sec,
        stale=age_sec > thresholds.liveness.stale_after_sec,
    )


def joint_group_triggers(group: JointGroupMetrics, topic_name: str) -> list[TelemetryTrigger]:
    # Matches bonbon_hal.nodes.{stepper_node,servo_node}.HalNodeBase
    # .DEVICE_NAME exactly -- bonbon_fault_manager.core.component_rules
    # .DEVICE_INFO keys "stepper" and "servo" as two distinct hardware
    # categories (different subsystem lookup), so this must not collapse
    # them to one device string.
    device = "stepper" if group.is_stepper else "servo"
    triggers: list[TelemetryTrigger] = []
    for joint in group.joints:
        if joint.lost_sync:
            triggers.append(
                TelemetryTrigger(
                    device=device,
                    severity=Severity.ERROR,
                    code="STEPPER_LOST_SYNC",
                    message=f"{joint.joint_name} (id={joint.servo_id}): lost_sync/stall confirmed",
                )
            )
    if group.stale:
        triggers.append(
            TelemetryTrigger(
                device=device,
                severity=Severity.WARN,
                code="JOINT_STATE_STALE",
                message=f"No {topic_name} update in {group.age_sec:.1f}s",
            )
        )
    return triggers
