"""MultiPersonTrackerNode — person identity lifecycle LifecycleNode.

Consumes (does not redetect):
    /bonbon/vision/persons   (bonbon_msgs/PersonStateArray)  @ ~10 Hz
    /bonbon/safety/state     (bonbon_msgs/SafetyState)

Publishes:
    /bonbon/persons/tracks            (bonbon_msgs/PersonTrack)       one msg per
                                       tracked person per cycle
    /bonbon/persons/lifecycle_events  (std_msgs/String)               human-readable,
                                       only on a real state transition (not steady-state)
    /bonbon/persons/<node>/health     (bonbon_msgs/ModuleHealth)

Services:
    ~/health_check  (bonbon_srvs/HealthCheck)

Failure handling:
    If /bonbon/vision/persons goes stale (no message within
    ``vision_stale_timeout_sec``), this cycle is treated as "nobody detected"
    so people correctly age toward temporarily_lost/left_scene rather than
    appearing falsely present forever off a frozen last-known frame.
"""

from __future__ import annotations

import threading
import time

import rclpy
from bonbon_msgs.msg import ModuleHealth, PersonStateArray, PersonTrack, SafetyState
from bonbon_srvs.srv import HealthCheck
from geometry_msgs.msg import Point, Vector3
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.lifecycle import Publisher as LifecyclePublisher
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Header, String

from bonbon_multi_person_tracker.core.lifecycle_state_machine import LifecycleConfig
from bonbon_multi_person_tracker.core.multi_person_scene_manager import MultiPersonSceneManager
from bonbon_multi_person_tracker.core.person_record import PersonRecord, RawPersonDetection

_HEALTH_OK, _HEALTH_WARN, _HEALTH_ERROR, _HEALTH_STALE = 0, 1, 2, 3
_SOURCE_MODULE = "bonbon_multi_person_tracker"

_QOS_SENSOR = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
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


