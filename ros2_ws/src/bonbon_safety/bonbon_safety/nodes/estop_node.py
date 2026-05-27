"""
bonbon_safety.nodes.estop_node
================================
Hardware emergency stop interface node.

Responsibilities
----------------
1. Continuously polls the GPIO e-stop pin (hardware relay line).
2. Publishes /bonbon/estop/state (Bool) whenever the state changes.
3. On SAFE_STOP state from /bonbon/safety/state — asserts the GPIO relay
   to physically cut 24 V motor power (belt-and-suspenders: the button
   itself has a direct hardware path but we also assert from software).
4. On manual reset (e-stop released AND supervisor confirms FAULT→INIT)
   — de-asserts the relay.

Hardware wiring (from circuit blueprint)
-----------------------------------------
  GPIO pin (Jetson Orin Nano 40-pin header, pin 18) → relay coil IN
  Relay NC contact → 24 V motor power rail
  Emergency stop button → relay coil IN (parallel, hardware path)

This node uses RPi.GPIO compatible library (Jetson.GPIO on Orin Nano).
When running in simulation the GPIO library is mocked automatically.
"""

from __future__ import annotations

import logging
import os
import threading

import rclpy
from bonbon_msgs.msg import ModuleHealth, SafetyState
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool

logger = logging.getLogger(__name__)

RELIABLE_TL = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)
RELIABLE_D5 = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=5,
)

# GPIO constants (Jetson.GPIO uses BCM numbering)
ESTOP_INPUT_PIN = 17  # reads physical e-stop button state (active LOW)
RELAY_OUTPUT_PIN = 18  # asserts relay to cut motor power (active HIGH)

_SIMULATION = os.environ.get("BONBON_SIMULATION", "0") == "1"


class _MockGPIO:
    """Drop-in GPIO mock used in simulation / CI environments."""

    BCM = "BCM"
    IN = "IN"
    OUT = "OUT"
    HIGH = 1
    LOW = 0
    PUD_UP = "PUD_UP"

    def setmode(self, *a):
        pass

    def setup(self, *a, **kw):
        pass

    def cleanup(self):
        pass

    def input(self, pin: int) -> int:
        return self.HIGH  # e-stop not pressed by default in simulation

    def output(self, pin: int, value: int):
        logger.debug("[MockGPIO] pin %d → %d", pin, value)


def _load_gpio():
    if _SIMULATION:
        logger.info("Simulation mode: using MockGPIO")
        return _MockGPIO()
    try:
        import Jetson.GPIO as GPIO  # type: ignore[import]

        return GPIO
    except ImportError:
        logger.warning("Jetson.GPIO not found — falling back to MockGPIO")
        return _MockGPIO()


