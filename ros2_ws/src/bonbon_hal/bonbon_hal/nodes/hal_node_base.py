"""
bonbon_hal.nodes.hal_node_base
================================
Common LifecycleNode base for all HAL hardware nodes.

Provides:
  - Driver selection (real vs mock) from 'driver_mode' parameter
  - Standard health publishing to /bonbon/<subsystem>/<node>/health at 1 Hz
  - HalFault publishing to /bonbon/hal/fault
  - Reconnect loop via ReconnectPolicy
  - Structured logging
  - QoS profiles

Every HAL node inherits from HalNodeBase and implements:
  _create_driver()              → DriverBase
  _create_publishers()          → None
  _create_subscribers()         → None
  _publish_data()               → None  (called at node data_rate_hz)
"""

from __future__ import annotations

import logging
import threading
import time
from abc import abstractmethod

from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from bonbon_hal.base.driver_base import DriverBase
from bonbon_hal.base.health_reporter import HealthReporter
from bonbon_hal.base.reconnect_policy import ReconnectConfig, ReconnectPolicy

logger = logging.getLogger(__name__)

RELIABLE_TL = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)
RELIABLE_D10 = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
BEST_EFFORT_D5 = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    history=HistoryPolicy.KEEP_LAST,
    depth=5,
)

# Maximum consecutive read errors before a reconnect is attempted
_MAX_CONSEC_ERRORS = 5


class HalNodeBase(LifecycleNode, HealthReporter):
    """
    Abstract base for all BonBon HAL lifecycle nodes.

    Subclass must define:
      NODE_NAME       : str  — ROS2 node name
      DEVICE_NAME     : str  — "camera", "lidar", etc.
      HEALTH_TOPIC    : str  — /bonbon/.../health
      DEFAULT_RATE_HZ : float
    """

    NODE_NAME: str = "hal_node"
    DEVICE_NAME: str = "unknown"
    HEALTH_TOPIC: str = "/bonbon/hal/unknown/health"
    DEFAULT_RATE_HZ: float = 10.0

    def __init__(self) -> None:
        super().__init__(self.NODE_NAME)
        self._driver: DriverBase | None = None
        self._driver_mode = "mock"
        self._rate_hz = self.DEFAULT_RATE_HZ
        self._data_timer = None
        self._health_timer = None
        self._pub_health = None
        self._pub_hal_fault = None
        self._reconnect_policy: ReconnectPolicy | None = None
        self._lock = threading.Lock()

        # Exposed for HealthReporter mixin
        self._device_name = self.DEVICE_NAME
        self._node_name = self.NODE_NAME

        # Standard parameters every HAL node has
        self.declare_parameter("driver_mode", "mock")
        self.declare_parameter("data_rate_hz", self.DEFAULT_RATE_HZ)
        self.declare_parameter("reconnect_max_attempts", 5)
        self.declare_parameter("reconnect_base_delay_sec", 1.0)
        self.declare_parameter("reconnect_max_delay_sec", 30.0)

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        self._driver_mode = self.get_parameter("driver_mode").value
        self._rate_hz = self.get_parameter("data_rate_hz").value

        cfg = ReconnectConfig(
            max_attempts=self.get_parameter("reconnect_max_attempts").value,
            base_delay_sec=self.get_parameter("reconnect_base_delay_sec").value,
            max_delay_sec=self.get_parameter("reconnect_max_delay_sec").value,
        )
        self._reconnect_policy = ReconnectPolicy(self.DEVICE_NAME, cfg)

        try:
            self._driver = self._create_driver()
            self._driver.register_fault_callback(self._on_driver_fault)
        except Exception as exc:
            self.get_logger().error(f"Driver creation failed: {exc}")
            return TransitionCallbackReturn.FAILURE

        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        from bonbon_msgs.msg import HalFault, ModuleHealth

        self._pub_health = self.create_lifecycle_publisher(
            ModuleHealth, self.HEALTH_TOPIC, RELIABLE_D10
        )
        self._pub_hal_fault = self.create_lifecycle_publisher(
            HalFault, "/bonbon/hal/fault", RELIABLE_D10
        )

        self._create_publishers()
        self._create_subscribers()

        ok = self._driver.connect()
        if not ok:
            self.get_logger().error(f"[{self.DEVICE_NAME}] Initial connect failed")
            self._publish_hal_fault(
                "INITIAL_CONNECT_FAILED", "Driver failed to connect on activation"
            )
            # Continue activating — reconnect loop will retry
        else:
            self.get_logger().info(f"[{self.DEVICE_NAME}] Driver connected ({self._driver_mode})")

        # Data publication timer
        self._data_timer = self.create_timer(1.0 / self._rate_hz, self._safe_publish_data)
        # Health publication timer (always 1 Hz)
        self._health_timer = self.create_timer(1.0, self._publish_health)

        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        if self._data_timer:
            self._data_timer.cancel()
        if self._health_timer:
            self._health_timer.cancel()
        if self._driver:
            self._driver.disconnect()
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        if self._driver:
            self._driver.shutdown()
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        return self.on_cleanup(state)

    # ── Data publish wrapper (handles errors + reconnect) ─────────────────────

    def _safe_publish_data(self) -> None:
        if self._driver is None:
            return
        try:
            if not self._driver.is_connected:
                self._attempt_reconnect()
                return
            self._publish_data()
        except Exception as exc:
            self.get_logger().warning(f"[{self.DEVICE_NAME}] publish error: {exc}")
            if self._driver.health.consecutive_errors >= _MAX_CONSEC_ERRORS:
                self._attempt_reconnect()

    def _attempt_reconnect(self) -> None:
        if self._reconnect_policy is None:
            return
        if not self._reconnect_policy.should_attempt():
            if not self._reconnect_policy.exhausted():
                return  # waiting for backoff delay
            # Exhausted — escalate to Safety Supervisor
            self.get_logger().error(f"[{self.DEVICE_NAME}] Reconnect exhausted — reporting FAULT")
            self._publish_hal_fault(
                "RECONNECT_EXHAUSTED",
                f"{self.DEVICE_NAME} driver failed to reconnect after "
                f"{self._reconnect_policy.attempt_count} attempts",
                severity=3,  # FATAL
            )
            return

        wait = self._reconnect_policy.next_wait_sec()
        self.get_logger().warning(
            f"[{self.DEVICE_NAME}] Attempting reconnect in {wait:.1f}s "
            f"(attempt {self._reconnect_policy.attempt_count + 1})"
        )
        # Non-blocking: skip one cycle, attempt on next
        time.sleep(min(wait, 0.1))  # cap sleep to avoid blocking the timer thread
        ok = self._driver.reconnect()
        if ok:
            self._reconnect_policy.record_success()
            self._publish_hal_fault(
                "RECONNECTED",
                f"{self.DEVICE_NAME} reconnected",
                severity=0,
                is_recovered=True,
                reconnect_attempt=self._reconnect_policy.attempt_count,
            )
        else:
            self._reconnect_policy.record_failure()

    # ── Abstract interface for subclasses ─────────────────────────────────────

    @abstractmethod
    def _create_driver(self) -> DriverBase:
        """Instantiate and return the correct driver based on driver_mode."""

    @abstractmethod
    def _create_publishers(self) -> None:
        """Create topic publishers (called during on_activate)."""

    def _create_subscribers(self) -> None:
        """Override to create subscriptions (optional)."""

    @abstractmethod
    def _publish_data(self) -> None:
        """Read from driver and publish to ROS2 topic.  Called at data_rate_hz."""
