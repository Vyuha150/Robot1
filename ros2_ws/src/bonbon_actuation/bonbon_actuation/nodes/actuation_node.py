"""
bonbon_actuation.nodes.actuation_node
======================================
ROS2 Lifecycle node — high-level expressive motion controller for BonBon.

Architecture
------------
ActuationGesture messages arrive on /bonbon/behavior/actuation.  Each request
is:

1. Safety-gated via ActuationSafetyGate (checks current safety level / priority).
2. Looked up in GestureLibrary.
3. Servo targets at each keyframe are validated + clamped by ServoValidator.
4. A background thread executes the keyframe sequence, sleeping between steps.
5. ServoStateArray commands go to /bonbon/hal/servo_commands.
6. ActuationStatus messages are published throughout execution.

Lifecycle transitions
---------------------
configure  → declare parameters, instantiate core objects
activate   → create subscribers, publishers, services; start executor thread pool
deactivate → cancel current gesture, move to safe_folded_pose, destroy ROS2 I/O
cleanup    → shut down thread pool

Safety guarantee
----------------
NEVER publishes to /bonbon/hal/servo_commands without passing through
ServoValidator.  The ActuationSafetyGate blocks all gestures at or below the
minimum priority for the current safety level.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import rclpy
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from builtin_interfaces.msg import Time as BuiltinTime
from std_msgs.msg import Header

from bonbon_msgs.msg import (
    ActuationGesture,
    ActuationStatus,
    SafetyState,
    ServoState,
    ServoStateArray,
)
from bonbon_srvs.srv import HealthCheck, PerformGesture

from bonbon_actuation.core.actuation_safety_gate import ActuationSafetyGate
from bonbon_actuation.core.gesture_library import GestureLibrary
from bonbon_actuation.core.motion_profile import MotionProfileGenerator
from bonbon_actuation.core.servo_validator import ServoValidator

_logger = logging.getLogger(__name__)

# QoS profiles
_QOS_TRANSIENT = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)
_QOS_DEFAULT = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)


class ActuationNode(LifecycleNode):
    """High-level expressive motion controller (LifecycleNode).

    Translates :class:`bonbon_msgs.ActuationGesture` requests into validated
    :class:`bonbon_msgs.ServoStateArray` commands dispatched to the HAL layer.
    """

    def __init__(self, node_name: str = "actuation_node") -> None:
        super().__init__(node_name)

        # Core components
        self._safety_gate = ActuationSafetyGate()
        self._validator = ServoValidator()
        self._motion_gen = MotionProfileGenerator()

        # Execution state (protected by _lock)
        self._lock = threading.Lock()
        self._current_gesture: Optional[str] = None
        self._current_event_id: Optional[str] = None
        self._gesture_start_time: float = 0.0
        self._cancel_requested: bool = False

        # ROS2 I/O (created in on_activate)
        self._sub_gesture = None
        self._sub_safety = None
        self._pub_servo = None
        self._pub_status = None
        self._srv_perform = None
        self._srv_health = None

        self._executor: Optional[ThreadPoolExecutor] = None
        self._node_start: float = time.monotonic()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("ActuationNode configuring …")
        self.declare_parameter("servo_command_topic", "/bonbon/hal/servo_commands")
        self.declare_parameter("status_topic",        "/bonbon/actuation/status")
        self.declare_parameter("gesture_topic",       "/bonbon/behavior/actuation")
        self.declare_parameter("safety_topic",        "/bonbon/safety/state")
        self.declare_parameter("rest_on_deactivate",  True)
        self.declare_parameter("executor_thread_count", 1)
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("ActuationNode activating …")

        p = self.get_parameter
        servo_topic   = p("servo_command_topic").get_parameter_value().string_value
        status_topic  = p("status_topic").get_parameter_value().string_value
        gesture_topic = p("gesture_topic").get_parameter_value().string_value
        safety_topic  = p("safety_topic").get_parameter_value().string_value
        n_threads     = p("executor_thread_count").get_parameter_value().integer_value

        self._executor = ThreadPoolExecutor(
            max_workers=max(1, n_threads),
            thread_name_prefix="actuation",
        )

        # Publishers
        self._pub_servo  = self.create_lifecycle_publisher(ServoStateArray, servo_topic,  10)
        self._pub_status = self.create_lifecycle_publisher(ActuationStatus,  status_topic, 10)

        # Subscribers
        self._sub_safety  = self.create_subscription(
            SafetyState, safety_topic, self._on_safety_state, _QOS_TRANSIENT
        )
        self._sub_gesture = self.create_subscription(
            ActuationGesture, gesture_topic, self._on_gesture_request, _QOS_DEFAULT
        )

        # Services
        self._srv_perform = self.create_service(
            PerformGesture, "~/perform_gesture", self._handle_perform_gesture
        )
        self._srv_health = self.create_service(
            HealthCheck, "~/health_check", self._handle_health_check
        )

        self.get_logger().info(
            "ActuationNode active — %d gestures available.",
            len(GestureLibrary.list_names()),
        )
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("ActuationNode deactivating …")

        # Cancel any running gesture
        with self._lock:
            self._cancel_requested = True

        # Move to safe folded pose before shutting down
        if self.get_parameter("rest_on_deactivate").get_parameter_value().bool_value:
            try:
                self._run_gesture_sync("safe_folded_pose", speed_scale=0.5)
            except Exception as exc:
                self.get_logger().error("Safe-fold on deactivate failed: %s", str(exc))

        # Tear down ROS2 I/O
        for attr in ("_sub_gesture", "_sub_safety"):
            sub = getattr(self, attr, None)
            if sub:
                self.destroy_subscription(sub)
        for attr in ("_srv_perform", "_srv_health"):
            srv = getattr(self, attr, None)
            if srv:
                self.destroy_service(srv)
        for attr in ("_pub_servo", "_pub_status"):
            pub = getattr(self, attr, None)
            if pub:
                self.destroy_publisher(pub)

        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("ActuationNode cleanup …")
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None
        return TransitionCallbackReturn.SUCCESS

    # ── Subscription callbacks ─────────────────────────────────────────────────

    def _on_safety_state(self, msg: SafetyState) -> None:
        self._safety_gate.update_safety_state(
            msg.level, msg.actuation_enabled, msg.level_name
        )
        # Cancel non-emergency gestures when danger or worse
        if msg.level >= 3:
            with self._lock:
                if self._current_gesture and self._current_gesture not in (
                    "emergency_attention_pose", "stop_gesture"
                ):
                    self._cancel_requested = True
                    self.get_logger().warn(
                        "Safety level %s: cancelling gesture '%s'.",
                        msg.level_name, self._current_gesture,
                    )

    def _on_gesture_request(self, msg: ActuationGesture) -> None:
        allowed, reason = self._safety_gate.is_allowed(msg.gesture_name, msg.priority)
        if not allowed:
            self.get_logger().warn(
                "Gesture '%s' rejected: %s", msg.gesture_name, reason
            )
            self._publish_status(msg.event_id, msg.gesture_name, "rejected", reason, 0.0)
            return

        if not GestureLibrary.has(msg.gesture_name):
            self.get_logger().error("Unknown gesture: '%s'", msg.gesture_name)
            self._publish_status(
                msg.event_id, msg.gesture_name, "failed", "unknown gesture", 0.0
            )
            return

        gesture_def = GestureLibrary.get(msg.gesture_name)

        # Handle interruption of the current gesture
        with self._lock:
            if self._current_gesture is not None:
                if not gesture_def.interruptible and msg.priority < 10:
                    self.get_logger().warn(
                        "Gesture '%s' cannot interrupt non-interruptible '%s'.",
                        msg.gesture_name, self._current_gesture,
                    )
                    self._publish_status(
                        msg.event_id, msg.gesture_name,
                        "rejected", "current gesture not interruptible", 0.0,
                    )
                    return
                self._cancel_requested = True

        if self._executor:
            self._executor.submit(self._run_gesture_async, msg)

    # ── Gesture execution ──────────────────────────────────────────────────────

    def _run_gesture_async(self, msg: ActuationGesture) -> None:
        self._run_gesture_sync(
            msg.gesture_name,
            speed_scale=msg.speed_scale if msg.speed_scale > 0.0 else 1.0,
            event_id=msg.event_id,
        )

    def _run_gesture_sync(
        self,
        gesture_name: str,
        speed_scale: float = 1.0,
        event_id: str = "",
    ) -> bool:
        """Execute a gesture synchronously.  Returns True on completion."""
        gesture = GestureLibrary.get(gesture_name)
        if gesture is None:
            return False

        with self._lock:
            self._current_gesture    = gesture_name
            self._current_event_id   = event_id
            self._gesture_start_time = time.monotonic()
            self._cancel_requested   = False

        self._publish_status(event_id, gesture_name, "executing", "", 0.0)

        steps = self._motion_gen.generate_steps(gesture, speed_scale)
        prev_t = 0.0

        try:
            for step in steps:
                with self._lock:
                    if self._cancel_requested:
                        self._publish_status(
                            event_id, gesture_name, "cancelled",
                            "cancelled by higher-priority request", step.progress,
                        )
                        return False

                # Sleep until the step's timestamp
                wait = step.elapsed_sec - prev_t
                if wait > 1e-4:
                    time.sleep(wait)
                prev_t = step.elapsed_sec

                # Validate + clamp servo targets
                vr = self._validator.validate(step.targets)
                for warn in vr.warnings:
                    self.get_logger().warn(warn)
                if not vr.valid:
                    self.get_logger().error(
                        "Gesture '%s' servo validation error: %s",
                        gesture_name, vr.errors,
                    )
                    self._publish_status(
                        event_id, gesture_name, "failed",
                        str(vr.errors), step.progress,
                    )
                    return False

                self._publish_servo_commands(vr.clamped_targets, gesture_name)
                self._publish_status(
                    event_id, gesture_name, "executing", "", step.progress
                )

            elapsed = time.monotonic() - self._gesture_start_time
            self._publish_status(event_id, gesture_name, "completed", "", 1.0)
            self.get_logger().info(
                "Gesture '%s' completed in %.2f s.", gesture_name, elapsed
            )
            return True

        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(
                "Gesture '%s' raised exception: %s", gesture_name, exc
            )
            self._publish_status(event_id, gesture_name, "failed", str(exc), 0.0)
            return False

        finally:
            with self._lock:
                self._current_gesture  = None
                self._current_event_id = None

    # ── Publishing helpers ─────────────────────────────────────────────────────

    def _publish_servo_commands(self, targets, gesture_name: str) -> None:
        if self._pub_servo is None:
            return
        msg = ServoStateArray()
        msg.header = Header()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "actuation"
        for t in targets:
            ss = ServoState()
            ss.servo_id     = t.servo_id
            ss.position_deg = t.position_deg
            ss.velocity_dps = t.velocity_dps
            ss.current_ma   = 0.0
            ss.temperature_c = 0.0
            ss.is_enabled   = True
            ss.has_error    = False
            ss.error_msg    = ""
            msg.servos.append(ss)
        self._pub_servo.publish(msg)

    def _publish_status(
        self,
        event_id: str,
        gesture_name: str,
        status: str,
        reason: str,
        progress: float,
    ) -> None:
        if self._pub_status is None:
            return
        msg = ActuationStatus()
        msg.header = Header()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.event_id     = event_id
        msg.gesture_name = gesture_name
        msg.status       = status
        msg.reason       = reason
        msg.progress     = float(progress)
        msg.elapsed_sec  = float(
            time.monotonic() - self._gesture_start_time
            if self._gesture_start_time
            else 0.0
        )
        self._pub_status.publish(msg)

    # ── Service handlers ───────────────────────────────────────────────────────

    def _handle_perform_gesture(
        self,
        request: PerformGesture.Request,
        response: PerformGesture.Response,
    ) -> PerformGesture.Response:
        # Use the gesture inside ActuationGesture message if provided
        gesture_name = request.gesture.gesture_name
        priority     = request.gesture.priority if request.gesture.priority else 5
        speed_scale  = request.gesture.speed_scale if request.gesture.speed_scale > 0 else 1.0

        allowed, reason = self._safety_gate.is_allowed(gesture_name, priority)
        if not allowed:
            response.accepted       = False
            response.error_message  = reason
            response.queue_position = "rejected"
            return response

        if not GestureLibrary.has(gesture_name):
            response.accepted       = False
            response.error_message  = f"Unknown gesture: {gesture_name}"
            response.queue_position = "rejected"
            return response

        event_id = str(uuid.uuid4())[:8]
        success = self._run_gesture_sync(gesture_name, speed_scale, event_id)
        response.accepted       = success
        response.error_message  = "" if success else "Execution failed"
        response.queue_position = "completed" if success else "failed"
        return response

    def _handle_health_check(
        self,
        request: HealthCheck.Request,
        response: HealthCheck.Response,
    ) -> HealthCheck.Response:
        response.healthy   = True
        response.status    = (
            f"active; current_gesture={self._current_gesture or 'none'}; "
            f"safety_level={self._safety_gate.safety_level}"
        )
        response.warnings  = []
        response.errors    = []
        response.uptime_sec = time.monotonic() - self._node_start
        return response


# ── Entry point ───────────────────────────────────────────────────────────────

def main(args=None) -> None:
    """ROS2 entry point."""
    rclpy.init(args=args)
    node = ActuationNode("actuation_node")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
