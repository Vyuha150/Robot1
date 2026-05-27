"""
bonbon_perception.nodes.detection_node
=======================================
CLASS-C IMPORTANT: Person detection and tracking node.

Subscribes (from HAL camera_node)
----------------------------------
  /bonbon/vision/camera/color/image_raw   sensor_msgs/Image   BGR8
  /bonbon/vision/camera/depth/image_raw   sensor_msgs/Image   32FC1 (metres)

Publishes
---------
  /bonbon/vision/persons                  bonbon_msgs/PersonStateArray  10 Hz
  /bonbon/vision/detection_node/health    bonbon_msgs/ModuleHealth       1 Hz

Parameters
----------
  detector_mode         str   "mock"|"hog"|"yolo"   default "mock"
  model_path            str   path to YOLO model     default "yolov8n.pt"
  confidence_threshold  float                        default 0.50
  hfov_deg              float camera HFOV in degrees default 60.0
  detection_rate_hz     float run detector at Hz     default 10.0
  health_rate_hz        float                        default 1.0
  iou_threshold         float tracker IoU match      default 0.30
  max_lost_frames       int   before track deleted   default 15
  publish_all_states    bool  publish TENTATIVE too? default false

Lifecycle
---------
  configure → load params, instantiate detector + tracker
  activate  → subscribe to image topics, start timers, publish health
  deactivate → cancel timers, destroy subs
  cleanup   → reset tracker, release resources

Thread safety
-------------
The node uses a threading.Lock to protect the image buffer that is written
by the ROS2 subscription callback and read by the 10 Hz detect-and-publish
timer.  Both callbacks run in a MultiThreadedExecutor (2 threads).
"""

from __future__ import annotations

import math
import threading
import time

import numpy as np
import rclpy
from bonbon_msgs.msg import (
    ModuleHealth,
)
from bonbon_msgs.msg import (
    PersonState as PersonStateMsg,
)
from bonbon_msgs.msg import (
    PersonStateArray as PersonStateArrayMsg,
)
from builtin_interfaces.msg import Time
from geometry_msgs.msg import Point
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image

from ..detectors import MockPersonDetector
from ..trackers import SimpleTracker, Track

# ── QoS profiles ──────────────────────────────────────────────────────────────

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
BEST_EFFORT_D2 = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    history=HistoryPolicy.KEEP_LAST,
    depth=2,
)

NODE_NAME = "detection_node"
HEALTH_TOPIC = "/bonbon/vision/detection_node/health"


