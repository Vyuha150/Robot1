"""
bonbon_gesture.nodes.gesture_node
===================================
CLASS-C IMPORTANT: Production gesture-recognition LifecycleNode.

Full pipeline per camera frame
--------------------------------
1. Throttle — skip frames based on ``frame_sample_rate`` counter.
2. Decode   — convert sensor_msgs/Image to numpy BGR via manual decoding
              (no cv_bridge runtime dependency).
3. Backend  — submit to ThreadPoolExecutor; backend.process_frame() returns
              List[PersonLandmarks].
4. Classify — for each person: HandGestureClassifier + BodyGestureClassifier
              + HeadGestureClassifier.
5. Smooth   — GestureTemporalSmoother majority-vote + cooldown.
6. Publish  — build GestureEvent message and publish on /bonbon/gesture/events.
7. Diagnose — publish JSON status on /bonbon/gesture/status.

Subscribed topics
------------------
  /bonbon/vision/camera/color/image_raw  sensor_msgs/Image
  /bonbon/vision/persons                 bonbon_msgs/PersonStateArray
  /bonbon/safety/state                   bonbon_msgs/SafetyState

Published topics
-----------------
  /bonbon/gesture/events                 bonbon_msgs/GestureEvent
  /bonbon/gesture/status                 std_msgs/String (JSON)
  /bonbon/diagnostics/events             std_msgs/String (JSON)

Services
---------
  /bonbon/gesture/health_check           bonbon_srvs/HealthCheck
  /bonbon/gesture/set_enabled            bonbon_srvs/SetMode
"""

from __future__ import annotations

import json
import logging
import threading
import time
import traceback
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Dict, List, Optional, Tuple

import numpy as np
import rclpy
from bonbon_msgs.msg import GestureEvent, PersonStateArray, SafetyState
from bonbon_srvs.srv import HealthCheck, SetMode
from builtin_interfaces.msg import Time as BuiltinTime
from geometry_msgs.msg import Point, Vector3
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image
from std_msgs.msg import Header, String

from ..backends.gesture_backend_interface import GestureBackendInterface, PersonLandmarks
from ..backends.mediapipe_backend import MediaPipeBackend
from ..backends.mock_backend import MockBackend
from ..classifiers.body_gesture_classifier import BodyGestureClassifier
from ..classifiers.hand_gesture_classifier import HandGestureClassifier
from ..classifiers.head_gesture_classifier import HeadGestureClassifier
from ..config.gesture_config import GestureConfig
from ..health.health_monitor import GestureHealthMonitor
from ..logic.intent_mapper import GestureIntentMapper
from ..logic.safety_classifier import GestureSafetyClassifier
from ..logic.temporal_smoother import GestureTemporalSmoother

_LOG = logging.getLogger(__name__)

# ── QoS profiles ──────────────────────────────────────────────────────────────

_RELIABLE_D10 = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
_RELIABLE_TL = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)
_BEST_EFFORT_D2 = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    history=HistoryPolicy.KEEP_LAST,
    depth=2,
)

# Safety states that disable gesture processing
_BLOCKING_SAFETY_STATES = frozenset({
    SafetyState.SAFE_STOP,
    SafetyState.FAULT,
})

NODE_NAME = "gesture_node"
SOURCE_MODULE = "bonbon_gesture"


