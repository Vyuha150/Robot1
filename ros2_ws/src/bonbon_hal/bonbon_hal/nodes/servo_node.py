"""
HAL servo node — PCA9685 PWM servos (real hardware per the BOM), with
DynamixelDriver kept as a selectable backend for any future Dynamixel
hardware. See docs/HARDWARE_SOFTWARE_GAP_REPORT.md's servo-topology
supersession note: this robot's servos are standard 25kgcm PWM RC servos
(RIGHT ARM elbow, RIGHT ARM wrist, HEAD tilt), not Dynamixel smart servos.

Publishes:
  /bonbon/servo/neck/state           (bonbon_msgs/ServoStateArray, 1 element — HEAD TILT)
  /bonbon/servo/arm/state            (bonbon_msgs/ServoStateArray — RIGHT ELBOW, RIGHT WRIST)
  /bonbon/actuation/servo_node/health

Subscribes:
  /bonbon/servo/neck/command         (bonbon_msgs/ServoState — target fields)
  /bonbon/servo/arm/command          (bonbon_msgs/ServoStateArray)

NOTE on the "neck"/"arm" topic split: kept as-is even though the single
servo is physically HEAD TILT, not a neck joint -- these topic names are
also depended on by bonbon_safety's safety_gate_node and
safety_supervisor_node (CLASS-A safety-critical), so renaming them is a
separate, wider-blast-radius change and out of scope here. What WAS a bug
and IS fixed here: this topic is published as a bare ServoState while
safety_supervisor_node.py subscribes to it as ServoStateArray -- a type
mismatch that meant the supervisor never actually received head-servo
state. It is now a ServoStateArray with a single element, matching what
the supervisor already expects.
"""

from __future__ import annotations

import rclpy
from bonbon_msgs.msg import ServoState, ServoStateArray

from bonbon_hal.base.driver_base import DriverBase
from bonbon_hal.drivers.servo import (
    DynamixelDriver,
    MockServoDriver,
    PCA9685ServoDriver,
    ServoCalibration,
    ServoCommand,
)

from .hal_node_base import BEST_EFFORT_D5, RELIABLE_D10, HalNodeBase

# Corrected joint topology (see docs/HARDWARE_SOFTWARE_GAP_REPORT.md and
# bonbon_actuation/core/gesture_library.py, which defines these same IDs):
#   1 = HEAD_TILT (up/down)      -- published alone on the "neck" topics
#   2 = RIGHT_ELBOW
#   3 = RIGHT_WRIST               -- 2,3 published together on the "arm" topics
_DEFAULT_SERVO_IDS = [1, 2, 3]
_DEFAULT_PRIMARY_SERVO_ID = 1  # HEAD_TILT


