"""
BaseControllerNode — the policy layer between Pi-3's safety-gated
/cmd_vel and bonbon_hal's raw motor_node, and between raw wheel readings
and Nav2's odometry input.

Subscribes:
  /cmd_vel                     (geometry_msgs/Twist) — the FINAL, already
                                safety_gate_node-approved velocity command.
                                This node has NO authority of its own; it
                                only converts an already-approved Twist
                                into wheel speeds. It never originates motion.
  /bonbon/motor/wheel_state     (std_msgs/Float32MultiArray)
                                [left_mps, right_mps, left_distance_m, right_distance_m]

Publishes:
  /bonbon/motor/wheel_command    (std_msgs/Float32MultiArray) [left_mps, right_mps]
  /bonbon/odometry/wheels        (nav_msgs/Odometry)

All kinematics/odometry math lives in bonbon_base_controller.core
(DiffDriveKinematics, OdometryIntegrator) -- fully unit-tested (30 tests).
This file is thin ROS2 glue only, and (like every other rclpy-importing
file touched in this session) cannot be executed or pytest-run in this
dev sandbox -- syntax-checked via py_compile only.
"""

from __future__ import annotations

import math

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.lifecycle import Publisher as LifecyclePublisher
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Float32MultiArray

from bonbon_base_controller.core.diff_drive_kinematics import (
    DiffDriveConfig,
    DiffDriveKinematics,
    Twist2D,
)
from bonbon_base_controller.core.odometry_integrator import OdometryIntegrator

_QOS_RELIABLE = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
_QOS_BEST_EFFORT = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=5,
)


class BaseControllerNode(LifecycleNode):
    def __init__(self, node_name: str = "base_controller_node") -> None:
        super().__init__(node_name)

        self.declare_parameter("wheel_base_m", 0.40)
        self.declare_parameter("max_wheel_speed_mps", 1.0)
        self.declare_parameter("odom_frame_id", "odom")
        self.declare_parameter("base_frame_id", "base_link")

        self._kinematics: DiffDriveKinematics | None = None
        self._odometry: OdometryIntegrator | None = None

        self._sub_cmd_vel = None
        self._sub_wheel_state = None
        self._pub_wheel_command: LifecyclePublisher | None = None
        self._pub_odometry: LifecyclePublisher | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        cfg = DiffDriveConfig(
            wheel_base_m=float(self.get_parameter("wheel_base_m").value),
            max_wheel_speed_mps=float(self.get_parameter("max_wheel_speed_mps").value),
        )
        self._kinematics = DiffDriveKinematics(cfg)
        self._odometry = OdometryIntegrator(cfg)

        self._sub_cmd_vel = self.create_subscription(
            Twist, "/cmd_vel", self._cb_cmd_vel, _QOS_RELIABLE
        )
        self._sub_wheel_state = self.create_subscription(
            Float32MultiArray, "/bonbon/motor/wheel_state", self._cb_wheel_state, _QOS_BEST_EFFORT
        )
        self._pub_wheel_command = self.create_lifecycle_publisher(
            Float32MultiArray, "/bonbon/motor/wheel_command", _QOS_RELIABLE
        )
        self._pub_odometry = self.create_lifecycle_publisher(
            Odometry, "/bonbon/odometry/wheels", _QOS_BEST_EFFORT
        )
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        # Command a stop through the normal wheel_command path -- motor_node
        # itself also emergency-stops on ITS OWN deactivate, this is
        # defense in depth, not a replacement for that.
        if self._pub_wheel_command is not None:
            self._pub_wheel_command.publish(Float32MultiArray(data=[0.0, 0.0]))
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        self._kinematics = None
        self._odometry = None
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        return TransitionCallbackReturn.SUCCESS

    # ── Callbacks ────────────────────────────────────────────────────────────

    def _cb_cmd_vel(self, msg: Twist) -> None:
        if self._kinematics is None or self._pub_wheel_command is None:
            return
        wheels = self._kinematics.twist_to_wheel_speeds(
            Twist2D(linear_x_mps=msg.linear.x, angular_z_rps=msg.angular.z)
        )
        self._pub_wheel_command.publish(Float32MultiArray(data=[wheels.left_mps, wheels.right_mps]))

    def _cb_wheel_state(self, msg: Float32MultiArray) -> None:
        if self._odometry is None or self._pub_odometry is None:
            return
        if len(msg.data) < 4:
            self.get_logger().warning(
                f"wheel_state with {len(msg.data)} elements (need 4) — ignored"
            )
            return
        _left_mps, _right_mps, left_distance_m, right_distance_m = msg.data[:4]
        estimate = self._odometry.integrate(left_distance_m, right_distance_m)

        odom = Odometry()
        odom.header.stamp = self.get_clock().now().to_msg()
        odom.header.frame_id = self.get_parameter("odom_frame_id").value
        odom.child_frame_id = self.get_parameter("base_frame_id").value
        odom.pose.pose.position.x = estimate.pose.x_m
        odom.pose.pose.position.y = estimate.pose.y_m
        odom.pose.pose.orientation.z = math.sin(estimate.pose.theta_rad / 2.0)
        odom.pose.pose.orientation.w = math.cos(estimate.pose.theta_rad / 2.0)
        odom.twist.twist.linear.x = estimate.linear_velocity_mps
        odom.twist.twist.angular.z = estimate.angular_velocity_rps
        self._pub_odometry.publish(odom)


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = BaseControllerNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
