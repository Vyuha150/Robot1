"""
bonbon_vision.nodes.vision_node
=================================
CLASS-C IMPORTANT: Production vision pipeline LifecycleNode.

Full pipeline per detection cycle
----------------------------------
1. FrameThrottler         — drop frames above detection_rate_hz
2. FrameProcessor         — OpenCV CLAHE / denoise / resize / quality gate
3. BaseDetector.detect()  — YOLO (or mock) with timeout + degraded fallback
4. FacePipeline.run()     — face detection + InsightFace / DeepFace recognition
5. PrivacyGuard.anonymise()— blur faces in annotated image if privacy_enabled
6. PersonTracker.update() — IoU-based multi-person tracking
7. Publish DetectedObjectArray, PersonStateArray, optional annotated Image

Subscribed topics (HAL camera_node)
-------------------------------------
  /bonbon/vision/camera/color/image_raw   sensor_msgs/Image   BGR8  → detection
  /bonbon/vision/camera/depth/image_raw   sensor_msgs/Image   32FC1 → depth

Published topics
----------------
  /bonbon/vision/objects          bonbon_msgs/DetectedObjectArray  10 Hz
  /bonbon/vision/persons          bonbon_msgs/PersonStateArray     10 Hz
  /bonbon/vision/annotated_image  sensor_msgs/Image                10 Hz (optional)
  /bonbon/vision/vision_node/health  bonbon_msgs/ModuleHealth       1 Hz

Parameters (see VisionConfig.from_ros_params() for full list)
--------------------------------------------------------------
  detector_backend       "mock" | "yolo" | "hog"         default "mock"
  detector_model_path    str  (required when backend=yolo) default ""
  face_detect_backend    "mock" | "opencv_dnn" | "insightface"
  face_recognize_backend "mock" | "deepface" | "insightface"
  face_db_path           str                              default ""
  privacy_enabled        bool                             default False
  detection_rate_hz      float                            default 10.0
  publish_annotated      bool                             default False
  allow_degraded         bool                             default True
  … (full list in vision_params.yaml)

Thread safety
-------------
Color + depth image buffers are written by subscription callbacks and read by
the detection timer.  A threading.Lock protects both.  All heavy inference
work (detect, face pipeline) runs inside BaseDetector's ThreadPoolExecutor
so the ROS2 timer thread is never blocked longer than inference_timeout_sec.
"""

from __future__ import annotations

import math
import threading
import time

import numpy as np
import rclpy
from bonbon_msgs.msg import (
    DetectedObject as DetectedObjectMsg,
)
from bonbon_msgs.msg import (
    DetectedObjectArray as DetectedObjectArrayMsg,
)
from bonbon_msgs.msg import (
    ModuleHealth,
)
from bonbon_msgs.msg import (
    PersonState as PersonStateMsg,
)
from bonbon_msgs.msg import (
    PersonStateArray as PersonStateArrayMsg,
)
from geometry_msgs.msg import Point
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image

from ..config import VisionConfig
from ..detectors import DetectionResult, MockDetector, ObjectDetection
from ..face import FacePipeline, FaceResult, PrivacyGuard
from ..models import ModelManager, ModelState
from ..preprocessing import FrameProcessor, FrameThrottler

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

NODE_NAME = "vision_node"
HEALTH_TOPIC = "/bonbon/vision/vision_node/health"

# ── Lightweight IoU tracker (embedded — no bonbon_perception dep) ─────────────