class MultiPersonTrackerNode(LifecycleNode):
    def __init__(self, node_name: str = "multi_person_tracker_node") -> None:
        super().__init__(node_name)

        self.declare_parameter("publish_rate_hz", 10.0)
        self.declare_parameter("health_rate_hz", 1.0)
        self.declare_parameter("vision_stale_timeout_sec", 1.0)
        self.declare_parameter("confirmation_hits", 2)
        self.declare_parameter("candidate_miss_limit", 2)
        self.declare_parameter("loss_grace_sec", 4.0)
        self.declare_parameter("active_interaction_hold_sec", 3.0)
        self.declare_parameter("confidence_decay_per_sec", 0.15)
        self.declare_parameter("recall_window_sec", 300.0)
        self.declare_parameter("max_persons", 20)
        self.declare_parameter("privacy_mode", False)

        self._scene_manager: MultiPersonSceneManager | None = None

        self._sub_persons = None
        self._sub_safety = None
        self._pub_tracks: LifecyclePublisher | None = None
        self._pub_events: LifecyclePublisher | None = None
        self._pub_health: LifecyclePublisher | None = None
        self._srv_health = None
        self._timer = None
        self._health_timer = None

        self._lock = threading.Lock()
        self._node_start = time.monotonic()
        self._cycle_count = 0
        self._error_count = 0
        self._warning_count = 0
        self._last_cycle_t = 0.0
        self._last_latency_ms = 0.0

        self._latest_persons_msg: PersonStateArray | None = None
        self._last_persons_msg_time: float = 0.0
        self._privacy_mode = False

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("MultiPersonTrackerNode: configuring …")
        try:

            def gp(name):
                return self.get_parameter(name).get_parameter_value()

            cfg = LifecycleConfig(
                confirmation_hits=int(gp("confirmation_hits").integer_value),
                candidate_miss_limit=int(gp("candidate_miss_limit").integer_value),
                loss_grace_sec=float(gp("loss_grace_sec").double_value),
                active_interaction_hold_sec=float(gp("active_interaction_hold_sec").double_value),
                confidence_decay_per_sec=float(gp("confidence_decay_per_sec").double_value),
            )
            self._scene_manager = MultiPersonSceneManager(
                lifecycle_config=cfg,
                recall_window_sec=float(gp("recall_window_sec").double_value),
                max_persons=int(gp("max_persons").integer_value),
            )
            self._privacy_mode = bool(gp("privacy_mode").bool_value)
            self.get_logger().info(
                "MultiPersonTrackerNode: configured (loss_grace=%.1fs, max_persons=%d)",
                cfg.loss_grace_sec,
                int(gp("max_persons").integer_value),
            )
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error("on_configure failed: %s", str(exc))
            return TransitionCallbackReturn.FAILURE
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("MultiPersonTrackerNode: activating …")
        try:
            rate_hz = self.get_parameter("publish_rate_hz").get_parameter_value().double_value
            health_hz = self.get_parameter("health_rate_hz").get_parameter_value().double_value

            self._sub_persons = self.create_subscription(
                PersonStateArray,
                "/bonbon/vision/persons",
                self._cb_persons,
                _QOS_SENSOR,
            )
            self._sub_safety = self.create_subscription(
                SafetyState,
                "/bonbon/safety/state",
                self._cb_safety,
                _QOS_TRANSIENT,
            )

            self._pub_tracks = self.create_lifecycle_publisher(
                PersonTrack,
                "/bonbon/persons/tracks",
                _QOS_RELIABLE,
            )
            self._pub_events = self.create_lifecycle_publisher(
                String,
                "/bonbon/persons/lifecycle_events",
                _QOS_RELIABLE,
            )
            self._pub_health = self.create_lifecycle_publisher(
                ModuleHealth,
                "/bonbon/persons/multi_person_tracker_node/health",
                _QOS_RELIABLE,
            )
            self._srv_health = self.create_service(
                HealthCheck,
                "~/health_check",
                self._handle_health_check,
            )

            self._timer = self.create_timer(1.0 / max(rate_hz, 0.1), self._cb_publish_timer)
            self._health_timer = self.create_timer(1.0 / max(health_hz, 0.1), self._cb_health_timer)

            self.get_logger().info("MultiPersonTrackerNode: active (rate=%.1f Hz)", rate_hz)
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error("on_activate failed: %s", str(exc))
            return TransitionCallbackReturn.FAILURE
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("MultiPersonTrackerNode: deactivating …")
        self._destroy_active_resources()
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("MultiPersonTrackerNode: cleaning up …")
        with self._lock:
            self._scene_manager = None
            self._latest_persons_msg = None
            self._last_persons_msg_time = 0.0
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("MultiPersonTrackerNode: shutting down …")
        self._destroy_active_resources()
        return TransitionCallbackReturn.SUCCESS

    # ── Subscriptions ────────────────────────────────────────────────────────

    def _cb_persons(self, msg: PersonStateArray) -> None:
        with self._lock:
            self._latest_persons_msg = msg
            self._last_persons_msg_time = time.monotonic()

    def _cb_safety(self, msg: SafetyState) -> None:
        # Reserved for future use (e.g. suppressing tracking publish during
        # SAFE_STOP); SafetyState does not itself gate identity tracking.
        pass

    # ── Publish cycle ────────────────────────────────────────────────────────

    def _cb_publish_timer(self) -> None:
        if self._scene_manager is None:
            return
        cycle_start = time.monotonic()
        try:
            self._run_cycle()
            self._cycle_count += 1
            self._last_cycle_t = time.monotonic()
            self._last_latency_ms = (self._last_cycle_t - cycle_start) * 1000.0
        except Exception as exc:  # noqa: BLE001
            self._error_count += 1
            self.get_logger().error("Multi-person tracker cycle failed: %s", str(exc))

    def _run_cycle(self) -> None:
        stale_timeout = (
            self.get_parameter("vision_stale_timeout_sec").get_parameter_value().double_value
        )

        with self._lock:
            msg = self._latest_persons_msg
            is_stale = (
                (time.monotonic() - self._last_persons_msg_time) > stale_timeout if msg else True
            )

        detections = [] if is_stale else self._to_detections(msg)

        snapshot = self._scene_manager.update(detections)

        stamp = self.get_clock().now().to_msg()
        if self._pub_tracks is not None and self._pub_tracks.is_activated:
            for rec in snapshot:
                self._pub_tracks.publish(self._record_to_ros(rec, stamp))

        if self._pub_events is not None and self._pub_events.is_activated:
            for rec in snapshot:
                t = rec.fsm.last_transition
                if t is not None and t.from_state != t.to_state:
                    evt = String()
                    label = rec.known_person_id or rec.temporary_person_id
                    evt.data = f"{t.to_state.value}: {label} ({t.reason})"
                    self._pub_events.publish(evt)
                    self.get_logger().info("Lifecycle event: %s", evt.data)

    # ── Conversion helpers ───────────────────────────────────────────────────

    def _to_detections(self, msg: PersonStateArray) -> list[RawPersonDetection]:
        out = []
        for p in msg.persons:
            out.append(
                RawPersonDetection(
                    raw_track_id=p.track_id,
                    face_id="" if self._privacy_mode else p.face_id,
                    x=p.position.x,
                    y=p.position.y,
                    z=p.position.z,
                )
            )
        return out

    def _record_to_ros(self, rec: PersonRecord, stamp) -> PersonTrack:
        msg = PersonTrack()
        msg.header = Header()
        msg.header.stamp = stamp
        msg.header.frame_id = "map"
        msg.person_track_id = rec.person_track_id
        msg.temporary_person_id = rec.temporary_person_id
        msg.known_person_id = "" if self._privacy_mode else rec.known_person_id

        msg.bbox_x, msg.bbox_y, msg.bbox_w, msg.bbox_h = rec.bbox
        msg.face_bbox_available = rec.face_bbox is not None
        if rec.face_bbox is not None:
            msg.face_bbox_x, msg.face_bbox_y, msg.face_bbox_w, msg.face_bbox_h = rec.face_bbox

        msg.body_embedding_id = rec.body_embedding_id
        msg.face_embedding_id = rec.face_embedding_id

        msg.position_3d = Point(x=rec.last_x, y=rec.last_y, z=rec.last_z)
        msg.velocity_3d = Vector3(x=rec.vx, y=rec.vy, z=0.0)

        msg.lifecycle_state = rec.lifecycle_state.value
        msg.time_since_last_seen_sec = rec.time_since_last_seen_sec
        msg.confidence = rec.confidence
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
        if self._scene_manager is None:
            return _HEALTH_WARN, "not configured"
        return _HEALTH_OK, "nominal"

    def _cb_health_timer(self) -> None:
        if self._pub_health is None or not self._pub_health.is_activated:
            return
        status, text = self._health_status()
        msg = ModuleHealth()
        msg.header = _now_header(self, "base_link")
        msg.module_name = "bonbon_multi_person_tracker.multi_person_tracker_node"
        msg.status = status
        msg.status_text = text
        msg.uptime_sec = float(time.monotonic() - self._node_start)
        msg.last_successful_cycle_sec = float(
            (time.monotonic() - self._last_cycle_t) if self._last_cycle_t else -1.0
        )
        msg.cpu_percent = 0.0
        msg.memory_mb = 0.0
        msg.latency_ms = float(self._last_latency_ms)
        msg.error_count = int(self._error_count)
        msg.warning_count = int(self._warning_count)
        msg.processed_count = int(self._cycle_count)
        self._pub_health.publish(msg)

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
            "_sub_persons",
            "_sub_safety",
            "_pub_tracks",
            "_pub_events",
            "_pub_health",
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
    node = MultiPersonTrackerNode("multi_person_tracker_node")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
