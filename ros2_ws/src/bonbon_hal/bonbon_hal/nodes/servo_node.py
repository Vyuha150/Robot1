"""
HAL servo node — Dynamixel.

Publishes:
  /bonbon/servo/neck/state           (bonbon_msgs/ServoState) — servo ID 1
  /bonbon/servo/arm/state            (bonbon_msgs/ServoStateArray)
  /bonbon/actuation/servo_node/health

Subscribes:
  /bonbon/servo/neck/command         (bonbon_msgs/ServoState — target fields)
  /bonbon/servo/arm/command          (bonbon_msgs/ServoStateArray)
"""

from __future__ import annotations

import rclpy
from bonbon_msgs.msg import ServoState, ServoStateArray

from bonbon_hal.base.driver_base import DriverBase
from bonbon_hal.drivers.servo import DynamixelDriver, MockServoDriver, ServoCommand

from .hal_node_base import BEST_EFFORT_D5, RELIABLE_D10, HalNodeBase


class ServoNode(HalNodeBase):
    NODE_NAME = "servo_node"
    DEVICE_NAME = "servo"
    HEALTH_TOPIC = "/bonbon/actuation/servo_node/health"
    DEFAULT_RATE_HZ = 20.0

    def __init__(self) -> None:
        super().__init__()
        self.declare_parameter("port", "/dev/ttyUSB0")
        self.declare_parameter("baudrate", 57600)
        self.declare_parameter("servo_ids", [1, 2, 3, 4])  # 1=neck, 2-4=arm
        self.declare_parameter("neck_servo_id", 1)
        self._pub_neck = None
        self._pub_arm = None

    def _create_driver(self) -> DriverBase:
        ids = list(self.get_parameter("servo_ids").value)
        if self.get_parameter("driver_mode").value == "real":
            return DynamixelDriver(
                servo_ids=ids,
                port=self.get_parameter("port").value,
                baudrate=self.get_parameter("baudrate").value,
            )
        return MockServoDriver(servo_ids=ids)

    def _create_publishers(self) -> None:
        self._pub_neck = self.create_lifecycle_publisher(
            ServoState, "/bonbon/servo/neck/state", BEST_EFFORT_D5
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
                    servo_id=self.get_parameter("neck_servo_id").value,
                    target_position_rad=msg.position_rad,
                    velocity_limit_rads=msg.velocity_rads if msg.velocity_rads > 0 else 1.0,
                )
            )
        except Exception as exc:
            self.get_logger().warning(f"Neck command failed: {exc}")

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
        neck_id = self.get_parameter("neck_servo_id").value
        now = self.get_clock().now().to_msg()

        neck_readings = [r for r in readings if r.servo_id == neck_id]
        arm_readings = [r for r in readings if r.servo_id != neck_id]

        if neck_readings:
            r = neck_readings[0]
            msg = ServoState()
            msg.header.stamp = now
            msg.servo_id = r.servo_id
            msg.position_rad = r.position_rad
            msg.velocity_rads = r.velocity_rads
            msg.load_percent = r.load_percent
            msg.temperature_c = r.temperature_c
            msg.voltage_v = r.voltage_v
            msg.error_code = r.error_code
            msg.torque_enabled = r.torque_enabled
            self._pub_neck.publish(msg)

        arr = ServoStateArray()
        arr.header.stamp = now
        for r in arm_readings:
            s = ServoState()
            s.servo_id = r.servo_id
            s.position_rad = r.position_rad
            s.velocity_rads = r.velocity_rads
            s.load_percent = r.load_percent
            s.temperature_c = r.temperature_c
            s.voltage_v = r.voltage_v
            s.error_code = r.error_code
            s.torque_enabled = r.torque_enabled
            arr.servos.append(s)
        self._pub_arm.publish(arr)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ServoNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
