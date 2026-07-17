"""ObjectIntelligenceNode — object permanence + calibration LifecycleNode.

Consumes (does not redetect):
    /bonbon/vision/objects   (bonbon_msgs/DetectedObjectArray)  @ ~10 Hz
    /bonbon/safety/state     (bonbon_msgs/SafetyState)

Publishes:
    /bonbon/objects/tracked                                (bonbon_msgs/TrackedObject)
    /bonbon/objects/object_intelligence_node/health         (bonbon_msgs/ModuleHealth)

Failure handling:
    If /bonbon/vision/objects goes stale (no message within
    vision_stale_timeout_sec), this cycle is treated as "no detections" so
    objects correctly age toward occluded/memory/lost rather than appearing
    falsely visible forever off a frozen frame.
"""

from __future__ import annotations

import json
import math
import time

import rclpy
from bonbon_msgs.msg import DetectedObjectArray, ModuleHealth, SafetyState, TrackedObject
from bonbon_srvs.srv import HealthCheck
from geometry_msgs.msg import Point, Vector3
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.lifecycle import Publisher as LifecyclePublisher
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Header, String

from bonbon_object_intelligence.core.confidence_calibrator import (
    CalibratorConfig,
    ObjectConfidenceCalibrator,
)
from bonbon_object_intelligence.core.depth_association import CameraIntrinsics, pixel_to_position_3d
from bonbon_object_intelligence.core.low_confidence_object_handler import (
    LowConfidenceConfig,
    LowConfidenceObjectHandler,
)
from bonbon_object_intelligence.core.object_class_registry import ObjectClassRegistry
from bonbon_object_intelligence.core.object_memory_hook import (
    InMemoryObjectMemoryHook,
    ObjectMemoryEntry,
)
from bonbon_object_intelligence.core.object_permanence_tracker import (
    ObjectPermanenceTracker,
    PermanenceConfig,
    RawObjectDetection,
)
from bonbon_object_intelligence.core.object_verification_manager import ObjectVerificationManager
from bonbon_object_intelligence.core.ocr_hook import MockOCRBackend, is_ocr_eligible
from bonbon_object_intelligence.core.pi_object_inference_scheduler import (
    PiObjectInferenceScheduler,
    SchedulerConfig,
)

_HEALTH_OK, _HEALTH_WARN, _HEALTH_ERROR, _HEALTH_STALE = 0, 1, 2, 3
_SOURCE_MODULE = "bonbon_object_intelligence"

_QOS_RELIABLE = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
_QOS_TRANSIENT = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)


def _now_header(node: LifecycleNode, frame_id: str = "map") -> Header:
    h = Header()
    h.stamp = node.get_clock().now().to_msg()
    h.frame_id = frame_id
    return h


