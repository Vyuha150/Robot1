"""
HAL motor node — Cytron SmartDrive MDDS30 dual-channel drive motor
controller (Rhino 24V 60RPM 100W wheel motors, Pi-3 hardware).

This is the HAL layer only: raw wheel-speed I/O, no kinematics. The
diff-drive kinematics that turn an approved /cmd_vel into per-wheel
targets, and the odometry integration that turns wheel readings back into
a robot-frame pose, live in bonbon_base_controller (a separate policy-
layer package, same HAL/policy split used everywhere else in this repo —
e.g. camera_node vs vision_node, microphone_node vs speech_node).

Publishes:
  /bonbon/motor/wheel_state          (std_msgs/Float32MultiArray)
    layout: [left_mps, right_mps, left_distance_m, right_distance_m]
  /bonbon/motor/motor_node/health    (bonbon_msgs/ModuleHealth)

Subscribes:
  /bonbon/motor/wheel_command        (std_msgs/Float32MultiArray)
    layout: [left_mps, right_mps]

No new bonbon_msgs .msg type was introduced for this internal, single-Pi
(Pi-3-only) contract -- see docs/PERCEPTION_AI_CURRENT_AUDIT.md for why
this repo prefers std_msgs types for topics that don't need the real
colcon build this dev environment cannot run to verify.
"""

from __future__ import annotations

import rclpy
from std_msgs.msg import Float32MultiArray

from bonbon_hal.base.driver_base import DriverBase
from bonbon_hal.drivers.motor import CytronMDDS30Driver, MockMotorDriver, WheelCommand

from .hal_node_base import BEST_EFFORT_D5, RELIABLE_D10, HalNodeBase


class MotorNode(HalNodeBase):
    NODE_NAME = "motor_node"
    DEVICE_NAME = "motor"
    HEALTH_TOPIC = "/bonbon/motor/motor_node/health"
    DEFAULT_RATE_HZ = 20.0

    def __init__(self) -> None:
        super().__init__()
        self.declare_parameter("port", "/dev/ttyUSB2")
        self.declare_parameter("baudrate", 115200)
        self.declare_parameter("max_speed_mps", 1.0)
        self._pub_wheel_state = None

    def _create_driver(self) -> DriverBase:
        max_speed = float(self.get_parameter("max_speed_mps").value)
        if self.get_parameter("driver_mode").value == "real":
            return CytronMDDS30Driver(
                port=self.get_parameter("port").value,
                baudrate=self.get_parameter("baudrate").value,
                max_speed_mps=max_speed,
            )
        return MockMotorDriver(max_speed_mps=max_speed)

    def _create_publishers(self) -> None:
        self._pub_wheel_state = self.create_lifecycle_publisher(
            Float32MultiArray, "/bonbon/motor/wheel_state", BEST_EFFORT_D5
        )

    def _create_subscribers(self) -> None:
        self.create_subscription(
            Float32MultiArray, "/bonbon/motor/wheel_command", self._cb_wheel_command, RELIABLE_D10
        )

    def _cb_wheel_command(self, msg: Float32MultiArray) -> None:
        if not self._driver or not self._driver.is_connected:
            return
        if len(msg.data) < 2:
            self.get_logger().warning(
                "wheel_command with %d elements (need 2) — ignored, not zero-padded silently",
                len(msg.data),
            )
            return
        try:
            self._driver.set_wheel_speeds(WheelCommand(left_mps=msg.data[0], right_mps=msg.data[1]))
        except Exception as exc:
            self.get_logger().warning(f"Wheel command failed: {exc}")

    def _publish_data(self) -> None:
        reading = self._driver.read_wheels()
        msg = Float32MultiArray()
        msg.data = [
            reading.left_mps,
            reading.right_mps,
            reading.left_distance_m,
            reading.right_distance_m,
        ]
        self._pub_wheel_state.publish(msg)

    def on_deactivate(self, state):
        # Motor-specific safety addition on top of HalNodeBase's normal
        # deactivate: always attempt an emergency stop before going
        # inactive, so a lifecycle transition can never leave the wheels
        # spinning at their last commanded speed.
        if self._driver is not None:
            try:
                self._driver.emergency_stop()
            except Exception as exc:  # noqa: BLE001 — best-effort, never block deactivate
                self.get_logger().error(f"emergency_stop during deactivate failed: {exc}")
        return super().on_deactivate(state)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MotorNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