class _Track:
    __slots__ = (
        "track_id",
        "bbox",
        "cx",
        "cy",
        "distance_m",
        "bearing_deg",
        "velocity_mps",
        "face_id",
        "age_group",
        "facing_robot",
        "hit_streak",
        "lost_count",
        "age_frames",
        "alpha",
    )

    def __init__(self, track_id: str, det: ObjectDetection) -> None:
        self.track_id = track_id
        self.bbox = det.bbox
        self.cx, self.cy = det.centre_px
        self.distance_m = det.depth_m
        self.bearing_deg = det.bearing_deg
        self.velocity_mps = 0.0
        self.face_id = ""
        self.age_group = "unknown"
        self.facing_robot = False
        self.hit_streak = 1
        self.lost_count = 0
        self.age_frames = 1
        self.alpha = 0.4

    def update(self, det: ObjectDetection) -> None:
        ncx, ncy = det.centre_px
        a = self.alpha
        self.cx = a * ncx + (1 - a) * self.cx
        self.cy = a * ncy + (1 - a) * self.cy
        if math.isfinite(det.depth_m):
            old = self.distance_m if math.isfinite(self.distance_m) else det.depth_m
            self.distance_m = a * det.depth_m + (1 - a) * old
        self.bearing_deg = a * det.bearing_deg + (1 - a) * self.bearing_deg
        self.bbox = det.bbox
        self.hit_streak += 1
        self.lost_count = 0
        self.age_frames += 1

    def mark_lost(self) -> None:
        self.lost_count += 1
        self.hit_streak = 0
        self.age_frames += 1

    @property
    def confirmed(self) -> bool:
        return self.hit_streak >= 2 or self.age_frames >= 2


def _iou(a_bbox: tuple, b_bbox: tuple) -> float:
    ax, ay, aw, ah = a_bbox
    bx, by, bw, bh = b_bbox
    ix = max(ax, bx)
    iy = max(ay, by)
    iw = max(0, min(ax + aw, bx + bw) - ix)
    ih = max(0, min(ay + ah, by + bh) - iy)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


class _SimpleTracker:
    def __init__(self, iou_thresh: float = 0.3, max_lost: int = 15, max_tracks: int = 20) -> None:
        self._iou = iou_thresh
        self._max_lost = max_lost
        self._max_tracks = max_tracks
        self._tracks: dict[str, _Track] = {}
        self._next_id = 0

    def update(self, detections: list[ObjectDetection]) -> list[_Track]:
        active = list(self._tracks.values())
        matched_t, matched_d = self._assign(active, detections)
        for tid, di in zip(matched_t, matched_d):
            self._tracks[tid].update(detections[di])
        for t in active:
            if t.track_id not in set(matched_t):
                t.mark_lost()
        matched_di = set(matched_d)
        for i, det in enumerate(detections):
            if i not in matched_di and len(self._tracks) < self._max_tracks:
                tid = f"person_{self._next_id}"
                self._next_id += 1
                self._tracks[tid] = _Track(tid, det)
        dead = [tid for tid, t in self._tracks.items() if t.lost_count > self._max_lost]
        for tid in dead:
            del self._tracks[tid]
        return [t for t in self._tracks.values() if t.confirmed]

    def reset(self) -> None:
        self._tracks.clear()
        self._next_id = 0

    def _assign(self, tracks, dets) -> tuple[list[str], list[int]]:
        if not tracks or not dets:
            return [], []
        n_t, n_d = len(tracks), len(dets)
        cost = np.ones((n_t, n_d))
        for i, t in enumerate(tracks):
            for j, d in enumerate(dets):
                cost[i, j] = 1.0 - _iou(t.bbox, d.bbox)
        matched_t, matched_d, used_t, used_d = [], [], set(), set()
        for idx in np.argsort(cost.ravel()):
            i, j = divmod(int(idx), n_d)
            if i in used_t or j in used_d:
                continue
            if cost[i, j] > 1.0 - self._iou:
                break
            matched_t.append(tracks[i].track_id)
            matched_d.append(j)
            used_t.add(i)
            used_d.add(j)
        return matched_t, matched_d


# ── VisionNode ────────────────────────────────────────────────────────────────


