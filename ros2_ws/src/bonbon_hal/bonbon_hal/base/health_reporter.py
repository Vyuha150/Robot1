"""
bonbon_hal.base.health_reporter
=================================
Mixin used by every HAL ROS2 node to build and publish health messages
and forward faults to the Safety Supervisor.

Inheriting node must expose:
  self._driver           : DriverBase instance
  self._pub_health       : Publisher[ModuleHealth]
  self._pub_hal_fault    : Publisher[HalFault]
  self.get_clock()       : rclpy Node clock
  self.get_logger()      : rclpy Node logger
  self._node_name        : str
  self._driver_mode      : str ("real"|"mock")
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bonbon_hal.base.driver_base import DriverStatus

# ModuleHealth constants (mirrors bonbon_msgs/msg/ModuleHealth.msg)
_STATUS_OK = 0
_STATUS_WARN = 1
_STATUS_ERROR = 2
_STATUS_STALE = 3

# HalFault severity (mirrors bonbon_msgs/msg/HalFault.msg)
_SEV_INFO = 0
_SEV_WARN = 1
_SEV_ERROR = 2
_SEV_FATAL = 3

# DriverStatus import at runtime to avoid circular dependency
from bonbon_hal.base.driver_base import DriverStatus


def _driver_status_to_health(status: DriverStatus, consec_errors: int) -> int:
    if status == DriverStatus.CONNECTED:
        return _STATUS_OK
    if status == DriverStatus.DEGRADED:
        return _STATUS_WARN
    if status in (DriverStatus.DISCONNECTED, DriverStatus.CONNECTING):
        return _STATUS_WARN
    if status in (DriverStatus.FAULTED, DriverStatus.SHUTDOWN):
        return _STATUS_ERROR
    return _STATUS_STALE


class HealthReporter:
    """
    Mixin — call self._publish_health() and self._publish_hal_fault() from the node.
    """

    def _build_health_msg(self):
        """Build a ModuleHealth ROS2 message from current driver state."""
        from bonbon_msgs.msg import ModuleHealth  # lazy import keeps base pure

        h = self._driver.health
        msg = ModuleHealth()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.module_name = self._node_name
        msg.status = _driver_status_to_health(h.status, h.consecutive_errors)
        msg.status_text = (
            f"OK — age={h.last_read_age_sec:.2f}s reconnects={h.reconnect_count}"
            if h.is_healthy
            else f"{h.status.name} — {h.last_error or 'no details'}"
        )
        return msg

    def _publish_health(self) -> None:
        if not hasattr(self, "_pub_health") or self._pub_health is None:
            return
        try:
            self._pub_health.publish(self._build_health_msg())
        except Exception as exc:
            self.get_logger().warning(f"Failed to publish health: {exc}")

    def _publish_hal_fault(
        self,
        error_code: str,
        message: str,
        severity: int = _SEV_ERROR,
        is_recovered: bool = False,
        reconnect_attempt: int = 0,
    ) -> None:
        """Publish a HalFault to /bonbon/hal/fault so the Safety Supervisor can react."""
        if not hasattr(self, "_pub_hal_fault") or self._pub_hal_fault is None:
            return
        try:
            from bonbon_msgs.msg import HalFault

            msg = HalFault()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.device = self._device_name
            msg.driver_mode = self._driver_mode
            msg.severity = severity
            msg.error_code = error_code
            msg.message = message
            msg.is_recovered = is_recovered
            msg.reconnect_attempt = reconnect_attempt
            self._pub_hal_fault.publish(msg)
        except Exception as exc:
            self.get_logger().warning(f"Failed to publish HalFault: {exc}")

    def _on_driver_fault(self, device: str, error_code: str, message: str) -> None:
        """Registered as fault callback in DriverBase.register_fault_callback()."""
        self.get_logger().error(f"[HAL FAULT] {device} {error_code}: {message}")
        self._publish_hal_fault(error_code, message, severity=_SEV_ERROR)