class ObjectIntelligenceNode(LifecycleNode):
    def __init__(self, node_name: str = "object_intelligence_node") -> None:
        super().__init__(node_name)

        self.declare_parameter("publish_rate_hz", 10.0)
        self.declare_parameter("health_rate_hz", 1.0)
        self.declare_parameter("vision_stale_timeout_sec", 1.0)
        self.declare_parameter("occlusion_grace_sec", 2.0)
        self.declare_parameter("memory_grace_sec", 15.0)
        self.declare_parameter("max_objects", 50)
        self.declare_parameter("rejection_threshold", 0.3)
        self.declare_parameter("small_object_area_px", 900.0)
        self.declare_parameter("small_object_confidence_floor", 0.35)
        self.declare_parameter("camera_hfov_deg", 60.0)
        self.declare_parameter("enable_ocr", False)
        self.declare_parameter("actionable_confidence_threshold", 0.6)
        self.declare_parameter("target_fps", 8.0)
        self.declare_parameter("bounded_queue_size", 2)

        self._tracker: ObjectPermanenceTracker | None = None
        self._calibrator: ObjectConfidenceCalibrator | None = None
        self._memory = InMemoryObjectMemoryHook()
        self._ocr = MockOCRBackend()
        self._enable_ocr = False
        self._camera_hfov_deg = 60.0

        # Class-support honesty, low-confidence gating, and Pi frame-rate
        # policy — see docs/OBJECT_RECOGNITION_FAILURE_ANALYSIS.md.
        self._registry = ObjectClassRegistry()
        self._verifier: ObjectVerificationManager | None = None
        self._low_confidence: LowConfidenceObjectHandler | None = None
        self._scheduler: PiObjectInferenceScheduler | None = None
        self._low_confidence_count = 0

        self._sub_objects = None
        self._sub_safety = None
        self._pub_tracked: LifecyclePublisher | None = None
        self._pub_health: LifecyclePublisher | None = None
        self._pub_status: LifecyclePublisher | None = None
        self._pub_dashboard_summary: LifecyclePublisher | None = None
        self._srv_health = None
        self._timer = None
        self._health_timer = None

        self._latest_objects_msg: DetectedObjectArray | None = None
        self._last_objects_msg_time: float = 0.0

        self._node_start = time.monotonic()
        self._cycle_count = 0
        self._error_count = 0
        self._last_cycle_t = 0.0

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("ObjectIntelligenceNode: configuring …")
        try:
            gp = lambda name: self.get_parameter(name).get_parameter_value()  # noqa: E731
            self._tracker = ObjectPermanenceTracker(
                config=PermanenceConfig(
                    occlusion_grace_sec=float(gp("occlusion_grace_sec").double_value),
                    memory_grace_sec=float(gp("memory_grace_sec").double_value),
                    max_objects=int(gp("max_objects").integer_value),
                )
            )
            self._calibrator = ObjectConfidenceCalibrator(
                CalibratorConfig(
                    small_object_area_px=float(gp("small_object_area_px").double_value),
                    small_object_confidence_floor=float(
                        gp("small_object_confidence_floor").double_value
                    ),
                    rejection_threshold=float(gp("rejection_threshold").double_value),
                )
            )
            self._enable_ocr = bool(gp("enable_ocr").bool_value)
            self._camera_hfov_deg = float(gp("camera_hfov_deg").double_value)

            self._verifier = ObjectVerificationManager(self._registry)
            self._low_confidence = LowConfidenceObjectHandler(
                LowConfidenceConfig(
                    actionable_threshold=float(gp("actionable_confidence_threshold").double_value)
                )
            )
            self._scheduler = PiObjectInferenceScheduler(
                SchedulerConfig(
                    target_fps=float(gp("target_fps").double_value),
                    bounded_queue_size=int(gp("bounded_queue_size").integer_value),
                )
            )
            self.get_logger().info("ObjectIntelligenceNode: configured")
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f"on_configure failed: {exc}")
            return TransitionCallbackReturn.FAILURE
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("ObjectIntelligenceNode: activating …")
        try:
            rate_hz = self.get_parameter("publish_rate_hz").get_parameter_value().double_value
            health_hz = self.get_parameter("health_rate_hz").get_parameter_value().double_value

            self._sub_objects = self.create_subscription(
                DetectedObjectArray,
                "/bonbon/vision/objects",
                self._cb_objects,
                _QOS_RELIABLE,
            )
            self._sub_safety = self.create_subscription(
                SafetyState,
                "/bonbon/safety/state",
                self._cb_safety,
                _QOS_TRANSIENT,
            )
            self._pub_tracked = self.create_lifecycle_publisher(
                TrackedObject,
                "/bonbon/objects/tracked",
                _QOS_RELIABLE,
            )
            self._pub_health = self.create_lifecycle_publisher(
                ModuleHealth,
                "/bonbon/objects/object_intelligence_node/health",
                _QOS_RELIABLE,
            )
            self._pub_status = self.create_lifecycle_publisher(
                String,
                "/bonbon/objects/status",
                _QOS_RELIABLE,
            )
            self._pub_dashboard_summary = self.create_lifecycle_publisher(
                String,
                "/bonbon/dashboard/object_summary",
                _QOS_RELIABLE,
            )
            self._srv_health = self.create_service(
                HealthCheck,
                "~/health_check",
                self._handle_health_check,
            )
            self._timer = self.create_timer(1.0 / max(rate_hz, 0.1), self._cb_publish_timer)
            self._health_timer = self.create_timer(1.0 / max(health_hz, 0.1), self._cb_health_timer)

            self.get_logger().info("ObjectIntelligenceNode: active")
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f"on_activate failed: {exc}")
            return TransitionCallbackReturn.FAILURE
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("ObjectIntelligenceNode: deactivating …")
        self._destroy_active_resources()
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("ObjectIntelligenceNode: cleaning up …")
        self._tracker = None
        self._calibrator = None
        self._latest_objects_msg = None
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("ObjectIntelligenceNode: shutting down …")
        self._destroy_active_resources()
        return TransitionCallbackReturn.SUCCESS

    # ── Subscriptions ────────────────────────────────────────────────────────

    def _cb_objects(self, msg: DetectedObjectArray) -> None:
        self._latest_objects_msg = msg
        self._last_objects_msg_time = time.monotonic()

    def _cb_safety(self, msg: SafetyState) -> None:
        pass  # reserved

    # ── Publish cycle ────────────────────────────────────────────────────────

    def _cb_publish_timer(self) -> None:
        if self._tracker is None:
            return
        try:
            self._run_cycle()
            self._cycle_count += 1
            self._last_cycle_t = time.monotonic()
        except Exception as exc:  # noqa: BLE001
            self._error_count += 1
            self.get_logger().error(f"Object intelligence cycle failed: {exc}")

    def _run_cycle(self) -> None:
        stale_timeout = (
            self.get_parameter("vision_stale_timeout_sec").get_parameter_value().double_value
        )
        msg = self._latest_objects_msg
        is_stale = (time.monotonic() - self._last_objects_msg_time) > stale_timeout if msg else True

        raw_dets: list[RawObjectDetection] = [] if is_stale else self._to_raw_detections(msg)
        snapshot = self._tracker.update(raw_dets)

        stamp = self.get_clock().now().to_msg()
        if self._pub_tracked is not None and self._pub_tracked.is_activated:
            for rec in snapshot:
                self._pub_tracked.publish(self._to_ros(rec, stamp))
                self._memory.remember(
                    ObjectMemoryEntry(
                        rec.object_track_id, rec.class_name, rec.x, rec.y, rec.z, time.monotonic()
                    )
                )

    def _to_raw_detections(self, msg: DetectedObjectArray) -> list[RawObjectDetection]:
        calibrated_inputs = [
            (o.class_name, o.confidence, (o.bbox_x, o.bbox_y, o.bbox_w, o.bbox_h))
            for o in msg.objects
        ]
        deduped = self._calibrator.deduplicate(calibrated_inputs)
        deduped_set = {(c, conf, bbox) for c, conf, bbox in deduped}

        intrinsics = CameraIntrinsics(width_px=640, height_px=480, hfov_deg=self._camera_hfov_deg)
        out = []
        for o in msg.objects:
            key = (o.class_name, o.confidence, (o.bbox_x, o.bbox_y, o.bbox_w, o.bbox_h))
            if key not in deduped_set:
                continue
            cal = self._calibrator.calibrate(
                o.class_name, o.confidence, (o.bbox_x, o.bbox_y, o.bbox_w, o.bbox_h)
            )
            if cal.rejected:
                continue
            # Published (passed calibration), but never treated as an
            # actionable signal on its own if still below the actionable
            # threshold — see LowConfidenceObjectHandler / brief rule
            # "low-confidence detection does not trigger behavior".
            if self._low_confidence is not None:
                assessment = self._low_confidence.assess(cal.calibrated_confidence)
                if not assessment.is_actionable:
                    self._low_confidence_count += 1

            if o.position_3d.x == o.position_3d.x and not (
                o.position_3d.x == 0.0 and o.position_3d.y == 0.0
            ):
                x, y, z = o.position_3d.x, o.position_3d.y, o.position_3d.z
            else:
                cx, cy = o.bbox_x + o.bbox_w / 2.0, o.bbox_y + o.bbox_h / 2.0
                x, y, z = pixel_to_position_3d(cx, cy, o.depth_m, intrinsics)
                if x != x:  # NaN depth — fall back to bearing-only placement
                    x, y, z = 1.0, math.tan(math.radians(o.bearing_deg)), 0.0

            reported_class = self._resolve_class_name(o)

            out.append(
                RawObjectDetection(
                    reported_class, cal.calibrated_confidence, x, y, z, o.source_camera
                )
            )
        return out

    def _resolve_class_name(self, o) -> str:
        """Base class name, unless ObjectVerificationManager has confirmed
        an ALIAS label (e.g. "person" -> "child") for this track across
        enough consecutive frames — never relabels off a single frame."""
        if self._verifier is None:
            return o.class_name
        results = self._verifier.verify(
            track_id=o.track_id or f"{o.class_name}:{o.bbox_x}:{o.bbox_y}",
            base_class=o.class_name,
            bbox=(o.bbox_x, o.bbox_y, o.bbox_w, o.bbox_h),
            frame_height=480.0,
        )
        for result in results:
            if result.confirmed:
                return result.reported_class
        return o.class_name

    def _to_ros(self, rec, stamp) -> TrackedObject:
        msg = TrackedObject()
        msg.header = Header()
        msg.header.stamp = stamp
        msg.header.frame_id = "map"
        msg.object_track_id = rec.object_track_id
        msg.class_name = rec.class_name
        msg.confidence = float(rec.confidence)
        msg.position_3d = Point(x=rec.x, y=rec.y, z=rec.z)
        msg.velocity_3d = Vector3(x=rec.vx, y=rec.vy, z=0.0)
        msg.first_seen = stamp
        msg.last_seen = stamp
        msg.permanence_state = rec.state.value
        msg.occlusion_duration_sec = float(rec.occlusion_duration_sec)

        msg.ocr_text = ""
        msg.ocr_confidence = 0.0
        if self._enable_ocr and is_ocr_eligible(rec.class_name) and self._ocr.is_ready:
            result = self._ocr.read(b"")
            msg.ocr_text = result.text
            msg.ocr_confidence = float(result.confidence)

        msg.source_camera = rec.source_camera
        return msg

    # ── Health ───────────────────────────────────────────────────────────────

    def _health_status(self) -> tuple:
        now = time.monotonic()
        if self._last_cycle_t and (now - self._last_cycle_t) > 3.0:
            return _HEALTH_STALE, "publish cycle stalled"
        if self._error_count > 0 and self._cycle_count == 0:
            return _HEALTH_ERROR, "all cycles failing"
        if self._error_count > 0:
            return _HEALTH_WARN, f"{self._error_count} cycle error(s)"
        if self._tracker is None:
            return _HEALTH_WARN, "not configured"
        return _HEALTH_OK, "nominal"

    def _cb_health_timer(self) -> None:
        if self._pub_health is None or not self._pub_health.is_activated:
            return
        status, text = self._health_status()
        msg = ModuleHealth()
        msg.header = _now_header(self, "base_link")
        msg.module_name = "bonbon_object_intelligence.object_intelligence_node"
        msg.status = status
        msg.status_text = text
        msg.uptime_sec = float(time.monotonic() - self._node_start)
        msg.last_successful_cycle_sec = float(
            (time.monotonic() - self._last_cycle_t) if self._last_cycle_t else -1.0
        )
        msg.cpu_percent = 0.0
        msg.memory_mb = 0.0
        msg.latency_ms = 0.0
        msg.error_count = int(self._error_count)
        msg.warning_count = 0
        msg.processed_count = int(self._cycle_count)
        self._pub_health.publish(msg)
        self._publish_status_and_dashboard_summary(status, text)

    def _publish_status_and_dashboard_summary(self, health_status: int, health_text: str) -> None:
        tracked_count = self._tracker.tracked_count if self._tracker is not None else 0
        scheduler_info = (
            {
                "queue_depth": self._scheduler.queue_depth,
                "stale_dropped_count": self._scheduler.stale_dropped_count,
                "target_fps": self._scheduler.target_fps,
            }
            if self._scheduler is not None
            else {}
        )
        status_payload = {
            "health_status": health_status,
            "health_text": health_text,
            "supported_class_count": len(self._registry.list_supported()),
            "unsupported_class_count": len(self._registry.list_unsupported()),
            "low_confidence_count": self._low_confidence_count,
            "ocr_enabled": self._enable_ocr,
            "scheduler": scheduler_info,
        }
        if self._pub_status is not None and self._pub_status.is_activated:
            self._pub_status.publish(String(data=json.dumps(status_payload)))

        dashboard_payload = {
            "tracked_object_count": tracked_count,
            "low_confidence_count": self._low_confidence_count,
            "supported_class_count": len(self._registry.list_supported()),
            "health": health_text,
        }
        if self._pub_dashboard_summary is not None and self._pub_dashboard_summary.is_activated:
            self._pub_dashboard_summary.publish(String(data=json.dumps(dashboard_payload)))

    def _handle_health_check(self, request, response):
        status, text = self._health_status()
        response.healthy = status in (_HEALTH_OK, _HEALTH_WARN)
        response.status = text
        response.warnings = [text] if status == _HEALTH_WARN else []
        response.errors = [text] if status in (_HEALTH_ERROR, _HEALTH_STALE) else []
        response.uptime_sec = float(time.monotonic() - self._node_start)
        return response

    # ── Teardown ─────────────────────────────────────────────────────────────

    def _destroy_active_resources(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._health_timer is not None:
            self._health_timer.cancel()
            self._health_timer = None
        for attr in (
            "_sub_objects",
            "_sub_safety",
            "_pub_tracked",
            "_pub_health",
            "_pub_status",
            "_pub_dashboard_summary",
            "_srv_health",
        ):
            resource = getattr(self, attr, None)
            if resource is not None:
                for destroy in (
                    self.destroy_publisher,
                    self.destroy_subscription,
                    self.destroy_service,
                ):
                    try:
                        destroy(resource)  # type: ignore[arg-type]
                        break
                    except Exception:  # noqa: BLE001
                        continue
                setattr(self, attr, None)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ObjectIntelligenceNode("object_intelligence_node")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
