"""bonbon_hardware_telemetry.nodes.hardware_telemetry_node -- the one
ROS2 node this package needs. Subscribes to the REAL, already-published
bonbon_hal state topics (wheel/stepper/servo/battery -- reused
unchanged, nothing here re-implements a driver), turns each reading
into a Tier-1 metrics snapshot via core/*_metrics.py's pure functions,
and:

  1. publishes a per-Pi JSON status snapshot on
     /bonbon/hardware_telemetry/status for the dashboard, on a timer
     (same lazy-rclpy-import, timer-tick, std_msgs/String-JSON pattern
     already established by bonbon_ai_model_registry.model_health_monitor
     and bonbon_edge_ai_runtime.nodes.edge_ai_runtime_node -- see either
     file's own docstring for why: this dev sandbox has no rclpy, so
     every node in this repo defers the import into main());
  2. publishes any triggered core/trigger.py TelemetryTrigger as a real
     bonbon_msgs/HalFault on /bonbon/hal/fault -- the ALREADY-EXISTING
     ingestion topic bonbon_fault_manager.nodes.fault_manager_node
     subscribes to (see that package's own docstring), so this node
     does not build a second, competing alerting mechanism.

pi_role gates which HAL topics get subscribed: wheel/stepper/servo/
battery state only exists on navigation_safety_pi (the Pi that actually
runs bonbon_hal, bonbon_base_controller, bonbon_stepper_controller,
bonbon_servo_controller -- see config/edge_ai/three_pi_allocation.yaml's
pi_roles.navigation_safety_pi.packages). Per-Pi CPU/memory/disk
sampling via bonbon_safety.core.resource_monitor.ResourceMonitor
(reused unchanged) runs on every Pi role, since every Pi has its own
local resource pressure worth surfacing.

Per-Pi CPU/memory/disk pressure is deliberately NOT forwarded to
/bonbon/hal/fault -- see core/pi_metrics.py's own docstring for why
(that signal already has a dedicated, already-acting-on-it pipeline via
resource_guard/LoadSheddingController/DegradedModeManager; duplicating
it into fault_manager's device-fault taxonomy would give the same
reading two independently-diverging meanings). The monitor-degraded and
snapshot-staleness triggers from pi_metrics ARE forwarded, since nothing
else already reports them.

No trigger is fired for a component before this node has received at
least one real message for it -- absence of data at startup is not the
same claim as "this topic went stale," and this module never conflates
the two.
"""

from __future__ import annotations