class ServoNode(HalNodeBase):
    NODE_NAME = "servo_node"
    DEVICE_NAME = "servo"
    HEALTH_TOPIC = "/bonbon/actuation/servo_node/health"
    DEFAULT_RATE_HZ = 20.0

    def __init__(self) -> None:
        super().__init__()
        # Backend: 'mock' | 'pca9685' (real hardware, this BOM) | 'dynamixel'
        # (selectable for any future Dynamixel-based hardware -- not what's
        # in this BOM).
        self.declare_parameter("backend", "mock")
        self.declare_parameter("port", "/dev/ttyUSB0")  # dynamixel only
        self.declare_parameter("baudrate", 57600)  # dynamixel only
        self.declare_parameter("i2c_bus", 1)  # pca9685 only
        self.declare_parameter("i2c_address", 0x40)  # pca9685 only
        self.declare_parameter("pwm_freq_hz", 50.0)  # pca9685 only
        self.declare_parameter("servo_ids", _DEFAULT_SERVO_IDS)
        self.declare_parameter("primary_servo_id", _DEFAULT_PRIMARY_SERVO_ID)
        # Per-servo PCA9685 channel/calibration, flattened for ROS2 param
        # arrays (index i corresponds to servo_ids[i]). Defaults assume
        # channel N-1 for servo id N and the common 1000-2000us/180deg
        # range -- MUST be verified against the physical 25kgcm servos
        # during Pi-3 bring-up, not assumed correct.
        self.declare_parameter("pca9685_channels", [0, 1, 2])
        self.declare_parameter("pca9685_min_pulse_us", [1000.0, 1000.0, 1000.0])
        self.declare_parameter("pca9685_max_pulse_us", [2000.0, 2000.0, 2000.0])
        self._pub_neck = None
        self._pub_arm = None

    def _create_driver(self) -> DriverBase:
        ids = list(self.get_parameter("servo_ids").value)
        backend = self.get_parameter("backend").value
        if backend == "mock" and self.get_parameter("driver_mode").value == "real":
            backend = "pca9685"  # legacy default when only driver_mode=real was set

        if backend == "dynamixel":
            self.get_logger().info("Servo backend: Dynamixel (not this robot's BOM hardware)")
            return DynamixelDriver(
                servo_ids=ids,
                port=self.get_parameter("port").value,
                baudrate=self.get_parameter("baudrate").value,
            )
        if backend == "pca9685":
            channels = list(self.get_parameter("pca9685_channels").value)
            min_pulses = list(self.get_parameter("pca9685_min_pulse_us").value)
            max_pulses = list(self.get_parameter("pca9685_max_pulse_us").value)
            calibrations = {
                sid: ServoCalibration(
                    channel=channels[i],
                    min_pulse_us=min_pulses[i],
                    max_pulse_us=max_pulses[i],
                )
                for i, sid in enumerate(ids)
            }
            self.get_logger().info("Servo backend: PCA9685 (%d channels)", len(ids))
            return PCA9685ServoDriver(
                servo_ids=ids,
                calibrations=calibrations,
                i2c_bus=self.get_parameter("i2c_bus").value,
                i2c_address=self.get_parameter("i2c_address").value,
                pwm_freq_hz=self.get_parameter("pwm_freq_hz").value,
            )
        self.get_logger().info("Servo backend: mock (simulation)")
        return MockServoDriver(servo_ids=ids)

    def _create_publishers(self) -> None:
        self._pub_neck = self.create_lifecycle_publisher(
            ServoStateArray, "/bonbon/servo/neck/state", BEST_EFFORT_D5
        )
        self._pub_arm = self.create_lifecycle_publisher(
            ServoStateArray, "/bonbon/servo/arm/state", BEST_EFFORT_D5
        )

    def _create_subscribers(self) -> None:
        self.create_subscription(
            ServoState, "/bonbon/servo/neck/command", self._cb_neck_command, RELIABLE_D10
        )
        self.create_subscription(
            ServoStateArray, "/bonbon/servo/arm/command", self._cb_arm_command, RELIABLE_D10
        )

    def _cb_neck_command(self, msg: ServoState) -> None:
        if not self._driver or not self._driver.is_connected:
            return
        try:
            self._driver.write_command(
                ServoCommand(
                    servo_id=self.get_parameter("primary_servo_id").value,
                    target_position_rad=msg.position_rad,
                    velocity_limit_rads=msg.velocity_rads if msg.velocity_rads > 0 else 1.0,
                )
            )
        except Exception as exc:
            self.get_logger().warning(f"Head-tilt command failed: {exc}")

    def _cb_arm_command(self, msg: ServoStateArray) -> None:
        if not self._driver or not self._driver.is_connected:
            return
        try:
            cmds = [
                ServoCommand(
                    servo_id=s.servo_id,
                    target_position_rad=s.position_rad,
                    velocity_limit_rads=s.velocity_rads if s.velocity_rads > 0 else 1.0,
                )
                for s in msg.servos
            ]
            self._driver.write_commands(cmds)
        except Exception as exc:
            self.get_logger().warning(f"Arm command failed: {exc}")

    def _publish_data(self) -> None:
        readings = self._driver.read_all()
        primary_id = self.get_parameter("primary_servo_id").value
        now = self.get_clock().now().to_msg()

        primary_readings = [r for r in readings if r.servo_id == primary_id]
        arm_readings = [r for r in readings if r.servo_id != primary_id]

        neck_arr = ServoStateArray()
        neck_arr.header.stamp = now
        for r in primary_readings:
            neck_arr.servos.append(self._to_msg(r))
        self._pub_neck.publish(neck_arr)

        arm_arr = ServoStateArray()
        arm_arr.header.stamp = now
        for r in arm_readings:
            arm_arr.servos.append(self._to_msg(r))
        self._pub_arm.publish(arm_arr)

    @staticmethod
    def _to_msg(r) -> ServoState:
        s = ServoState()
        s.servo_id = r.servo_id
        s.position_rad = r.position_rad
        s.velocity_rads = r.velocity_rads
        s.load_percent = r.load_percent
        s.temperature_c = r.temperature_c
        s.voltage_v = r.voltage_v
        s.error_code = r.error_code
        s.torque_enabled = r.torque_enabled
        return s


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ServoNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
