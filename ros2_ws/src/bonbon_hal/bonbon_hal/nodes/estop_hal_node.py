"""
HAL e-stop node — GPIO / Mock.

This node wraps the HAL GpioEstopDriver and integrates with the safety
supervisor.  It replaces (or augments) bonbon_safety's estop_node when
the full HAL is deployed — both can coexist because they use the same
GPIO pin mapping.

Publishes:
  /bonbon/estop/state                (std_msgs/Bool, RELIABLE/TRANSIENT_LOCAL)
  /bonbon/safety/estop_node/health   (bonbon_msgs/ModuleHealth)

Subscribes:
  /bonbon/safety/state               (bonbon_msgs/SafetyState)
  — asserts relay when SAFE_STOP received
"""

from __future__ import annotations

import rclpy
from bonbon_msgs.msg import SafetyState
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool

from bonbon_hal.base.driver_base import DriverBase
from bonbon_hal.drivers.estop import GpioEstopDriver, MockEstopDriver

from .hal_node_base import HalNodeBase

RELIABLE_TL = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)


class EstopHalNode(HalNodeBase):
    NODE_NAME = "estop_hal_node"
    DEVICE_NAME = "estop"
    HEALTH_TOPIC = "/bonbon/safety/estop_node/health"
    DEFAULT_RATE_HZ = 50.0

    def __init__(self) -> None:
        super().__init__()
        self.declare_parameter("input_pin", 17)
        self.declare_parameter("relay_pin", 18)
        self.declare_parameter("poll_hz", 50.0)
        self._pub_estop = None
        self._relay_asserted = False

    def _create_driver(self) -> DriverBase:
        if self.get_parameter("driver_mode").value == "real":
            return GpioEstopDriver(
                input_pin=self.get_parameter("input_pin").value,
                relay_pin=self.get_parameter("relay_pin").value,
                poll_hz=self.get_parameter("poll_hz").value,
            )
        return MockEstopDriver()

    def _create_publishers(self) -> None:
        self._pub_estop = self.create_lifecycle_publisher(Bool, "/bonbon/estop/state", RELIABLE_TL)

    def _create_subscribers(self) -> None:
        self.create_subscription(
            SafetyState, "/bonbon/safety/state", self._cb_safety_state, RELIABLE_TL
        )
        # Register press callback for instant relay assertion
        if self._driver:
            self._driver.register_press_callback(self._on_estop_pressed)

    def _cb_safety_state(self, msg: SafetyState) -> None:
        if msg.state == SafetyState.SAFE_STOP and not self._relay_asserted:
            self.get_logger().fatal("Software SAFE_STOP → asserting relay")
            self._driver.assert_relay()
            self._relay_asserted = True
        elif msg.state == SafetyState.INITIALIZING and self._relay_asserted:
            self.get_logger().warning("Reset → de-asserting relay")
            self._driver.deassert_relay()
            self._relay_asserted = False

    def _on_estop_pressed(self, pressed: bool) -> None:
        if pressed:
            self.get_logger().fatal("E-STOP BUTTON PRESSED — asserting relay")
            self._driver.assert_relay()
            self._relay_asserted = True

    def _publish_data(self) -> None:
        state = self._driver.read_state()
        msg = Bool()
        msg.data = state.pressed
        self._pub_estop.publish(msg)
        if state.pressed and not self._relay_asserted:
            self._driver.assert_relay()
            self._relay_asserted = True


def main(args=None) -> None:
    rclpy.init(args=args)
    node = EstopHalNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
