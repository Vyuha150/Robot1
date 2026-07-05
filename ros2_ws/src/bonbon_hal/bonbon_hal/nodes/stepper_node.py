"""
HAL stepper node — NEMA17 closed-loop steppers (HEAD pan L/R, RIGHT ARM
shoulder rotation). See docs/HARDWARE_SOFTWARE_GAP_REPORT.md item 2 and
bonbon_hal/drivers/stepper/nema17_closed_loop_driver.py.

This is a NEW node (steppers had no HAL representation at all before this
workstream) -- reuses bonbon_msgs/ServoState and ServoStateArray (fields
are already generic enough: servo_id/position_rad/velocity_rads/
load_percent/temperature_c/voltage_v/error_code/torque_enabled) rather
than adding a new message type, consistent with this repo's established
avoid-new-.msg-types-when-avoidable policy. `error_code` doubles as the
stall/lost-sync fault flag for steppers (1 = lost_sync, 0 = healthy) --
documented here since ServoState's comment says "hardware error byte,"
which stall/lost-sync genuinely is for this actuator class.

Publishes:
  /bonbon/stepper/state              (bonbon_msgs/ServoStateArray)
  /bonbon/actuation/stepper_node/health

Subscribes:
  /bonbon/stepper/command            (bonbon_msgs/ServoStateArray — target fields)

A confirmed stall (lost_sync) is reported via error_code=1 on
/bonbon/stepper/state and logged at ERROR level; clear_stall() exists at
the driver level (StepperDriver.clear_stall()) but has no operator-facing
service yet -- that belongs with the fault-manager/dashboard integration
work, not this HAL node, and is intentionally not claimed here.
"""

from __future__ import annotations

import rclpy
from bonbon_msgs.msg import ServoState, ServoStateArray

from bonbon_hal.base.driver_base import DriverBase
from bonbon_hal.drivers.stepper import MockStepperDriver, NEMA17ClosedLoopDriver, StepperCommand

from .hal_node_base import BEST_EFFORT_D5, RELIABLE_D10, HalNodeBase

# Corrected joint topology (see bonbon_actuation/core/gesture_library.py):
#   1 = HEAD_PAN (left/right)
#   2 = RIGHT_SHOULDER
_DEFAULT_STEPPER_IDS = [1, 2]

_LOST_SYNC_ERROR_CODE = 1


class StepperNode(HalNodeBase):
    NODE_NAME = "stepper_node"
    DEVICE_NAME = "stepper"
    HEALTH_TOPIC = "/bonbon/actuation/stepper_node/health"
    DEFAULT_RATE_HZ = 20.0

    def __init__(self) -> None:
        super().__init__()
        self.declare_parameter("backend", "mock")  # 'mock' | 'nema17'
        self.declare_parameter("stepper_ids", _DEFAULT_STEPPER_IDS)
        self.declare_parameter("steps_per_rev", 200)
        self.declare_parameter("microstepping", 8)
        self.declare_parameter("max_step_rate_hz", 1500.0)
        # Per-stepper GPIO pins, flattened for ROS2 param arrays (index i
        # corresponds to stepper_ids[i]) -- MUST be verified against the
        # actual wiring during Pi-3 bring-up.
        self.declare_parameter("step_pins", [20, 22])
        self.declare_parameter("dir_pins", [21, 23])
        self.declare_parameter("enable_pins", [24, 25])
        self.declare_parameter("alarm_pins", [26, 27])
        self._pub_state = None

    def _create_driver(self) -> DriverBase:
        ids = list(self.get_parameter("stepper_ids").value)
        backend = self.get_parameter("backend").value
        if backend == "mock" and self.get_parameter("driver_mode").value == "real":
            backend = "nema17"

        if backend == "nema17":
            step_pins = list(self.get_parameter("step_pins").value)
            dir_pins = list(self.get_parameter("dir_pins").value)
            enable_pins = list(self.get_parameter("enable_pins").value)
            alarm_pins = list(self.get_parameter("alarm_pins").value)
            pin_map = {
                sid: {
                    "step": step_pins[i],
                    "dir": dir_pins[i],
                    "enable": enable_pins[i],
                    "alarm": alarm_pins[i],
                }
                for i, sid in enumerate(ids)
            }
            self.get_logger().info("Stepper backend: NEMA17 closed-loop (%d channels)", len(ids))
            return NEMA17ClosedLoopDriver(
                stepper_ids=ids,
                pin_map=pin_map,
                steps_per_rev=self.get_parameter("steps_per_rev").value,
                microstepping=self.get_parameter("microstepping").value,
                max_step_rate_hz=self.get_parameter("max_step_rate_hz").value,
            )
        self.get_logger().info("Stepper backend: mock (simulation)")
        return MockStepperDriver(stepper_ids=ids)

    def _create_publishers(self) -> None:
        self._pub_state = self.create_lifecycle_publisher(
            ServoStateArray, "/bonbon/stepper/state", BEST_EFFORT_D5
        )

    def _create_subscribers(self) -> None:
        self.create_subscription(
            ServoStateArray, "/bonbon/stepper/command", self._cb_command, RELIABLE_D10
        )

    def _cb_command(self, msg: ServoStateArray) -> None:
        if not self._driver or not self._driver.is_connected:
            return
        try:
            cmds = [
                StepperCommand(
                    stepper_id=s.servo_id,
                    target_position_rad=s.position_rad,
                    velocity_limit_rads=s.velocity_rads if s.velocity_rads > 0 else 1.0,
                )
                for s in msg.servos
            ]
            self._driver.write_commands(cmds)
        except Exception as exc:
            self.get_logger().warning(f"Stepper command failed: {exc}")

    def _publish_data(self) -> None:
        readings = self._driver.read_all()
        now = self.get_clock().now().to_msg()
        arr = ServoStateArray()
        arr.header.stamp = now
        for r in readings:
            s = ServoState()
            s.servo_id = r.stepper_id
            s.position_rad = r.position_rad
            s.velocity_rads = r.velocity_rads
            s.load_percent = 0.0  # not measurable -- see NEMA17ClosedLoopDriver docstring
            s.temperature_c = 0.0  # not measurable
            s.voltage_v = 0.0  # not measurable
            s.error_code = _LOST_SYNC_ERROR_CODE if r.lost_sync else 0
            s.torque_enabled = r.enabled
            arr.servos.append(s)
            if r.lost_sync:
                self.get_logger().error(
                    "Stepper %d: LOST SYNC (stall confirmed) — clear_stall() required after "
                    "the mechanical jam/misalignment is resolved",
                    r.stepper_id,
                )
        self._pub_state.publish(arr)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = StepperNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
