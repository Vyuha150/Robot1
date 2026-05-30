"""
bonbon_actuation.nodes.actuation_node
======================================
ROS2 Lifecycle node — high-level expressive motion controller for BonBon.

Pipeline (per ActuationGesture on /bonbon/behavior/actuation)
-------------------------------------------------------------
1. E-stop gate        — if hardware e-stop is engaged, reject everything except
                        the safe-fold recovery.
2. ActuationSafetyGate— check current safety level vs gesture priority.
3. ProximityGovernor  — derate speed / block arm-sweeping motion near people
                        and in child-safe / elderly modes.
4. GestureLibrary     — resolve the named gesture to a keyframe sequence.
5. MotionQueue        — if a gesture is already running, queue by priority;
                        emergency / higher-priority requests preempt.
6. ServoValidator     — clamp every servo target to safe mechanical limits.
7. /bonbon/hal/servo_commands — dispatch validated ServoStateArray to the HAL.
8. /bonbon/actuation/status   — publish ActuationStatus throughout.

Safety guarantees
-----------------
* NEVER publishes to the HAL without passing through ServoValidator.
* Hardware e-stop (``/bonbon/estop/state`` True) cancels the running gesture
  and blocks all non-recovery motion until released.
* Safety level DANGER+ cancels non-emergency gestures.
* Arm-sweeping gestures (``requires_clear_space``) are suppressed when a person
  is inside the proximity stop band.

Degraded mode
-------------
If the HAL servo topic has no subscribers (no servo node / simulation), the
node still validates, queues, and publishes status so the rest of the stack
behaves identically — it simply has no physical effect.
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

from std_msgs.msg import Bool, Header

from bonbon_msgs.msg import (
    ActuationGesture,
    ActuationStatus,
    SafetyState,
    ServoState,
    ServoStateArray,
    SocialNavigationHint,
    SpatialEntity,
)
from bonbon_srvs.srv import HealthCheck, PerformGesture, SetMode

from bonbon_actuation.core.actuation_safety_gate import ActuationSafetyGate
from bonbon_actuation.core.gesture_library import GestureLibrary
from bonbon_actuation.core.motion_profile import MotionProfileGenerator
from bonbon_actuation.core.motion_queue import MotionQueue
from bonbon_actuation.core.proximity_governor import ProximityGovernor
from bonbon_actuation.core.servo_validator import ServoValidator

_logger = logging.getLogger(__name__)

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
_QOS_SENSOR = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)

# Person tracks older than this are treated as gone (proximity cleared).
_PROXIMITY_TTL_SEC = 3.0
_EMERGENCY_GESTURES = frozenset({"emergency_attention_pose", "stop_gesture"})
_RECOVERY_GESTURE = "safe_folded_pose"


class ActuationNode(LifecycleNode):
    """High-level expressive motion controller (LifecycleNode)."""

    def __init__(self, node_name: str = "actuation_node") -> None:
        super().__init__(node_name)

        # Core components
        self._safety_gate = ActuationSafetyGate()
        self._validator = ServoValidator()
        self._motion_gen = MotionProfileGenerator()
        self._queue = MotionQueue()
        self._proximity = ProximityGovernor()

        # Execution state (protected by _lock)
        self._lock = threading.Lock()
        self._current_gesture: Optional[str] = None
        self._current_priority: int = 0
        self._current_event_id: Optional[str] = None
        self._gesture_start_time: float = 0.0
        self._cancel_requested: bool = False
        self._estop_engaged: bool = False
        self._last_person_seen: float = 0.0

        # Telemetry
        self._gestures_run = 0
        self._gestures_rejected = 0
        self._proximity_derates = 0

        # ROS2 I/O (created in on_activate)
        self._sub_gesture = None
        self._sub_safety = None
        self._sub_estop = None
        self._sub_hint = None
        self._sub_entity = None
        self._pub_servo = None
        self._pub_status = None
        self._srv_perform = None
        self._srv_health = None
        self._srv_mode = None
        self._proximity_timer = None

        self._executor: Optional[ThreadPoolExecutor] = None
        self._node_start: float = time.monotonic()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("ActuationNode configuring …")
        self.declare_parameter("servo_command_topic", "/bonbon/hal/servo_commands")
        self.declare_parameter("status_topic", "/bonbon/actuation/status")
        self.declare_parameter("gesture_topic", "/bonbon/behavior/actuation")
        self.declare_parameter("safety_topic", "/bonbon/safety/state")
        self.declare_parameter("estop_topic", "/bonbon/estop/state")
        self.declare_parameter("spatial_hint_topic", "/bonbon/spatial/hints")
        self.declare_parameter("spatial_entity_topic", "/bonbon/spatial/entities")
        self.declare_parameter("rest_on_deactivate", True)
        self.declare_parameter("operating_mode", "normal")
        self.declare_parameter("motion_queue_depth", 16)
        self.declare_parameter("executor_thread_count", 1)
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("ActuationNode activating …")
        p = self.get_parameter
        servo_topic = p("servo_command_topic").get_parameter_value().string_value
        status_topic = p("status_topic").get_parameter_value().string_value
        gesture_topic = p("gesture_topic").get_parameter_value().string_value
        safety_topic = p("safety_topic").get_parameter_value().string_value
        estop_topic = p("estop_topic").get_parameter_value().string_value
        hint_topic = p("spatial_hint_topic").get_parameter_value().string_value
        entity_topic = p("spatial_entity_topic").get_parameter_value().string_value
        mode = p("operating_mode").get_parameter_value().string_value
        depth = p("motion_queue_depth").get_parameter_value().integer_value
        n_threads = p("executor_thread_count").get_parameter_value().integer_value

        self._proximity.set_operating_mode(mode)
        self._queue = MotionQueue(max_depth=max(1, depth))
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, n_threads), thread_name_prefix="actuation"
        )

        # Publishers
        self._pub_servo = self.create_lifecycle_publisher(ServoStateArray, servo_topic, 10)
        self._pub_status = self.create_lifecycle_publisher(ActuationStatus, status_topic, 10)

        # Subscribers
        self._sub_safety = self.create_subscription(
            SafetyState, safety_topic, self._on_safety_state, _QOS_TRANSIENT
        )
        self._sub_estop = self.create_subscription(
            Bool, estop_topic, self._on_estop, _QOS_TRANSIENT
        )
        self._sub_gesture = self.create_subscription(
            ActuationGesture, gesture_topic, self._on_gesture_request, _QOS_DEFAULT
        )
        self._sub_hint = self.create_subscription(
            SocialNavigationHint, hint_topic, self._on_spatial_hint, _QOS_DEFAULT
        )
        self._sub_entity = self.create_subscription(
            SpatialEntity, entity_topic, self._on_spatial_entity, _QOS_SENSOR
        )

        # Services
        self._srv_perform = self.create_service(
            PerformGesture, "~/perform_gesture", self._handle_perform_gesture
        )
        self._srv_health = self.create_service(
            HealthCheck, "~/health_check", self._handle_health_check
        )
        self._srv_mode = self.create_service(SetMode, "~/set_mode", self._handle_set_mode)

        # Proximity TTL timer — clears stale person tracks.
        self._proximity_timer = self.create_timer(1.0, self._on_proximity_tick)

        self.get_logger().info(
            "ActuationNode active — %d gestures, mode=%s, queue_depth=%d.",
            len(GestureLibrary.list_names()), mode, depth,
        )
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("ActuationNode deactivating …")
        with self._lock:
            self._cancel_requested = True
        self._queue.clear()

        if self.get_parameter("rest_on_deactivate").get_parameter_value().bool_value:
            try:
                self._run_gesture_sync(_RECOVERY_GESTURE, speed_scale=0.5, priority=15)
            except Exception as exc:  # noqa: BLE001
                self.get_logger().error("Safe-fold on deactivate failed: %s", str(exc))

        if self._proximity_timer:
            self.destroy_timer(self._proximity_timer)
            self._proximity_timer = None
        for attr in ("_sub_gesture", "_sub_safety", "_sub_estop", "_sub_hint", "_sub_entity"):
            sub = getattr(self, attr, None)
            if sub:
                self.destroy_subscription(sub)
        for attr in ("_srv_perform", "_srv_health", "_srv_mode"):
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
        self._safety_gate.update_safety_state(msg.level, msg.actuation_enabled, msg.level_name)
        if msg.level >= 3:
            with self._lock:
                if self._current_gesture and self._current_gesture not in _EMERGENCY_GESTURES:
                    self._cancel_requested = True
                    self.get_logger().warn(
                        "Safety level %s: cancelling gesture '%s'.",
                        msg.level_name, self._current_gesture,
                    )
            self._queue.clear()

    def _on_estop(self, msg: Bool) -> None:
        engaged = bool(msg.data)
        with self._lock:
            changed = engaged != self._estop_engaged
            self._estop_engaged = engaged
            if engaged:
                self._cancel_requested = True
        if engaged:
            self._queue.clear()
            if changed:
                self.get_logger().warn("E-STOP engaged — all motion blocked, gestures cancelled.")
        elif changed:
            self.get_logger().info("E-STOP released — actuation re-enabled.")

    def _on_spatial_hint(self, msg: SocialNavigationHint) -> None:
        self._proximity.update_hint(msg.hint_type)

    def _on_spatial_entity(self, msg: SpatialEntity) -> None:
        if msg.entity_type != "person":
            return
        # Distance from robot origin (entity pose is robot-frame).
        px = msg.pose.pose.position.x
        py = msg.pose.pose.position.y
        dist = (px * px + py * py) ** 0.5
        self._proximity.update_proximity(dist, msg.person_category or "adult")
        self._last_person_seen = time.monotonic()

    def _on_proximity_tick(self) -> None:
        """Clear stale person proximity so derate releases when people leave."""
        if self._last_person_seen and (time.monotonic() - self._last_person_seen) > _PROXIMITY_TTL_SEC:
            self._proximity.clear_proximity()
            self._last_person_seen = 0.0

    def _on_gesture_request(self, msg: ActuationGesture) -> None:
        self._admit_or_queue(
            gesture_name=msg.gesture_name,
            priority=msg.priority,
            speed_scale=msg.speed_scale if msg.speed_scale > 0.0 else 1.0,
            event_id=msg.event_id,
        )

    # ── Admission / queueing ───────────────────────────────────────────────────

    def _admit_or_queue(
        self, gesture_name: str, priority: int, speed_scale: float, event_id: str
    ) -> str:
        """Decide whether to run now, queue, or reject a gesture request.

        Returns one of: 'running', 'queued', 'rejected'.
        """
        # E-stop hard gate (recovery fold is the only exception).
        with self._lock:
            estop = self._estop_engaged
        if estop and gesture_name != _RECOVERY_GESTURE:
            self._gestures_rejected += 1
            self._publish_status(event_id, gesture_name, "rejected", "e-stop engaged", 0.0)
            return "rejected"

        # Safety-level gate.
        allowed, reason = self._safety_gate.is_allowed(gesture_name, priority)
        if not allowed:
            self._gestures_rejected += 1
            self.get_logger().warn("Gesture '%s' rejected: %s", gesture_name, reason)
            self._publish_status(event_id, gesture_name, "rejected", reason, 0.0)
            return "rejected"

        gesture_def = GestureLibrary.get(gesture_name)
        if gesture_def is None:
            self._gestures_rejected += 1
            self.get_logger().error("Unknown gesture: '%s'", gesture_name)
            self._publish_status(event_id, gesture_name, "failed", "unknown gesture", 0.0)
            return "rejected"

        # Proximity gate — suppress arm-sweeping gestures too close to a person.
        decision = self._proximity.evaluate(priority)
        if decision.block_large_motion and gesture_def.requires_clear_space:
            self._gestures_rejected += 1
            self.get_logger().warn(
                "Gesture '%s' suppressed: %s", gesture_name, decision.reason
            )
            self._publish_status(
                event_id, gesture_name, "rejected",
                f"proximity: {decision.reason}", 0.0,
            )
            return "rejected"
        if decision.speed_scale < 1.0:
            self._proximity_derates += 1

        # Decide run-now vs queue.
        with self._lock:
            running = self._current_gesture is not None
            running_prio = self._current_priority
        if not running:
            if self._executor:
                self._executor.submit(
                    self._run_gesture_sync, gesture_name, speed_scale, event_id, priority
                )
            return "running"

        # A gesture is running. Preempt or queue.
        if priority >= 20 or (priority > running_prio and gesture_def.interruptible is not False):
            with self._lock:
                self._cancel_requested = True
            self._queue.enqueue(gesture_name, priority, speed_scale, event_id, gesture_def.interruptible)
            return "queued"

        admitted = self._queue.enqueue(
            gesture_name, priority, speed_scale, event_id, gesture_def.interruptible
        )
        return "queued" if admitted else "rejected"

    def _drain_queue(self) -> None:
        """Run the next queued gesture, if any. Called after each gesture ends."""
        nxt = self._queue.dequeue()
        if nxt is None:
            return
        self._run_gesture_sync(nxt.gesture_name, nxt.speed_scale, nxt.event_id, nxt.priority)

    # ── Gesture execution ──────────────────────────────────────────────────────

    def _run_gesture_sync(
        self,
        gesture_name: str,
        speed_scale: float = 1.0,
        event_id: str = "",
        priority: int = 5,
    ) -> bool:
        """Execute a gesture synchronously in a worker thread."""
        gesture = GestureLibrary.get(gesture_name)
        if gesture is None:
            return False

        # Apply proximity-governed speed derate at dispatch time.
        decision = self._proximity.evaluate(priority)
        effective_speed = max(0.1, speed_scale * decision.speed_scale)

        with self._lock:
            self._current_gesture = gesture_name
            self._current_priority = priority
            self._current_event_id = event_id
            self._gesture_start_time = time.monotonic()
            self._cancel_requested = False

        self._publish_status(event_id, gesture_name, "executing", decision.reason, 0.0)
        steps = self._motion_gen.generate_steps(gesture, effective_speed)
        prev_t = 0.0
        completed = False

        try:
            for step in steps:
                with self._lock:
                    if self._cancel_requested:
                        self._publish_status(
                            event_id, gesture_name, "cancelled",
                            "cancelled by higher-priority request or e-stop", step.progress,
                        )
                        return False
                wait = step.elapsed_sec - prev_t
                if wait > 1e-4:
                    time.sleep(wait)
                prev_t = step.elapsed_sec

                vr = self._validator.validate(step.targets)
                for warn in vr.warnings:
                    self.get_logger().warn(warn)
                if not vr.valid:
                    self.get_logger().error(
                        "Gesture '%s' servo validation error: %s", gesture_name, vr.errors
                    )
                    self._publish_status(
                        event_id, gesture_name, "failed", str(vr.errors), step.progress
                    )
                    return False

                self._publish_servo_commands(vr.clamped_targets)
                self._publish_status(event_id, gesture_name, "executing", "", step.progress)

            elapsed = time.monotonic() - self._gesture_start_time
            self._gestures_run += 1
            self._publish_status(event_id, gesture_name, "completed", "", 1.0)
            self.get_logger().info("Gesture '%s' completed in %.2f s.", gesture_name, elapsed)
            completed = True
            return True

        except Exception as exc:  # noqa: BLE001
            self.get_logger().error("Gesture '%s' raised exception: %s", gesture_name, exc)
            self._publish_status(event_id, gesture_name, "failed", str(exc), 0.0)
            return False
        finally:
            with self._lock:
                self._current_gesture = None
                self._current_priority = 0
                self._current_event_id = None
            # Drain the next queued gesture (only on a clean finish; on cancel the
            # preempting request is already queued and will be drained too).
            if completed or not self._queue.is_empty():
                if self._executor:
                    self._executor.submit(self._drain_queue)

    # ── Publishing helpers ─────────────────────────────────────────────────────

    def _publish_servo_commands(self, targets) -> None:
        if self._pub_servo is None:
            return
        msg = ServoStateArray()
        msg.header = Header()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "actuation"
        for t in targets:
            ss = ServoState()
            ss.servo_id = t.servo_id
            ss.position_deg = t.position_deg
            ss.velocity_dps = t.velocity_dps
            ss.current_ma = 0.0
            ss.temperature_c = 0.0
            ss.is_enabled = True
            ss.has_error = False
            ss.error_msg = ""
            msg.servos.append(ss)
        self._pub_servo.publish(msg)

    def _publish_status(
        self, event_id: str, gesture_name: str, status: str, reason: str, progress: float
    ) -> None:
        if self._pub_status is None:
            return
        msg = ActuationStatus()
        msg.header = Header()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.event_id = event_id
        msg.gesture_name = gesture_name
        msg.status = status
        msg.reason = reason
        msg.progress = float(progress)
        msg.elapsed_sec = float(
            time.monotonic() - self._gesture_start_time if self._gesture_start_time else 0.0
        )
        self._pub_status.publish(msg)

    # ── Service handlers ───────────────────────────────────────────────────────

    def _handle_perform_gesture(
        self, request: PerformGesture.Request, response: PerformGesture.Response
    ) -> PerformGesture.Response:
        g = request.gesture
        priority = g.priority if g.priority else 5
        speed = g.speed_scale if g.speed_scale > 0 else 1.0
        event_id = g.event_id or str(uuid.uuid4())[:8]
        outcome = self._admit_or_queue(g.gesture_name, priority, speed, event_id)
        response.accepted = outcome in ("running", "queued")
        response.error_message = "" if response.accepted else "rejected"
        response.queue_position = outcome
        return response

    def _handle_set_mode(
        self, request: SetMode.Request, response: SetMode.Response
    ) -> SetMode.Response:
        allowed = {"normal", "child_safe", "elderly", "degraded", "demo", "emergency"}
        prev = self._proximity.operating_mode
        if request.mode not in allowed:
            response.success = False
            response.previous_mode = prev
            response.error_message = f"Unknown mode '{request.mode}'"
            return response
        self._proximity.set_operating_mode(request.mode)
        self.get_logger().info(
            "Operating mode '%s' → '%s' by %s", prev, request.mode, request.operator_id or "?"
        )
        response.success = True
        response.previous_mode = prev
        response.error_message = ""
        return response

    def _handle_health_check(
        self, request: HealthCheck.Request, response: HealthCheck.Response
    ) -> HealthCheck.Response:
        warnings: list[str] = []
        if self._estop_engaged:
            warnings.append("e-stop engaged")
        if self._proximity.nearest_person_m < 1.0:
            warnings.append(f"person within {self._proximity.nearest_person_m:.2f}m")
        response.healthy = True
        response.status = (
            f"active; gesture={self._current_gesture or 'none'}; "
            f"mode={self._proximity.operating_mode}; "
            f"queue={self._queue.depth()}; "
            f"safety={self._safety_gate.safety_level}; "
            f"run={self._gestures_run}; rejected={self._gestures_rejected}; "
            f"derates={self._proximity_derates}"
        )
        response.warnings = warnings
        response.errors = []
        response.uptime_sec = time.monotonic() - self._node_start
        return response


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