class VisionNode(LifecycleNode):
    """
    Production-grade vision pipeline — all camera intelligence in one node.
    """

    def __init__(self) -> None:
        super().__init__(NODE_NAME)
        self._lock = threading.Lock()

        # Frame buffers (written by sub callbacks, read by detection timer)
        self._latest_color: np.ndarray | None = None
        self._latest_depth: np.ndarray | None = None
        self._color_stamp = None
        self._color_frame_id: str = "camera_color_optical_frame"
        self._color_seq: int = 0
        self._frames_received: int = 0

        # Pipeline objects (created in on_configure)
        self._cfg: VisionConfig | None = None
        self._processor: FrameProcessor | None = None
        self._throttler: FrameThrottler | None = None
        self._detector = None
        self._face_pipe: FacePipeline | None = None
        self._privacy: PrivacyGuard | None = None
        self._tracker: _SimpleTracker | None = None
        self._model_mgr: ModelManager | None = None

        # Timers / publishers
        self._detect_timer = None
        self._health_timer = None
        self._pub_objects = None
        self._pub_persons = None
        self._pub_annotated = None
        self._pub_health = None

        # Runtime counters (for health)
        self._start_time = time.monotonic()
        self._processed: int = 0
        self._errors: int = 0
        self._warnings: int = 0
        self._last_inf_ms: float = 0.0
        self._frames_skipped_quality: int = 0
        self._frames_throttled: int = 0

        self._declare_parameters()
        self.get_logger().info(f"[{NODE_NAME}] created — awaiting configure()")

    # ── Parameter declarations ────────────────────────────────────────────────

    def _declare_parameters(self) -> None:
        # Detector
        self.declare_parameter("detector_backend", "mock")
        self.declare_parameter("detector_model_path", "")
        self.declare_parameter("detector_confidence", 0.45)
        self.declare_parameter("detector_nms_iou", 0.45)
        self.declare_parameter("detector_device", "")
        self.declare_parameter("detector_img_size", 640)
        self.declare_parameter("detector_timeout_sec", 1.0)
        self.declare_parameter("detector_max_timeouts", 3)
        self.declare_parameter("detector_half", False)
        # Face
        self.declare_parameter("face_detect_backend", "mock")
        self.declare_parameter("face_recognize_backend", "mock")
        self.declare_parameter("face_db_path", "")
        self.declare_parameter("face_recognition_threshold", 0.40)
        self.declare_parameter("face_dnn_prototxt_path", "")
        self.declare_parameter("face_dnn_weights_path", "")
        self.declare_parameter("face_timeout_sec", 0.5)
        self.declare_parameter("face_min_confidence", 0.70)
        # Preprocessing
        self.declare_parameter("preprocess_width", 640)
        self.declare_parameter("preprocess_height", 480)
        self.declare_parameter("preprocess_clahe", True)
        self.declare_parameter("preprocess_clahe_clip", 2.0)
        self.declare_parameter("preprocess_denoise", False)
        self.declare_parameter("preprocess_brightness_threshold", 50.0)
        # Privacy
        self.declare_parameter("privacy_enabled", False)
        self.declare_parameter("privacy_blur_faces", True)
        self.declare_parameter("privacy_blur_kernel", 51)
        self.declare_parameter("privacy_pixelate", False)
        self.declare_parameter("privacy_suppress_id", True)
        self.declare_parameter("privacy_disable_annotated", False)
        # Tracking
        self.declare_parameter("tracking_iou_threshold", 0.30)
        self.declare_parameter("tracking_max_lost", 15)
        self.declare_parameter("tracking_max_tracks", 20)
        # Top-level
        self.declare_parameter("detection_rate_hz", 10.0)
        self.declare_parameter("health_rate_hz", 1.0)
        self.declare_parameter("hfov_deg", 60.0)
        self.declare_parameter("publish_annotated", False)
        self.declare_parameter("allow_degraded", True)

    # ── Lifecycle transitions ─────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info(f"[{NODE_NAME}] Configuring…")
        try:
            self._cfg = VisionConfig.from_ros_params(self)
            self._cfg.validate()
        except Exception as exc:
            self.get_logger().error(f"[{NODE_NAME}] Config validation failed: {exc}")
            return TransitionCallbackReturn.FAILURE

        self.get_logger().info(f"[{NODE_NAME}] config summary: {self._cfg.summary()}")

        # Preprocessing
        self._processor = FrameProcessor(self._cfg.preprocess)
        self._throttler = FrameThrottler(self._cfg.detection_rate_hz)

        # Object detector
        self._detector = self._build_detector()

        # Model manager (async load so configure() returns immediately)
        self._model_mgr = ModelManager(
            self._detector,
            allow_degraded=self._cfg.allow_degraded_startup,
        )
        self._model_mgr.load_async()

        # Face pipeline
        self._face_pipe = FacePipeline(
            self._cfg.face,
            privacy_mode=self._cfg.privacy.enabled and self._cfg.privacy.suppress_identity,
        )

        # Privacy guard
        self._privacy = PrivacyGuard(self._cfg.privacy)

        # Tracker
        t = self._cfg.tracking
        self._tracker = _SimpleTracker(
            iou_thresh=t.iou_threshold,
            max_lost=t.max_lost_frames,
            max_tracks=t.max_tracks,
        )

        self.get_logger().info(f"[{NODE_NAME}] Configured — model loading async")
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info(f"[{NODE_NAME}] Activating…")

        # Publishers
        self._pub_objects = self.create_lifecycle_publisher(
            DetectedObjectArrayMsg, "/bonbon/vision/objects", RELIABLE_D5
        )
        self._pub_persons = self.create_lifecycle_publisher(
            PersonStateArrayMsg, "/bonbon/vision/persons", RELIABLE_D5
        )
        self._pub_health = self.create_lifecycle_publisher(ModuleHealth, HEALTH_TOPIC, RELIABLE_TL)
        if self._cfg.publish_annotated_image and not self._cfg.privacy.disable_annotated_publish:
            self._pub_annotated = self.create_lifecycle_publisher(
                Image, "/bonbon/vision/annotated_image", BEST_EFFORT_D2
            )

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

        # Timers
        det_period = 1.0 / max(1.0, self._cfg.detection_rate_hz)
        self._detect_timer = self.create_timer(det_period, self._detection_cycle)

        health_period = 1.0 / max(0.1, self._cfg.health_rate_hz)
        self._health_timer = self.create_timer(health_period, self._publish_health)

        self.get_logger().info(
            f"[{NODE_NAME}] Active — "
            f"rate={self._cfg.detection_rate_hz}Hz "
            f"privacy={self._cfg.privacy.enabled}"
        )
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info(f"[{NODE_NAME}] Deactivating")
        for timer in (self._detect_timer, self._health_timer):
            if timer:
                timer.cancel()
        self._detect_timer = self._health_timer = None
        # Publish empty arrays to signal no detections
        if self._pub_objects:
            self._pub_objects.publish(DetectedObjectArrayMsg())
        if self._pub_persons:
            self._pub_persons.publish(PersonStateArrayMsg())
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info(f"[{NODE_NAME}] Cleanup")
        if self._tracker:
            self._tracker.reset()
        if self._face_pipe:
            self._face_pipe.shutdown()
        if self._detector:
            self._detector.shutdown()
        with self._lock:
            self._latest_color = None
            self._latest_depth = None
        self._pub_objects = self._pub_persons = self._pub_health = None
        self._pub_annotated = None
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info(f"[{NODE_NAME}] Shutdown")
        if self._face_pipe:
            self._face_pipe.shutdown()
        if self._detector:
            self._detector.shutdown()
        return TransitionCallbackReturn.SUCCESS

    # ── Image callbacks ───────────────────────────────────────────────────────

    def _on_color_image(self, msg: Image) -> None:
        try:
            arr = self._decode_color(msg)
            with self._lock:
                self._latest_color = arr
                self._color_stamp = msg.header.stamp
                self._color_frame_id = msg.header.frame_id
                self._frames_received += 1
        except Exception as exc:
            self._errors += 1
            self.get_logger().debug(f"[{NODE_NAME}] color decode error: {exc}")

    def _on_depth_image(self, msg: Image) -> None:
        try:
            arr = self._decode_depth(msg)
            with self._lock:
                self._latest_depth = arr
        except Exception as exc:
            self._errors += 1
            self.get_logger().debug(f"[{NODE_NAME}] depth decode error: {exc}")

    # ── Detection cycle ───────────────────────────────────────────────────────

    def _detection_cycle(self) -> None:
        # 1. Check model readiness
        if self._model_mgr and self._model_mgr.state == ModelState.LOADING:
            return  # still loading — skip this cycle silently

        # 2. Frame throttle
        if not self._throttler.should_process():
            self._frames_throttled += 1
            return

        # 3. Grab latest frame (non-blocking)
        with self._lock:
            color = self._latest_color
            depth = self._latest_depth
            stamp = self._color_stamp
            frame_id = self._color_frame_id

        if color is None:
            return

        t_cycle = time.monotonic()

        # 4. Preprocess
        pf = self._processor.process(color, depth)
        if not pf.is_usable:
            self._frames_skipped_quality += 1
            self.get_logger().debug(f"[{NODE_NAME}] frame quality={pf.quality.name} — skipping")
            return

        # 5. Object detection
        det_result: DetectionResult = self._detector.detect(pf.bgr, pf.depth_m)
        self._last_inf_ms = det_result.inference_ms

        # 6. Face pipeline (only on person detections to save CPU)
        person_dets = [d for d in det_result.detections if d.is_person]
        face_result: FaceResult = FaceResult()
        if person_dets:
            face_result = self._face_pipe.run(pf.bgr)

        # 7. Tracker update (persons only)
        confirmed_tracks = self._tracker.update(person_dets) if person_dets else []

        # Associate face IDs to closest track by geometry
        self._fuse_face_ids(confirmed_tracks, face_result)

        # 8. Privacy: build annotated image (copy) with blurred faces
        annotated: np.ndarray | None = None
        if self._pub_annotated is not None:
            face_bboxes = [f.bbox for f in face_result.faces]
            annotated = self._privacy.anonymise(pf.bgr.copy(), face_bboxes)

        # 9. Publish
        now_stamp = stamp or self.get_clock().now().to_msg()
        self._publish_objects(det_result, now_stamp, frame_id, pf)
        self._publish_persons(confirmed_tracks, face_result, now_stamp, frame_id)
        if annotated is not None:
            self._publish_annotated(annotated, now_stamp, frame_id)

        self._processed += 1
        total_ms = (time.monotonic() - t_cycle) * 1000
        self.get_logger().debug(
            f"[{NODE_NAME}] cycle_ms={total_ms:.1f} "
            f"objects={len(det_result.detections)} "
            f"persons={len(confirmed_tracks)} "
            f"faces={len(face_result.faces)} "
            f"low_light={pf.is_low_light} "
            f"degraded={det_result.is_degraded}"
        )

    # ── Publishers ────────────────────────────────────────────────────────────

    def _publish_objects(
        self,
        result: DetectionResult,
        stamp,
        frame_id: str,
        pf,
    ) -> None:
        if self._pub_objects is None:
            return
        msg = DetectedObjectArrayMsg()
        msg.header.stamp = stamp
        msg.header.frame_id = frame_id
        msg.is_degraded = result.is_degraded
        msg.privacy_mode_active = self._cfg.privacy.enabled
        msg.inference_ms = result.inference_ms
        msg.detector_backend = result.backend
        msg.total_count = len(result.detections)

        for od in result.detections:
            obj = DetectedObjectMsg()
            obj.class_id = od.class_id
            obj.class_name = od.class_name
            obj.confidence = od.confidence
            obj.bbox_x, obj.bbox_y, obj.bbox_w, obj.bbox_h = od.bbox
            obj.depth_m = od.depth_m if math.isfinite(od.depth_m) else -1.0
            obj.bearing_deg = od.bearing_deg
            obj.track_id = od.track_id
            obj.is_anonymized = self._cfg.privacy.enabled and od.is_person
            msg.objects.append(obj)

        self._pub_objects.publish(msg)

    def _publish_persons(
        self,
        tracks: list,
        face_result: FaceResult,
        stamp,
        frame_id: str,
    ) -> None:
        if self._pub_persons is None:
            return
        msg = PersonStateArrayMsg()
        msg.header.stamp = stamp
        msg.header.frame_id = frame_id
        msg.total_count = len(tracks)

        suppress_id = self._cfg.privacy.enabled and self._cfg.privacy.suppress_identity

        for track in tracks:
            ps = PersonStateMsg()
            ps.track_id = track.track_id
            ps.face_id = "" if suppress_id else track.face_id
            ps.distance_m = float(track.distance_m) if math.isfinite(track.distance_m) else 0.0
            ps.bearing_deg = float(track.bearing_deg)
            ps.velocity_mps = float(track.velocity_mps)
            ps.facing_robot = track.facing_robot
            ps.age_group = track.age_group
            br = math.radians(track.bearing_deg)
            d = ps.distance_m
            ps.position = Point(x=d * math.sin(br), y=d * math.cos(br), z=0.0)
            msg.persons.append(ps)

        self._pub_persons.publish(msg)

    def _publish_annotated(self, bgr: np.ndarray, stamp, frame_id: str) -> None:
        if self._pub_annotated is None:
            return
        msg = Image()
        msg.header.stamp = stamp
        msg.header.frame_id = frame_id
        msg.height = bgr.shape[0]
        msg.width = bgr.shape[1]
        msg.encoding = "bgr8"
        msg.step = bgr.shape[1] * 3
        msg.data = bgr.tobytes()
        self._pub_annotated.publish(msg)

    def _publish_health(self) -> None:
        if self._pub_health is None:
            return
        uptime = time.monotonic() - self._start_time
        degraded = self._detector and self._detector.is_degraded
        model_state = self._model_mgr.state.name if self._model_mgr else "N/A"

        if self._errors > 20 or degraded:
            status = ModuleHealth.ERROR
        elif self._warnings > 10 or self._frames_skipped_quality > 50:
            status = ModuleHealth.WARN
        else:
            status = ModuleHealth.OK

        status_txt = (
            f"model={model_state} degraded={degraded} "
            f"processed={self._processed} "
            f"errors={self._errors} "
            f"quality_drops={self._frames_skipped_quality} "
            f"inf_ms={self._last_inf_ms:.1f} "
            f"privacy={self._cfg.privacy.enabled if self._cfg else False}"
        )

        msg = ModuleHealth()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.module_name = NODE_NAME
        msg.status = status
        msg.status_text = status_txt
        msg.uptime_sec = uptime
        msg.last_successful_cycle_sec = 0.0
        msg.latency_ms = self._last_inf_ms
        msg.error_count = self._errors
        msg.warning_count = self._warnings
        msg.processed_count = self._processed
        self._pub_health.publish(msg)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _fuse_face_ids(self, tracks: list, face_result: FaceResult) -> None:
        """
        Assign face_id from the nearest detected face to each confirmed track.
        Uses simple Euclidean centre distance for assignment.
        """
        if not face_result.faces or not tracks:
            return
        for track in tracks:
            best_face, best_dist = None, float("inf")
            for face in face_result.faces:
                fx = face.bbox[0] + face.bbox[2] / 2
                fy = face.bbox[1] + face.bbox[3] / 2
                dist = math.hypot(fx - track.cx, fy - track.cy)
                if dist < best_dist:
                    best_dist, best_face = dist, face
            if best_face and best_dist < 200:  # 200 px proximity threshold
                track.face_id = best_face.face_id
                track.facing_robot = best_face.facing_robot
                track.age_group = best_face.age_group

    def _build_detector(self):
        backend = self._cfg.detector.backend
        if backend == "yolo":
            try:
                from ..detectors.yolo_detector import YoloDetector

                return YoloDetector(self._cfg.detector, self._cfg.hfov_deg)
            except ImportError:
                self.get_logger().warning(f"[{NODE_NAME}] YOLO unavailable — falling back to mock")
                return MockDetector(self._cfg.detector, self._cfg.hfov_deg)
        elif backend == "mock":
            return MockDetector(self._cfg.detector, self._cfg.hfov_deg)
        else:
            self.get_logger().warning(f"[{NODE_NAME}] Unknown backend '{backend}' — using mock")
            return MockDetector(self._cfg.detector, self._cfg.hfov_deg)

    # ── Image decode (no cv_bridge required) ─────────────────────────────────

    @staticmethod
    def _decode_color(msg: Image) -> np.ndarray:
        h, w = msg.height, msg.width
        raw = np.frombuffer(msg.data, dtype=np.uint8)
        if msg.encoding in ("bgr8", "8UC3"):
            return raw.reshape((h, w, 3)).copy()
        elif msg.encoding == "rgb8":
            return raw.reshape((h, w, 3))[:, :, ::-1].copy()
        else:
            return raw.reshape((h, w, -1)).copy()

    @staticmethod
    def _decode_depth(msg: Image) -> np.ndarray:
        h, w = msg.height, msg.width
        if msg.encoding == "32FC1":
            return np.frombuffer(msg.data, dtype=np.float32).reshape((h, w)).copy()
        elif msg.encoding in ("16UC1", "mono16"):
            return (
                np.frombuffer(msg.data, dtype=np.uint16).reshape((h, w)).astype(np.float32) / 1000.0
            )
        raise ValueError(f"Unsupported depth encoding: {msg.encoding!r}")


# ── Entry point ───────────────────────────────────────────────────────────────


def main(args=None) -> None:
    rclpy.init(args=args)
    node = VisionNode()
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