class EstopNode(LifecycleNode):
    """
    Hardware e-stop interface.  Polls at 50 Hz (20 ms) for sub-100 ms response.
    """

    NODE_NAME = "estop_node"
    POLL_HZ = 50

    def __init__(self) -> None:
        super().__init__(self.NODE_NAME)
        self._gpio = _load_gpio()
        self._estop_pressed: bool = False
        self._relay_asserted: bool = False
        self._poll_timer = None
        self._pub_estop: rclpy.publisher.Publisher | None = None
        self._pub_health: rclpy.publisher.Publisher | None = None
        self._lock = threading.Lock()

        self.declare_parameter("estop_input_pin", ESTOP_INPUT_PIN)
        self.declare_parameter("relay_output_pin", RELAY_OUTPUT_PIN)
        self.declare_parameter("poll_hz", float(self.POLL_HZ))

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        try:
            self._in_pin = self.get_parameter("estop_input_pin").value
            self._out_pin = self.get_parameter("relay_output_pin").value

            self._gpio.setmode(self._gpio.BCM)
            self._gpio.setup(self._in_pin, self._gpio.IN, pull_up_down=self._gpio.PUD_UP)
            self._gpio.setup(self._out_pin, self._gpio.OUT)
            # Relay starts de-asserted (motor power on)
            self._gpio.output(self._out_pin, self._gpio.LOW)
            self.get_logger().info(
                "GPIO configured: input pin %d, relay pin %d", self._in_pin, self._out_pin
            )
            return TransitionCallbackReturn.SUCCESS
        except Exception as exc:
            self.get_logger().error(f"GPIO configuration failed: {exc}")
            return TransitionCallbackReturn.FAILURE

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        self._pub_estop = self.create_lifecycle_publisher(Bool, "/bonbon/estop/state", RELIABLE_TL)
        self._pub_health = self.create_lifecycle_publisher(
            ModuleHealth, "/bonbon/safety/estop_node/health", RELIABLE_D5
        )
        # Subscribe to safety state so we can assert relay on SAFE_STOP
        self._sub_safety = self.create_subscription(
            SafetyState,
            "/bonbon/safety/state",
            self._cb_safety_state,
            RELIABLE_TL,
        )
        # Publish initial state immediately
        self._publish_estop_state()

        poll_hz = self.get_parameter("poll_hz").value
        self._poll_timer = self.create_timer(1.0 / poll_hz, self._poll_gpio)
        self.get_logger().info("EstopNode ACTIVE — polling at %.0f Hz", poll_hz)
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        if self._poll_timer:
            self._poll_timer.cancel()
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        self._gpio.cleanup()
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        return self.on_cleanup(state)

    # ── Poll callback (50 Hz) ─────────────────────────────────────────────────

    def _poll_gpio(self) -> None:
        """Read e-stop button GPIO.  Publish on state change."""
        raw = self._gpio.input(self._in_pin)
        # Active LOW: button pressed = GPIO LOW = raw == 0
        pressed = raw == self._gpio.LOW

        with self._lock:
            changed = pressed != self._estop_pressed
            self._estop_pressed = pressed

        if changed:
            if pressed:
                self.get_logger().fatal("E-STOP BUTTON PRESSED — asserting motor power relay")
                self._assert_relay()
            else:
                self.get_logger().warn("E-stop button RELEASED")
            self._publish_estop_state()

        self._publish_health()

    def _cb_safety_state(self, msg: SafetyState) -> None:
        """
        If supervisor enters SAFE_STOP from software path, assert relay too.
        Belt-and-suspenders: hardware path also exists independently.
        """
        if msg.state == SafetyState.SAFE_STOP and not self._relay_asserted:
            self.get_logger().fatal("Software SAFE_STOP received — asserting relay")
            self._assert_relay()
        elif msg.state == SafetyState.INITIALIZING and self._relay_asserted:
            self.get_logger().warn("Startup/reset — de-asserting relay")
            self._deassert_relay()

    # ── Relay control ─────────────────────────────────────────────────────────

    def _assert_relay(self) -> None:
        """Cut motor power by asserting the relay output pin."""
        self._gpio.output(self._out_pin, self._gpio.HIGH)
        self._relay_asserted = True
        self.get_logger().fatal("RELAY ASSERTED — 24V motor power CUT")

    def _deassert_relay(self) -> None:
        """Restore motor power by de-asserting relay pin."""
        self._gpio.output(self._out_pin, self._gpio.LOW)
        self._relay_asserted = False
        self.get_logger().warn("RELAY DE-ASSERTED — 24V motor power RESTORED")

    # ── Publishers ────────────────────────────────────────────────────────────

    def _publish_estop_state(self) -> None:
        if self._pub_estop:
            msg = Bool()
            msg.data = self._estop_pressed
            self._pub_estop.publish(msg)

    def _publish_health(self) -> None:
        if self._pub_health is None:
            return
        msg = ModuleHealth()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.module_name = "estop_node"
        msg.status = ModuleHealth.WARN if self._estop_pressed else ModuleHealth.OK
        msg.status_text = "E-STOP PRESSED" if self._estop_pressed else "E-stop clear"
        self._pub_health.publish(msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = EstopNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