class GestureNode(LifecycleNode):
    """ROS2 LifecycleNode for BonBon gesture recognition.

    Lifecycle states:
    * **Unconfigured → Configured** (``on_configure``):
      Reads parameters, creates classifiers, initialises backend.
    * **Configured → Active** (``on_activate``):
      Creates subscribers, publishers, services; starts executor thread pool.
    * **Active → Inactive** (``on_deactivate``):
      Destroys subscribers and publishers, shuts down executor.
    * **Inactive / Active → Unconfigured** (``on_cleanup``):
      Releases backend resources.
    """

    def __init__(self) -> None:
        super().__init__(NODE_NAME)
        # Declared before on_configure so the launch file can inject values
        self._declare_parameters()

        self._config: Optional[GestureConfig] = None
        self._backend: Optional[GestureBackendInterface] = None
        self._hand_cls: Optional[HandGestureClassifier] = None
        self._body_cls: Optional[BodyGestureClassifier] = None
        self._head_cls: Optional[HeadGestureClassifier] = None
        self._smoother: Optional[GestureTemporalSmoother] = None
        self._intent_mapper: Optional[GestureIntentMapper] = None
        self._safety_cls: Optional[GestureSafetyClassifier] = None
        self._health: Optional[GestureHealthMonitor] = None

        # State
        self._frame_counter: int = 0
        self._safety_blocked: bool = False
        self._lock: threading.Lock = threading.Lock()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._person_positions: Dict[str, Point] = {}  # person_id → position
        self._in_flight: Optional[Future] = None

        # Pub/sub handles (created in on_activate)
        self._pub_events = None
        self._pub_status = None
        self._pub_diag = None
        self._sub_image = None
        self._sub_persons = None
        self._sub_safety = None
        self._srv_health = None
        self._srv_set_enabled = None

    # ------------------------------------------------------------------
    # Lifecycle transitions
    # ------------------------------------------------------------------

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        """Read parameters, build pipeline components, warm up backend."""
        self.get_logger().info("GestureNode configuring …")
        try:
            self._config = GestureConfig.from_ros_params(self)
            self._health = GestureHealthMonitor(start_time=time.monotonic())

            # Classifiers
            self._hand_cls = HandGestureClassifier()
            self._body_cls = BodyGestureClassifier()
            self._head_cls = HeadGestureClassifier(self._config)
            self._smoother = GestureTemporalSmoother(self._config)
            self._intent_mapper = GestureIntentMapper()
            self._safety_cls = GestureSafetyClassifier()

            # Backend selection
            self._backend = self._create_backend(self._config.backend)
            self._backend.warmup()
            self._health.set_backend_ready(self._backend.is_ready)

            if not self._backend.is_ready:
                self.get_logger().warning(
                    f"Backend '{self._config.backend}' is not ready after warmup. "
                    "Falling back to MockBackend."
                )
                self._backend = MockBackend(self._config, test_scenario=False)
                self._backend.warmup()
                self._health.set_backend_ready(self._backend.is_ready)

            self.get_logger().info(
                f"GestureNode configured. backend={self._config.backend}, "
                f"ready={self._backend.is_ready}"
            )
            return TransitionCallbackReturn.SUCCESS

        except Exception as exc:
            self.get_logger().error(f"GestureNode configure failed: {exc}\n{traceback.format_exc()}")
            return TransitionCallbackReturn.FAILURE

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        """Create publishers, subscribers, services, and thread pool."""
        self.get_logger().info("GestureNode activating …")
        try:
            # Thread pool (1 worker — prevents concurrent backend calls)
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gesture_backend")

            # Publishers
            self._pub_events = self.create_publisher(GestureEvent, "/bonbon/gesture/events", _RELIABLE_D10)
            self._pub_status = self.create_publisher(String, "/bonbon/gesture/status", _RELIABLE_D10)
            self._pub_diag = self.create_publisher(String, "/bonbon/diagnostics/events", _RELIABLE_D10)

            # Subscribers
            self._sub_image = self.create_subscription(
                Image,
                "/bonbon/vision/camera/color/image_raw",
                self._cb_frame,
                _BEST_EFFORT_D2,
            )
            self._sub_persons = self.create_subscription(
                PersonStateArray,
                "/bonbon/vision/persons",
                self._cb_persons,
                _RELIABLE_D10,
            )
            self._sub_safety = self.create_subscription(
                SafetyState,
                "/bonbon/safety/state",
                self._cb_safety,
                _RELIABLE_TL,
            )

            # Services
            self._srv_health = self.create_service(
                HealthCheck,
                "/bonbon/gesture/health_check",
                self._srv_health_check,
            )
            self._srv_set_enabled = self.create_service(
                SetMode,
                "/bonbon/gesture/set_enabled",
                self._srv_set_enabled_cb,
            )

            # Periodic status timer (1 Hz)
            self._status_timer = self.create_timer(1.0, self._publish_status)

            self._health.set_enabled(self._config.enabled)
            self.get_logger().info("GestureNode active.")
            return TransitionCallbackReturn.SUCCESS

        except Exception as exc:
            self.get_logger().error(f"GestureNode activate failed: {exc}\n{traceback.format_exc()}")
            return TransitionCallbackReturn.FAILURE

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        """Destroy subscribers, publishers, and shut down thread pool."""
        self.get_logger().info("GestureNode deactivating …")
        self._shutdown_executor()
        # Destroy subscriptions
        if self._sub_image:
            self.destroy_subscription(self._sub_image)
            self._sub_image = None
        if self._sub_persons:
            self.destroy_subscription(self._sub_persons)
            self._sub_persons = None
        if self._sub_safety:
            self.destroy_subscription(self._sub_safety)
            self._sub_safety = None
        # Destroy publishers
        if self._pub_events:
            self.destroy_publisher(self._pub_events)
            self._pub_events = None
        if self._pub_status:
            self.destroy_publisher(self._pub_status)
            self._pub_status = None
        if self._pub_diag:
            self.destroy_publisher(self._pub_diag)
            self._pub_diag = None
        # Destroy services
        if self._srv_health:
            self.destroy_service(self._srv_health)
            self._srv_health = None
        if self._srv_set_enabled:
            self.destroy_service(self._srv_set_enabled)
            self._srv_set_enabled = None
        if hasattr(self, "_status_timer") and self._status_timer:
            self.destroy_timer(self._status_timer)
            self._status_timer = None
        self.get_logger().info("GestureNode deactivated.")
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        """Release backend and classifiers."""
        self.get_logger().info("GestureNode cleaning up …")
        self._backend = None
        self._hand_cls = None
        self._body_cls = None
        self._head_cls = None
        self._smoother = None
        self._config = None
        self._health = None
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("GestureNode shutting down.")
        self._shutdown_executor()
        return TransitionCallbackReturn.SUCCESS

    # ------------------------------------------------------------------
    # Subscription callbacks
    # ------------------------------------------------------------------

    def _cb_frame(self, msg: Image) -> None:
        """Handle an incoming camera frame.

        Applies frame-rate throttling and dispatches processing to the
        ThreadPoolExecutor so the ROS executor thread is never blocked.

        Args:
            msg: Incoming sensor_msgs/Image message.
        """
        if self._config is None or not self._config.enabled:
            return
        if self._safety_blocked:
            return

        self._health.record_frame_received()

        # Throttle: process every Nth frame
        with self._lock:
            self._frame_counter += 1
            should_process = (self._frame_counter % self._config.frame_sample_rate) == 0
            in_flight = self._in_flight is not None and not self._in_flight.done()

        if not should_process or in_flight:
            return

        # Decode image on the callback thread (fast, numpy only)
        try:
            frame = self._ros_image_to_numpy(msg)
        except Exception as exc:
            self.get_logger().warning(f"Image decode failed: {exc}")
            return

        stamp = msg.header.stamp

        # Submit heavy backend work to executor
        with self._lock:
            self._in_flight = self._executor.submit(self._process_frame_async, frame, stamp)

    def _cb_persons(self, msg: PersonStateArray) -> None:
        """Update the person_id → map-position lookup.

        Args:
            msg: Incoming PersonStateArray message.
        """
        with self._lock:
            self._person_positions = {
                p.track_id: p.position for p in msg.persons
            }

    def _cb_safety(self, msg: SafetyState) -> None:
        """Disable processing when in SAFE_STOP or FAULT state.

        Args:
            msg: Incoming SafetyState message.
        """
        blocked = msg.state in _BLOCKING_SAFETY_STATES
        if blocked != self._safety_blocked:
            self._safety_blocked = blocked
            self.get_logger().warning(
                f"Safety state changed: state={msg.state_name}, "
                f"gesture_processing={'BLOCKED' if blocked else 'ENABLED'}"
            )

    # ------------------------------------------------------------------
    # Async processing pipeline
    # ------------------------------------------------------------------

    def _process_frame_async(self, frame: np.ndarray, stamp) -> None:
        """Run the full gesture pipeline on *frame* (called from thread pool).

        1. Run backend.
        2. Classify each person.
        3. Smooth via temporal smoother.
        4. Publish fired gesture events.

        Args:
            frame: BGR numpy image.
            stamp: builtin_interfaces.msg.Time from the source message header.
        """
        t0 = time.monotonic()
        try:
            landmarks_list: List[PersonLandmarks] = self._backend.process_frame(frame)
        except Exception as exc:
            err_str = str(exc)
            self._health.record_backend_failure(err_str)
            self.get_logger().warning(f"Backend processing error: {err_str}")
            return

        latency = time.monotonic() - t0
        if latency > self._config.processing_timeout_sec:
            self.get_logger().warning(
                f"Backend exceeded timeout: {latency*1000:.1f}ms "
                f"(limit={self._config.processing_timeout_sec*1000:.0f}ms)"
            )

        self._health.record_frame_processed(latency)

        for person_lm in landmarks_list:
            self._classify_and_publish(person_lm, stamp)

    def _classify_and_publish(self, lm: PersonLandmarks, stamp) -> None:
        """Classify landmarks for one person and publish any fired gesture events.

        Args:
            lm: :class:`PersonLandmarks` for one person in the current frame.
            stamp: Message timestamp.
        """
        # ── Hand classification ──────────────────────────────────────────────
        hand_gesture = "none"
        hand_conf = 0.0
        pointing_dir = Vector3()

        if self._config.hand_gesture_enabled:
            # Prefer whichever hand is more visible (right-hand bias as tie-break)
            right_result = self._hand_cls.classify(lm.right_hand, is_right=True, pose_landmarks=lm.pose)
            left_result = self._hand_cls.classify(lm.left_hand, is_right=False, pose_landmarks=lm.pose)

            if right_result[1] >= left_result[1]:
                hand_gesture, hand_conf = right_result
                pointing_is_right = True
            else:
                hand_gesture, hand_conf = left_result
                pointing_is_right = False
        else:
            pointing_is_right = True

        # ── Body classification ──────────────────────────────────────────────
        if self._config.body_gesture_enabled:
            final_gesture, final_conf = self._body_cls.classify(lm.pose, hand_gesture)
        else:
            final_gesture, final_conf = hand_gesture, hand_conf

        # ── Head classification ──────────────────────────────────────────────
        if self._config.head_gesture_enabled:
            head_gesture, head_conf = self._head_cls.update(lm.tracking_id, lm.face_mesh)
            # Head gestures override if higher confidence and no strong body gesture
            if head_conf > final_conf and head_gesture != "none":
                final_gesture, final_conf = head_gesture, head_conf

        # ── Confidence threshold ─────────────────────────────────────────────
        if final_conf < self._config.confidence_threshold:
            return

        # ── Temporal smoothing ───────────────────────────────────────────────
        result = self._smoother.update(lm.tracking_id, final_gesture, final_conf)
        if result is None:
            return

        smoothed_gesture, smoothed_conf, just_started, is_held, just_ended = result

        # ── Compute pointing direction vector ────────────────────────────────
        if "pointing" in smoothed_gesture and lm.pose and len(lm.pose) >= 33:
            from ..processors.pose_landmark_processor import PoseLandmarkProcessor
            proc = PoseLandmarkProcessor(self._config)
            dx, dy, dz = proc.compute_pointing_direction(lm.pose, use_right=pointing_is_right)
            pointing_dir = Vector3(x=float(dx), y=float(dy), z=float(dz))

        # ── Safety classification ────────────────────────────────────────────
        safety_relevant, safety_class, requires_immediate = self._safety_cls.classify(smoothed_gesture)

        # ── Build GestureEvent message ───────────────────────────────────────
        person_pos = self._get_person_position(lm.tracking_id)

        event = GestureEvent()
        event.header = Header()
        event.header.stamp = stamp
        event.header.frame_id = "camera_color_optical_frame"
        event.event_id = str(uuid.uuid4())
        event.detected_at = stamp
        event.source_module = SOURCE_MODULE
        event.person_id = f"person_{lm.tracking_id}"
        event.tracking_id = lm.tracking_id
        event.gesture_type = smoothed_gesture
        event.confidence = float(smoothed_conf)
        event.person_position_map = person_pos
        event.pointing_direction = pointing_dir
        event.safety_relevant = safety_relevant
        event.safety_class = safety_class
        event.requires_immediate_response = requires_immediate
        event.gesture_duration_sec = 0.0  # populated by is_held tracking
        event.is_held = is_held
        event.just_started = just_started
        event.just_ended = just_ended
        event.backend_used = self._config.backend

        self._pub_events.publish(event)
        self._health.record_gesture_published()

        self.get_logger().debug(
            f"GestureEvent: person={event.person_id} gesture={smoothed_gesture} "
            f"conf={smoothed_conf:.2f} safety={safety_class}"
        )

        # Diagnostics
        diag = {
            "event": "gesture_published",
            "event_id": event.event_id,
            "person_id": event.person_id,
            "gesture_type": smoothed_gesture,
            "confidence": round(float(smoothed_conf), 3),
            "safety_relevant": safety_relevant,
            "safety_class": safety_class,
            "requires_immediate": requires_immediate,
            "backend": self._config.backend,
        }
        self._pub_diag.publish(String(data=json.dumps(diag)))

    # ------------------------------------------------------------------
    # Service callbacks
    # ------------------------------------------------------------------

    def _srv_health_check(self, request: HealthCheck.Request, response: HealthCheck.Response) -> HealthCheck.Response:
        """Handle /bonbon/gesture/health_check service calls.

        Args:
            request: Service request (module_name field).
            response: Service response to populate.

        Returns:
            Populated HealthCheck.Response.
        """
        status = self._health.build_status_dict()
        response.healthy = status["healthy"]
        response.status = json.dumps(status)
        response.warnings = status["warnings"]
        response.errors = status["errors"]
        response.uptime_sec = status["uptime_sec"]
        return response

    def _srv_set_enabled_cb(self, request: SetMode.Request, response: SetMode.Response) -> SetMode.Response:
        """Handle /bonbon/gesture/set_enabled service calls.

        Interprets ``request.mode`` as ``'true'`` or ``'false'`` (case-insensitive)
        to enable or disable gesture processing.

        Args:
            request: SetMode request.
            response: SetMode response to populate.

        Returns:
            Populated SetMode.Response.
        """
        prev = "enabled" if self._config.enabled else "disabled"
        new_mode = request.mode.strip().lower()

        if new_mode in ("true", "1", "enabled", "on", "normal"):
            self._config.enabled = True
            self._health.set_enabled(True)
        elif new_mode in ("false", "0", "disabled", "off", "emergency"):
            self._config.enabled = False
            self._health.set_enabled(False)
        else:
            response.success = False
            response.error_message = f"Unknown mode '{request.mode}'. Use 'true' or 'false'."
            response.previous_mode = prev
            return response

        response.success = True
        response.previous_mode = prev
        response.error_message = ""
        self.get_logger().info(f"Gesture processing set to {self._config.enabled} by operator {request.operator_id!r}.")
        return response

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _declare_parameters(self) -> None:
        """Declare all ROS2 parameters with defaults."""
        defaults = GestureConfig()
        self.declare_parameter("backend", defaults.backend)
        self.declare_parameter("enabled", defaults.enabled)
        self.declare_parameter("confidence_threshold", defaults.confidence_threshold)
        self.declare_parameter("temporal_window", defaults.temporal_window)
        self.declare_parameter("gesture_cooldown_sec", defaults.gesture_cooldown_sec)
        self.declare_parameter("max_persons", defaults.max_persons)
        self.declare_parameter("frame_sample_rate", defaults.frame_sample_rate)
        self.declare_parameter("head_gesture_enabled", defaults.head_gesture_enabled)
        self.declare_parameter("hand_gesture_enabled", defaults.hand_gesture_enabled)
        self.declare_parameter("body_gesture_enabled", defaults.body_gesture_enabled)
        self.declare_parameter("safety_gesture_immediate", defaults.safety_gesture_immediate)
        self.declare_parameter("processing_timeout_sec", defaults.processing_timeout_sec)
        self.declare_parameter("min_visibility_threshold", defaults.min_visibility_threshold)

    def _create_backend(self, name: str) -> GestureBackendInterface:
        """Instantiate the requested backend.

        Args:
            name: Backend name string: ``'mediapipe'`` or ``'mock'``.

        Returns:
            An unwarmed :class:`GestureBackendInterface` instance.
        """
        if name == "mediapipe":
            return MediaPipeBackend(self._config)
        if name == "mock":
            return MockBackend(self._config, test_scenario=False)
        self.get_logger().warning(f"Unknown backend '{name}', defaulting to mock.")
        return MockBackend(self._config, test_scenario=False)

    def _ros_image_to_numpy(self, msg: Image) -> np.ndarray:
        """Convert a sensor_msgs/Image message to a BGR numpy array.

        Supports ``bgr8``, ``rgb8``, and ``mono8`` encodings.  Does not
        require cv_bridge as a runtime dependency.

        Args:
            msg: Incoming Image message.

        Returns:
            BGR uint8 numpy array with shape ``(height, width, 3)``.

        Raises:
            ValueError: When the image encoding is not supported.
        """
        import cv2  # noqa: PLC0415

        data = np.frombuffer(msg.data, dtype=np.uint8)

        if msg.encoding in ("bgr8", "rgb8"):
            img = data.reshape((msg.height, msg.width, 3))
            if msg.encoding == "rgb8":
                img = img[:, :, ::-1].copy()  # RGB → BGR
            else:
                img = img.copy()
        elif msg.encoding == "mono8":
            img = data.reshape((msg.height, msg.width))
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif msg.encoding in ("bayer_rggb8", "bayer_bggr8", "bayer_gbrg8", "bayer_grbg8"):
            img = data.reshape((msg.height, msg.width))
            img = cv2.cvtColor(img, cv2.COLOR_BayerBG2BGR)
        else:
            raise ValueError(f"Unsupported image encoding: {msg.encoding!r}")

        return img

    def _get_person_position(self, tracking_id: int) -> Point:
        """Look up the map-frame position for a person by tracking ID.

        Falls back to zero position when the person is not in the vision
        person-state cache.

        Args:
            tracking_id: Integer tracking identifier.

        Returns:
            geometry_msgs/Point in the map frame.
        """
        with self._lock:
            # Vision's track_id is a string like "person_3"
            key = f"person_{tracking_id}"
            pos = self._person_positions.get(key)
            if pos is not None:
                return pos
            # Also try integer key match fallback
            for pid, p in self._person_positions.items():
                if pid.endswith(str(tracking_id)):
                    return p
        return Point(x=0.0, y=0.0, z=0.0)

    def _publish_status(self) -> None:
        """Publish a periodic JSON health status message."""
        if self._health is None or self._pub_status is None:
            return
        status = self._health.build_status_dict()
        self._pub_status.publish(String(data=json.dumps(status)))

    def _shutdown_executor(self) -> None:
        """Safely shut down the ThreadPoolExecutor."""
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(args=None) -> None:
    """Start the GestureNode and spin until killed."""
    rclpy.init(args=args)
    node = GestureNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