class DetectionNode(LifecycleNode):
    """
    Person detection and multi-person tracking lifecycle node.

    Runs the selected detector on the latest color+depth frame at
    detection_rate_hz.  Outputs confirmed tracks as PersonStateArray.
    """

    def __init__(self) -> None:
        super().__init__(NODE_NAME)
        self._lock = threading.Lock()

        # Image buffers (latest received, protected by _lock)
        self._latest_color: np.ndarray | None = None
        self._latest_depth: np.ndarray | None = None
        self._color_stamp: Time | None = None
        self._color_frame_id: str = "camera_color_optical_frame"

        # Core objects (created in on_configure)
        self._detector = None
        self._tracker: SimpleTracker | None = None

        # Publishers / timers (created in on_activate)
        self._pub_persons = None
        self._pub_health = None
        self._detect_timer = None
        self._health_timer = None

        # Runtime counters
        self._start_time = time.monotonic()
        self._processed_count: int = 0
        self._error_count: int = 0
        self._last_latency_ms: float = 0.0

        self._declare_parameters()
        self.get_logger().info(f"[{NODE_NAME}] created — awaiting configure()")

    # ── Parameter declarations ────────────────────────────────────────────────

    def _declare_parameters(self) -> None:
        self.declare_parameter("detector_mode", "mock")
        self.declare_parameter("model_path", "yolov8n.pt")
        self.declare_parameter("confidence_threshold", 0.50)
        self.declare_parameter("hfov_deg", 60.0)
        self.declare_parameter("detection_rate_hz", 10.0)
        self.declare_parameter("health_rate_hz", 1.0)
        self.declare_parameter("iou_threshold", 0.30)
        self.declare_parameter("max_lost_frames", 15)
        self.declare_parameter("publish_all_states", False)
        # Mock-specific
        self.declare_parameter("mock_num_persons", 1)
        self.declare_parameter("mock_base_distance_m", 2.0)

    # ── Lifecycle transitions ─────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info(f"[{NODE_NAME}] Configuring…")
        try:
            mode = self.get_parameter("detector_mode").value
            conf_thresh = self.get_parameter("confidence_threshold").value
            hfov = self.get_parameter("hfov_deg").value
            iou_thresh = self.get_parameter("iou_threshold").value
            max_lost = int(self.get_parameter("max_lost_frames").value)

            self._detector = self._make_detector(mode, conf_thresh, hfov)
            self._tracker = SimpleTracker(
                iou_threshold=iou_thresh,
                max_lost_frames=max_lost,
            )
        except Exception as exc:
            self.get_logger().error(f"[{NODE_NAME}] Configure failed: {exc}")
            return TransitionCallbackReturn.FAILURE

        self.get_logger().info(
            f"[{NODE_NAME}] Configured — detector={self.get_parameter('detector_mode').value}"
        )
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info(f"[{NODE_NAME}] Activating…")

        # Publishers
        self._pub_persons = self.create_lifecycle_publisher(
            PersonStateArrayMsg, "/bonbon/vision/persons", RELIABLE_D5
        )
        self._pub_health = self.create_lifecycle_publisher(ModuleHealth, HEALTH_TOPIC, RELIABLE_TL)

        # Subscriptions
        self._sub_color = self.create_subscription(
            Image,
            "/bonbon/vision/camera/color/image_raw",
            self._on_color_image,
            BEST_EFFORT_D2,
        )
        self._sub_depth = self.create_subscription(
            Image,
            "/bonbon/vision/camera/depth/image_raw",
            self._on_depth_image,
            BEST_EFFORT_D2,
        )

        # Detection timer
        detect_period = 1.0 / max(1.0, self.get_parameter("detection_rate_hz").value)
        self._detect_timer = self.create_timer(detect_period, self._detect_and_publish)

        # Health timer
        health_period = 1.0 / max(0.1, self.get_parameter("health_rate_hz").value)
        self._health_timer = self.create_timer(health_period, self._publish_health)

        self.get_logger().info(f"[{NODE_NAME}] Active")
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info(f"[{NODE_NAME}] Deactivating")
        if self._detect_timer:
            self._detect_timer.cancel()
            self._detect_timer = None
        if self._health_timer:
            self._health_timer.cancel()
            self._health_timer = None
        # Publish empty array to signal no tracked persons
        if self._pub_persons:
            self._pub_persons.publish(PersonStateArrayMsg())
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info(f"[{NODE_NAME}] Cleanup")
        if self._tracker:
            self._tracker.reset()
        with self._lock:
            self._latest_color = None
            self._latest_depth = None
        self._pub_persons = None
        self._pub_health = None
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info(f"[{NODE_NAME}] Shutdown")
        return TransitionCallbackReturn.SUCCESS

    # ── Image subscribers ─────────────────────────────────────────────────────

    def _on_color_image(self, msg: Image) -> None:
        try:
            arr = self._image_msg_to_bgr(msg)
            with self._lock:
                self._latest_color = arr
                self._color_stamp = msg.header.stamp
                self._color_frame_id = msg.header.frame_id
        except Exception as exc:
            self._error_count += 1
            self.get_logger().warn(f"[{NODE_NAME}] Color image decode error: {exc}")

    def _on_depth_image(self, msg: Image) -> None:
        try:
            arr = self._depth_msg_to_float32(msg)
            with self._lock:
                self._latest_depth = arr
        except Exception as exc:
            self._error_count += 1
            self.get_logger().warn(f"[{NODE_NAME}] Depth image decode error: {exc}")

    # ── Detection cycle ───────────────────────────────────────────────────────

    def _detect_and_publish(self) -> None:
        with self._lock:
            color = self._latest_color
            depth = self._latest_depth
            stamp = self._color_stamp
            frame = self._color_frame_id

        if color is None:
            return

        t0 = time.monotonic()
        try:
            detections = self._detector.detect(color, depth)
        except Exception as exc:
            self._error_count += 1
            self.get_logger().warn(f"[{NODE_NAME}] Detector error: {exc}")
            return

        try:
            confirmed_tracks = self._tracker.update(detections)
        except Exception as exc:
            self._error_count += 1
            self.get_logger().warn(f"[{NODE_NAME}] Tracker error: {exc}")
            return

        self._last_latency_ms = (time.monotonic() - t0) * 1000.0
        self._processed_count += 1

        self._publish_persons(confirmed_tracks, stamp, frame)

    def _publish_persons(
        self,
        tracks: list[Track],
        stamp: Time | None,
        frame_id: str,
    ) -> None:
        if self._pub_persons is None:
            return

        msg = PersonStateArrayMsg()
        msg.header.stamp = stamp or self.get_clock().now().to_msg()
        msg.header.frame_id = frame_id
        msg.total_count = len(tracks)

        for track in tracks:
            ps = PersonStateMsg()
            ps.track_id = track.track_id
            ps.face_id = track.face_id
            ps.distance_m = float(track.distance_m) if math.isfinite(track.distance_m) else 0.0
            ps.bearing_deg = float(track.bearing_deg)
            ps.velocity_mps = float(track.velocity_mps)
            ps.facing_robot = track.facing_robot
            ps.age_group = track.age_group

            # 3D position (x = lateral from bearing + distance, y = depth)
            bearing_rad = math.radians(track.bearing_deg)
            d = ps.distance_m
            ps.position = Point(
                x=d * math.sin(bearing_rad),
                y=d * math.cos(bearing_rad),
                z=0.0,
            )
            msg.persons.append(ps)

        self._pub_persons.publish(msg)

    # ── Health publishing ─────────────────────────────────────────────────────

    def _publish_health(self) -> None:
        if self._pub_health is None:
            return

        uptime = time.monotonic() - self._start_time
        n_tracked = len(self._tracker.confirmed_tracks) if self._tracker else 0

        if self._error_count > 10:
            status = ModuleHealth.ERROR
            status_txt = f"High error count: {self._error_count}"
        else:
            status = ModuleHealth.OK
            status_txt = f"Tracking {n_tracked} persons. " f"Latency {self._last_latency_ms:.1f} ms"

        msg = ModuleHealth()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.module_name = NODE_NAME
        msg.status = status
        msg.status_text = status_txt
        msg.uptime_sec = uptime
        msg.last_successful_cycle_sec = 0.0
        msg.latency_ms = self._last_latency_ms
        msg.error_count = self._error_count
        msg.warning_count = 0
        msg.processed_count = self._processed_count
        self._pub_health.publish(msg)

    # ── Detector factory ──────────────────────────────────────────────────────

    def _make_detector(self, mode: str, conf: float, hfov: float):
        if mode == "mock":
            n = int(self.get_parameter("mock_num_persons").value)
            dist = float(self.get_parameter("mock_base_distance_m").value)
            return MockPersonDetector(
                num_persons=n,
                base_distance_m=dist,
                confidence=conf,
                hfov_deg=hfov,
            )
        elif mode == "hog":
            try:
                from ..detectors.hog_person_detector import HogPersonDetector

                return HogPersonDetector(
                    confidence_threshold=conf,
                    hfov_deg=hfov,
                )
            except ImportError as exc:
                self.get_logger().warn(
                    f"[{NODE_NAME}] HOG unavailable ({exc}), falling back to mock"
                )
                return MockPersonDetector(confidence=conf, hfov_deg=hfov)
        elif mode == "yolo":
            try:
                from ..detectors.yolo_person_detector import YoloPersonDetector

                model = self.get_parameter("model_path").value
                return YoloPersonDetector(
                    model_path=model,
                    confidence_threshold=conf,
                    hfov_deg=hfov,
                )
            except ImportError as exc:
                self.get_logger().warn(
                    f"[{NODE_NAME}] YOLO unavailable ({exc}), falling back to mock"
                )
                return MockPersonDetector(confidence=conf, hfov_deg=hfov)
        else:
            self.get_logger().warn(f"[{NODE_NAME}] Unknown detector_mode '{mode}' — using mock")
            return MockPersonDetector(confidence=conf, hfov_deg=hfov)

    # ── Image conversion utilities ────────────────────────────────────────────

    @staticmethod
    def _image_msg_to_bgr(msg: Image) -> np.ndarray:
        """Convert sensor_msgs/Image (bgr8 or rgb8) to HxWx3 uint8 BGR array."""
        h, w = msg.height, msg.width
        data = np.frombuffer(msg.data, dtype=np.uint8).reshape((h, w, -1))
        if msg.encoding == "rgb8":
            return data[:, :, ::-1].copy()  # RGB → BGR
        elif msg.encoding in ("bgr8", "8UC3"):
            return data.copy()
        else:
            # Try to use cv2 bridge; fall back to raw copy
            try:
                import cv2

                arr = np.frombuffer(msg.data, dtype=np.uint8).reshape((h, w, -1))
                if msg.encoding == "mono8":
                    return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
            except Exception:
                pass
            return np.frombuffer(msg.data, dtype=np.uint8).reshape((h, w, -1))

    @staticmethod
    def _depth_msg_to_float32(msg: Image) -> np.ndarray:
        """
        Convert sensor_msgs/Image depth to float32 array in metres.
        Supports 32FC1 (metres) and 16UC1 (millimetres → metres).
        """
        h, w = msg.height, msg.width
        if msg.encoding == "32FC1":
            arr = np.frombuffer(msg.data, dtype=np.float32).reshape((h, w))
            return arr.copy()
        elif msg.encoding in ("16UC1", "mono16"):
            arr = np.frombuffer(msg.data, dtype=np.uint16).reshape((h, w))
            return arr.astype(np.float32) / 1000.0  # mm → m
        else:
            raise ValueError(f"Unsupported depth encoding: {msg.encoding!r}")


# ── Entry point ───────────────────────────────────────────────────────────────


def main(args=None) -> None:
    rclpy.init(args=args)
    node = DetectionNode()
    executor = rclpy.executors.MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
