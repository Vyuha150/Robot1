"""DataFeedbackNode — failure-case logging, hard-negative collection, and
privacy-safe retention, as a LifecycleNode.

Does not duplicate database access (reuses bonbon_data_stores'
SQLiteConnection/SchemaMigrator via FeedbackStore) and does not store raw
face/audio by default (PrivacySafeDataPolicy; raw_snapshot_path is only
honored when debug_mode_enabled is an explicit launch parameter).

Two ways failure cases reach this node:
  1. Automatic: GestureEvent confidence below the live recommended floor
     published by bonbon_perception_efficiency (falls back to a static
     default if that package isn't running) is logged automatically. The
     SQLite write happens off the ROS callback thread (ThreadPoolExecutor +
     BoundedInferenceQueue gate, same pattern as bonbon_affective_ai's
     voice/text analysis dispatch) so a slow disk write never delays
     processing of the next gesture event.
  2. Explicit: any node can call ~/report_failure_case (ReportFailureCase
     service) — the general mechanism, so this node never needs bespoke
     per-signal-type subscription wiring for object/face/voice/text. This
     stays synchronous: a service is request-response by nature, and the
     caller needs the real case_id/accepted outcome in its response, not a
     placeholder — unlike the automatic path, there is no "next event" this
     blocks.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import rclpy
from bonbon_msgs.msg import GestureEvent, ModuleHealth, PerceptionPolicy
from bonbon_perception_efficiency.core.bounded_inference_queue import BoundedInferenceQueue
from bonbon_srvs.srv import HealthCheck, ReportFailureCase
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from bonbon_data_feedback.core.annotation_export_manager import AnnotationExportManager
from bonbon_data_feedback.core.dataset_version_manager import DatasetVersionManager
from bonbon_data_feedback.core.failure_case_logger import FailureCaseLogger
from bonbon_data_feedback.core.feedback_store import FeedbackStore
from bonbon_data_feedback.core.hard_negative_collector import HardNegativeCollector
from bonbon_data_feedback.core.model_evaluation_store import ModelEvaluationStore
from bonbon_data_feedback.core.privacy_safe_data_policy import PrivacySafeDataPolicy

_HEALTH_OK, _HEALTH_WARN, _HEALTH_ERROR, _HEALTH_STALE = 0, 1, 2, 3
_DEFAULT_GESTURE_FLOOR = 0.65  # mirrors bonbon_perception_efficiency's default

_QOS_RELIABLE = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)


class DataFeedbackNode(LifecycleNode):
    def __init__(self, node_name: str = "data_feedback_node") -> None:
        super().__init__(node_name)

        self.declare_parameter("db_path", "data/bonbon_data_feedback/feedback.db")
        self.declare_parameter("export_dir", "data/bonbon_data_feedback/exports")
        self.declare_parameter("debug_mode_enabled", False)
        self.declare_parameter("hard_negative_confidence_threshold", 0.7)
        self.declare_parameter("retention_sweep_rate_hz", 1.0 / 3600.0)  # hourly
        self.declare_parameter("health_rate_hz", 1.0)
        # Which hospital deployment this instance belongs to -- stamped onto
        # every failure case so multi-site deployments can query per-site
        # failure rates instead of a single undifferentiated pool. "" (the
        # default) is honest for a single-site dev/lab deployment; set per
        # real hospital site at launch, same pattern as other packages'
        # deployment-time params (e.g. distributed_network_monitor's pi_role).
        self.declare_parameter("site_id", "")

        self._site_id = ""
        self._store: FeedbackStore | None = None
        self._policy: PrivacySafeDataPolicy | None = None
        self._failure_logger: FailureCaseLogger | None = None
        self._hard_negative_collector: HardNegativeCollector | None = None
        self._export_manager: AnnotationExportManager | None = None
        self._version_manager: DatasetVersionManager | None = None
        self._eval_store: ModelEvaluationStore | None = None

        self._gesture_floor = _DEFAULT_GESTURE_FLOOR

        # Non-blocking automatic write path: the gesture-event callback only
        # ever admits to this queue and submits to this executor — it never
        # blocks on disk I/O itself. drop-newest is correct here exactly as
        # it is for affective_ai_node's queues: a fresh gesture event is more
        # useful than one that has been waiting, and an already-admitted
        # write should be allowed to finish rather than be discarded.
        self._gesture_log_queue = BoundedInferenceQueue(max_depth=8)
        self._write_executor: ThreadPoolExecutor | None = None

        self._subs: list = []
        self._pub_health = None
        self._srv_report = None
        self._srv_health = None
        self._retention_timer = None
        self._health_timer = None

        self._node_start = time.monotonic()
        self._cases_logged = 0
        self._error_count = 0

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("DataFeedbackNode: configuring …")
        try:
            db_path = Path(self.get_parameter("db_path").get_parameter_value().string_value)
            export_dir = self.get_parameter("export_dir").get_parameter_value().string_value
            debug_mode = self.get_parameter("debug_mode_enabled").get_parameter_value().bool_value
            threshold = (
                self.get_parameter("hard_negative_confidence_threshold")
                .get_parameter_value()
                .double_value
            )
            self._site_id = self.get_parameter("site_id").get_parameter_value().string_value

            self._store = FeedbackStore(db_path)
            self._policy = PrivacySafeDataPolicy(debug_mode_enabled=debug_mode)
            self._failure_logger = FailureCaseLogger(self._store, self._policy)
            self._hard_negative_collector = HardNegativeCollector(
                self._store, self._policy, confidence_threshold=threshold
            )
            self._export_manager = AnnotationExportManager(self._store, export_dir)
            self._version_manager = DatasetVersionManager(self._store, self._export_manager)
            self._eval_store = ModelEvaluationStore(self._store)

            if debug_mode:
                self.get_logger().warn(
                    "DataFeedbackNode: debug_mode_enabled=true — raw snapshot "
                    "paths will be persisted when supplied."
                )
            self.get_logger().info("DataFeedbackNode: configured")
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f"on_configure failed: {exc}")
            return TransitionCallbackReturn.FAILURE
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("DataFeedbackNode: activating …")
        try:
            health_hz = self.get_parameter("health_rate_hz").get_parameter_value().double_value
            sweep_hz = (
                self.get_parameter("retention_sweep_rate_hz").get_parameter_value().double_value
            )

            self._write_executor = ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="data_feedback_write"
            )

            self._subs.append(
                self.create_subscription(
                    GestureEvent, "/bonbon/gesture/events", self._cb_gesture_event, _QOS_RELIABLE
                )
            )
            self._subs.append(
                self.create_subscription(
                    PerceptionPolicy,
                    "/bonbon/perception_efficiency/policy",
                    self._cb_perception_policy,
                    _QOS_RELIABLE,
                )
            )

            self._pub_health = self.create_lifecycle_publisher(
                ModuleHealth, "/bonbon/data_feedback/data_feedback_node/health", _QOS_RELIABLE
            )
            self._srv_report = self.create_service(
                ReportFailureCase, "~/report_failure_case", self._handle_report_failure_case
            )
            self._srv_health = self.create_service(
                HealthCheck, "~/health_check", self._handle_health_check
            )

            self._retention_timer = self.create_timer(
                1.0 / max(sweep_hz, 1e-6), self._cb_retention_sweep
            )
            self._health_timer = self.create_timer(1.0 / max(health_hz, 0.1), self._cb_health_timer)

            self.get_logger().info("DataFeedbackNode: active")
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error(f"on_activate failed: {exc}")
            return TransitionCallbackReturn.FAILURE
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("DataFeedbackNode: deactivating …")
        self._destroy_active_resources()
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("DataFeedbackNode: cleaning up …")
        if self._store is not None:
            self._store.close()
        self._store = None
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        self._destroy_active_resources()
        if self._store is not None:
            self._store.close()
        return TransitionCallbackReturn.SUCCESS

    # ── Subscriptions ────────────────────────────────────────────────────────

    def _cb_perception_policy(self, msg: PerceptionPolicy) -> None:
        for signal, threshold in zip(msg.signal_names, msg.recommended_thresholds):
            if signal == "gesture":
                self._gesture_floor = float(threshold)

    def _cb_gesture_event(self, msg: GestureEvent) -> None:
        if self._failure_logger is None or self._write_executor is None:
            return
        if msg.confidence >= self._gesture_floor:
            return
        admit = self._gesture_log_queue.try_admit()
        if not admit.admitted:
            self.get_logger().debug(
                f"Failure-case write queue full (depth={admit.queue_depth}) — dropping gesture case."
            )
            return
        self._write_executor.submit(
            self._write_gesture_failure_case,
            msg.gesture_type,
            msg.confidence,
            msg.person_track_id,
            msg.hand_side,
            msg.body_part,
        )

    def _write_gesture_failure_case(
        self,
        gesture_type: str,
        confidence: float,
        person_track_id: str,
        hand_side: str,
        body_part: str,
    ) -> None:
        """Runs off the ROS callback thread — the actual SQLite write for
        the automatic gesture-confidence failure-case path. SQLiteConnection
        is thread-local by design (see bonbon_data_stores), so writing from
        a worker thread here is safe."""
        try:
            self._failure_logger.log(
                category="gesture",
                signal_name="gesture_below_confidence_floor",
                actual_label=gesture_type,
                confidence=confidence,
                person_track_id=person_track_id,
                context={"hand_side": hand_side, "body_part": body_part},
                site_id=self._site_id,
                # No language_code here -- GestureEvent carries no language
                # signal; leaving it "" is honest, not a placeholder guess.
            )
            self._cases_logged += 1
        except Exception as exc:  # noqa: BLE001
            self._error_count += 1
            self.get_logger().error(f"Failed to log gesture failure case: {exc}")
        finally:
            self._gesture_log_queue.mark_complete()

    # ── Service handlers ─────────────────────────────────────────────────────

    def _handle_report_failure_case(self, request, response):
        if self._failure_logger is None or self._hard_negative_collector is None:
            response.accepted = False
            response.message = "node not configured"
            return response
        try:
            context = json.loads(request.context_json) if request.context_json else {}
        except (json.JSONDecodeError, TypeError):
            context = {}

        try:
            is_hard_negative = self._hard_negative_collector.is_hard_negative(
                request.confidence, request.was_correct
            )
            if is_hard_negative:
                case_id = self._hard_negative_collector.collect(
                    category=request.category,
                    signal_name=request.signal_name,
                    actual_label=request.actual_label,
                    confidence=request.confidence,
                    was_correct=request.was_correct,
                    expected_label=request.expected_label,
                    person_track_id=request.person_track_id,
                    context=context,
                    site_id=self._site_id,
                    language_code=request.language_code,
                )
            else:
                case_id = self._failure_logger.log(
                    category=request.category,
                    signal_name=request.signal_name,
                    actual_label=request.actual_label,
                    confidence=request.confidence,
                    expected_label=request.expected_label,
                    person_track_id=request.person_track_id,
                    context=context,
                    raw_snapshot_path=request.raw_snapshot_path,
                    site_id=self._site_id,
                    language_code=request.language_code,
                )
            self._cases_logged += 1
            response.accepted = True
            response.case_id = case_id or ""
            response.is_hard_negative = is_hard_negative
            response.message = "logged"
        except Exception as exc:  # noqa: BLE001
            self._error_count += 1
            response.accepted = False
            response.message = str(exc)
        return response

    def _handle_health_check(self, request, response):
        status, text = self._health_status()
        response.healthy = status in (_HEALTH_OK, _HEALTH_WARN)
        response.status = text
        response.warnings = [text] if status == _HEALTH_WARN else []
        response.errors = [text] if status in (_HEALTH_ERROR, _HEALTH_STALE) else []
        response.uptime_sec = float(time.monotonic() - self._node_start)
        return response

    # ── Retention sweep ──────────────────────────────────────────────────────

    def _cb_retention_sweep(self) -> None:
        if self._store is None or self._policy is None:
            return
        now = time.time()
        try:
            for category in ("object", "gesture", "speaker", "face", "emotion"):
                retention_days = self._policy.retention_days_for(category)
                cutoff = now - (retention_days * 86400.0)
                deleted = self._store.delete_expired(category, cutoff)
                if deleted:
                    self.get_logger().info(
                        f"Retention sweep: deleted {deleted} expired '{category}' case(s)"
                    )
        except Exception as exc:  # noqa: BLE001
            self._error_count += 1
            self.get_logger().error(f"Retention sweep failed: {exc}")

    # ── Health ───────────────────────────────────────────────────────────────

    def _health_status(self) -> tuple:
        if self._store is None:
            return _HEALTH_WARN, "not configured"
        if self._error_count > 0:
            return _HEALTH_WARN, f"{self._error_count} error(s)"
        return _HEALTH_OK, "nominal"

    def _cb_health_timer(self) -> None:
        if self._pub_health is None or not self._pub_health.is_activated:
            return
        status, text = self._health_status()
        msg = ModuleHealth()
        msg.module_name = "bonbon_data_feedback.data_feedback_node"
        msg.status = status
        msg.status_text = text
        msg.uptime_sec = float(time.monotonic() - self._node_start)
        msg.error_count = int(self._error_count)
        msg.processed_count = int(self._cases_logged)
        self._pub_health.publish(msg)

    # ── Teardown ─────────────────────────────────────────────────────────────

    def _destroy_active_resources(self) -> None:
        if self._write_executor is not None:
            self._write_executor.shutdown(wait=False)
            self._write_executor = None
        for timer_attr in ("_retention_timer", "_health_timer"):
            t = getattr(self, timer_attr, None)
            if t is not None:
                t.cancel()
                setattr(self, timer_attr, None)
        for sub in self._subs:
            try:
                self.destroy_subscription(sub)
            except Exception:  # noqa: BLE001
                pass
        self._subs.clear()
        if self._pub_health is not None:
            try:
                self.destroy_publisher(self._pub_health)
            except Exception:  # noqa: BLE001
                pass
            self._pub_health = None
        for srv_attr in ("_srv_report", "_srv_health"):
            srv = getattr(self, srv_attr, None)
            if srv is not None:
                try:
                    self.destroy_service(srv)
                except Exception:  # noqa: BLE001
                    pass
                setattr(self, srv_attr, None)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = DataFeedbackNode("data_feedback_node")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