def main(
    args: list[str] | None = None,
) -> None:  # pragma: no cover -- exercised only with rclpy present
    try:
        import json
        import time

        import rclpy
        from bonbon_msgs.msg import HalFault, ServoState, ServoStateArray
        from rclpy.node import Node
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
        from sensor_msgs.msg import BatteryState
        from std_msgs.msg import Float32MultiArray, String
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "hardware_telemetry_node requires rclpy + std_msgs + sensor_msgs + bonbon_msgs -- run "
            "inside a ROS2 environment, not this dev sandbox"
        ) from exc

    from bonbon_safety.core.resource_monitor import ResourceMonitor

    from bonbon_hardware_telemetry.core.battery_metrics import (
        battery_triggers,
        compute_battery_metrics,
    )
    from bonbon_hardware_telemetry.core.joint_metrics import (
        JointReading,
        compute_joint_group_metrics,
        joint_group_triggers,
    )
    from bonbon_hardware_telemetry.core.pi_metrics import (
        compute_pi_resource_metrics,
        pi_resource_triggers,
    )
    from bonbon_hardware_telemetry.core.threshold_config import ThresholdConfig
    from bonbon_hardware_telemetry.core.trigger import TelemetryTrigger
    from bonbon_hardware_telemetry.core.wheel_metrics import compute_wheel_metrics, wheel_triggers

    _QOS_BEST_EFFORT_D5 = QoSProfile(
        reliability=ReliabilityPolicy.BEST_EFFORT,
        durability=DurabilityPolicy.VOLATILE,
        history=HistoryPolicy.KEEP_LAST,
        depth=5,
    )
    _QOS_RELIABLE_D10 = QoSProfile(
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.VOLATILE,
        history=HistoryPolicy.KEEP_LAST,
        depth=10,
    )

    _NAV_SAFETY_PI = "navigation_safety_pi"

    def _servo_state_to_reading(s: "ServoState") -> JointReading:
        return JointReading(
            servo_id=s.servo_id,
            position_rad=s.position_rad,
            velocity_rads=s.velocity_rads,
            load_percent=s.load_percent,
            temperature_c=s.temperature_c,
            voltage_v=s.voltage_v,
            error_code=s.error_code,
            torque_enabled=s.torque_enabled,
        )

    class HardwareTelemetryNode(Node):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__("hardware_telemetry_node")
            self.declare_parameter("pi_role", _NAV_SAFETY_PI)
            self.declare_parameter("publish_interval_sec", 2.0)
            self.declare_parameter("thresholds_path", "")

            self._pi_role = str(self.get_parameter("pi_role").value)
            thresholds_path = str(self.get_parameter("thresholds_path").value) or None
            self._thresholds = ThresholdConfig.load(thresholds_path)
            self._resource_monitor = ResourceMonitor()

            self._last_wheel: Float32MultiArray | None = None
            self._last_wheel_at = 0.0
            self._last_stepper: ServoStateArray | None = None
            self._last_stepper_at = 0.0
            self._last_neck: ServoStateArray | None = None
            self._last_neck_at = 0.0
            self._last_arm: ServoStateArray | None = None
            self._last_arm_at = 0.0
            self._last_battery: BatteryState | None = None
            self._last_battery_at = 0.0

            self._pub_fault = self.create_publisher(
                HalFault, "/bonbon/hal/fault", _QOS_RELIABLE_D10
            )
            self._pub_status = self.create_publisher(
                String, "/bonbon/hardware_telemetry/status", _QOS_RELIABLE_D10
            )

            if self._pi_role == _NAV_SAFETY_PI:
                self.create_subscription(
                    Float32MultiArray,
                    "/bonbon/motor/wheel_state",
                    self._on_wheel_state,
                    _QOS_BEST_EFFORT_D5,
                )
                self.create_subscription(
                    ServoStateArray,
                    "/bonbon/stepper/state",
                    self._on_stepper_state,
                    _QOS_BEST_EFFORT_D5,
                )
                self.create_subscription(
                    ServoStateArray,
                    "/bonbon/servo/neck/state",
                    self._on_neck_state,
                    _QOS_BEST_EFFORT_D5,
                )
                self.create_subscription(
                    ServoStateArray,
                    "/bonbon/servo/arm/state",
                    self._on_arm_state,
                    _QOS_BEST_EFFORT_D5,
                )
                self.create_subscription(
                    BatteryState, "/bonbon/battery/state", self._on_battery_state, _QOS_RELIABLE_D10
                )

            interval = float(self.get_parameter("publish_interval_sec").value) or 2.0
            self._timer = self.create_timer(interval, self._on_tick)

        # ── Subscriptions ────────────────────────────────────────────────

        def _on_wheel_state(self, msg: "Float32MultiArray") -> None:
            self._last_wheel = msg
            self._last_wheel_at = time.monotonic()

        def _on_stepper_state(self, msg: "ServoStateArray") -> None:
            self._last_stepper = msg
            self._last_stepper_at = time.monotonic()

        def _on_neck_state(self, msg: "ServoStateArray") -> None:
            self._last_neck = msg
            self._last_neck_at = time.monotonic()

        def _on_arm_state(self, msg: "ServoStateArray") -> None:
            self._last_arm = msg
            self._last_arm_at = time.monotonic()

        def _on_battery_state(self, msg: "BatteryState") -> None:
            self._last_battery = msg
            self._last_battery_at = time.monotonic()

        # ── Trigger -> HalFault ──────────────────────────────────────────

        def _publish_trigger(self, trigger: TelemetryTrigger) -> None:
            msg = HalFault()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.device = trigger.device
            msg.driver_mode = "real"
            msg.severity = int(trigger.severity)
            msg.error_code = trigger.code
            msg.message = trigger.message
            msg.is_recovered = trigger.is_recovered
            msg.reconnect_attempt = 0
            self._pub_fault.publish(msg)

        # ── Timer tick ───────────────────────────────────────────────────

        def _on_tick(self) -> None:
            now = time.monotonic()
            snapshot: dict = {"pi_role": self._pi_role}

            if self._pi_role == _NAV_SAFETY_PI:
                snapshot["wheels"] = self._tick_wheels(now)
                snapshot["steppers"] = self._tick_joint_group(
                    now,
                    self._last_stepper,
                    self._last_stepper_at,
                    is_stepper=True,
                    topic_name="/bonbon/stepper/state",
                )
                snapshot["servos_neck"] = self._tick_joint_group(
                    now,
                    self._last_neck,
                    self._last_neck_at,
                    is_stepper=False,
                    topic_name="/bonbon/servo/neck/state",
                )
                snapshot["servos_arm"] = self._tick_joint_group(
                    now,
                    self._last_arm,
                    self._last_arm_at,
                    is_stepper=False,
                    topic_name="/bonbon/servo/arm/state",
                )
                snapshot["battery"] = self._tick_battery(now)

            snapshot["pi_resources"] = self._tick_pi_resources()

            msg = String()
            msg.data = json.dumps(snapshot)
            self._pub_status.publish(msg)

        def _tick_wheels(self, now: float) -> dict:
            if self._last_wheel is None:
                return {"received": False}
            d = list(self._last_wheel.data) + [0.0, 0.0, 0.0, 0.0]
            left_mps, right_mps, left_distance_m, right_distance_m = d[:4]
            age_sec = now - self._last_wheel_at
            m = compute_wheel_metrics(
                left_mps, right_mps, left_distance_m, right_distance_m, age_sec, self._thresholds
            )
            for trig in wheel_triggers(m):
                self._publish_trigger(trig)
            return {
                "received": True,
                "left_mps": m.left_mps,
                "right_mps": m.right_mps,
                "left_distance_m": m.left_distance_m,
                "right_distance_m": m.right_distance_m,
                "age_sec": m.age_sec,
                "stale": m.stale,
            }

        def _tick_joint_group(
            self,
            now: float,
            last_msg: "ServoStateArray | None",
            last_at: float,
            *,
            is_stepper: bool,
            topic_name: str,
        ) -> dict:
            if last_msg is None:
                return {"received": False}
            readings = [_servo_state_to_reading(s) for s in last_msg.servos]
            age_sec = now - last_at
            group = compute_joint_group_metrics(readings, is_stepper, age_sec, self._thresholds)
            for trig in joint_group_triggers(group, topic_name):
                self._publish_trigger(trig)
            return {
                "received": True,
                "age_sec": group.age_sec,
                "stale": group.stale,
                "joints": [
                    {
                        "joint_name": j.joint_name,
                        "servo_id": j.servo_id,
                        "position_rad": j.position_rad,
                        "torque_enabled": j.torque_enabled,
                        "lost_sync": j.lost_sync,
                    }
                    for j in group.joints
                ],
            }

        def _tick_battery(self, now: float) -> dict:
            if self._last_battery is None:
                return {"received": False}
            b = self._last_battery
            is_charging = b.power_supply_status == BatteryState.POWER_SUPPLY_STATUS_CHARGING
            age_sec = now - self._last_battery_at
            m = compute_battery_metrics(
                b.voltage, b.current, b.percentage * 100.0, is_charging, age_sec, self._thresholds
            )
            for trig in battery_triggers(m):
                self._publish_trigger(trig)
            return {
                "received": True,
                "voltage_v": m.voltage_v,
                "current_a": m.current_a,
                "percent": m.percent,
                "is_charging": m.is_charging,
                "age_sec": m.age_sec,
                "stale": m.stale,
                "low_warn": m.low_warn,
                "low_error": m.low_error,
                "undervoltage": m.undervoltage,
                "overcurrent": m.overcurrent,
            }

        def _tick_pi_resources(self) -> dict:
            snap = self._resource_monitor.sample()
            m = compute_pi_resource_metrics(
                self._pi_role,
                snap.cpu_percent,
                snap.memory_percent,
                snap.memory_mb,
                snap.disk_free_percent,
                snap.available,
                age_sec=0.0,
                thresholds=self._thresholds,
            )
            for trig in pi_resource_triggers(m):
                self._publish_trigger(trig)
            return {
                "cpu_percent": m.cpu_percent,
                "memory_percent": m.memory_percent,
                "memory_mb": m.memory_mb,
                "disk_free_percent": m.disk_free_percent,
                "available": m.available,
                "cpu_elevated": m.cpu_elevated,
                "cpu_overloaded": m.cpu_overloaded,
                "memory_pressure": m.memory_pressure,
                "disk_low": m.disk_low,
            }

    rclpy.init(args=args)
    node = HardwareTelemetryNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":  # pragma: no cover
    main()
