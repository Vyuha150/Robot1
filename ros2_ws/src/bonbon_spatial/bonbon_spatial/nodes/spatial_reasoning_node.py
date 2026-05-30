"""SpatialReasoningNode — human-aware spatial reasoning LifecycleNode.

Subscriptions:
    /bonbon/vision/persons  (bonbon_msgs/PersonStateArray)  @ 10 Hz
    /bonbon/safety/state    (bonbon_msgs/SafetyState)        @ 10 Hz

Publications:
    /bonbon/spatial/entities   (bonbon_msgs/SpatialEntity)        @ 5 Hz
    /bonbon/spatial/relations  (bonbon_msgs/SpatialRelation)      @ 5 Hz
    /bonbon/spatial/hints      (bonbon_msgs/SocialNavigationHint) on change

Services:
    ~/get_world_model          (bonbon_srvs/GetWorldModel)
    ~/get_approach_pose        (bonbon_srvs/GetApproachPose)
    ~/add_restricted_zone      (bonbon_srvs/AddRestrictedZone)
    ~/remove_restricted_zone   (bonbon_srvs/RemoveRestrictedZone)
"""

from __future__ import annotations

import math
import threading
import time
import uuid
from typing import List, Optional

import rclpy
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.lifecycle import Publisher as LifecyclePublisher
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy

# ROS2 message types
from std_msgs.msg import Header
from geometry_msgs.msg import (
    Point,
    Pose,
    PoseStamped,
    Quaternion,
    Vector3,
    Polygon,
    Point32,
)
from builtin_interfaces.msg import Time as BuiltinTime

from bonbon_msgs.msg import (
    ModuleHealth,
    PersonStateArray,
    RiskEvent,
    SafetyState,
    SpatialEntity,
    SpatialRelation,
    SocialNavigationHint,
)
from bonbon_srvs.srv import (
    GetWorldModel,
    GetApproachPose,
    AddRestrictedZone,
    RemoveRestrictedZone,
    HealthCheck,
)

# ModuleHealth status constants (mirror bonbon_msgs/ModuleHealth.msg)
_HEALTH_OK = 0
_HEALTH_WARN = 1
_HEALTH_ERROR = 2
_HEALTH_STALE = 3

# Core components
from bonbon_spatial.core.entity_tracker import EntityTracker, TrackedEntity
from bonbon_spatial.core.personal_space_estimator import (
    PersonalSpaceEstimator,
    ProxemicZones,
)
from bonbon_spatial.core.semantic_zone_manager import SemanticZone, SemanticZoneManager
from bonbon_spatial.core.social_navigation_hints import SocialNavigationHints, HintSummary
from bonbon_spatial.core.approach_pose_planner import ApproachPosePlanner
from bonbon_spatial.core.restricted_zone_monitor import RestrictedZoneMonitor
from bonbon_spatial.core.blockage_detector import BlockageDetector
from bonbon_spatial.core.dynamic_obstacle_predictor import DynamicObstaclePredictor

# RiskEvent severity constants (mirror bonbon_msgs/RiskEvent.msg)
_SEV_INFO = 0
_SEV_LOW = 1
_SEV_MEDIUM = 2
_SEV_HIGH = 3
_SEV_CRITICAL = 4

# ---------------------------------------------------------------------------
# QoS profiles
# ---------------------------------------------------------------------------
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

_SOURCE_MODULE = "bonbon_spatial"


def _yaw_to_quaternion(yaw: float) -> Quaternion:
    """Convert a yaw angle (radians) to a :class:`geometry_msgs/Quaternion`."""
    q = Quaternion()
    q.w = math.cos(yaw / 2.0)
    q.z = math.sin(yaw / 2.0)
    return q


def _now_header(node: LifecycleNode, frame_id: str = "map") -> Header:
    """Build a :class:`std_msgs/Header` with the current node clock time."""
    h = Header()
    h.stamp = node.get_clock().now().to_msg()
    h.frame_id = frame_id
    return h


class SpatialReasoningNode(LifecycleNode):
    """LifecycleNode for human-aware spatial reasoning.

    Lifecycle transitions::

        unconfigured --[configure]--> inactive --[activate]--> active
        active --[deactivate]--> inactive --[cleanup]--> unconfigured

    All entity-state mutations are protected by ``self._lock``.
    """

    def __init__(self, node_name: str = "spatial_reasoning_node") -> None:
        """Declare ROS2 parameters before any lifecycle transition."""
        super().__init__(node_name)

        # Declare parameters with defaults (overridden by YAML at configure).
        self.declare_parameter("publish_rate_hz", 5.0)
        self.declare_parameter("entity_timeout_sec", 5.0)
        self.declare_parameter("personal_space.intimate_m", 0.45)
        self.declare_parameter("personal_space.personal_m", 1.2)
        self.declare_parameter("personal_space.social_m", 3.6)
        self.declare_parameter("personal_space.public_m", 7.6)
        self.declare_parameter("personal_space.stop_distance_m", 0.6)
        self.declare_parameter("personal_space.slow_distance_m", 1.5)
        self.declare_parameter("personal_space.approach_target_m", 1.0)
        # Blockage / prediction parameters.
        self.declare_parameter("blockage.corridor_half_width_m", 0.5)
        self.declare_parameter("blockage.corridor_length_m", 2.0)
        self.declare_parameter("blockage.persistence_sec", 1.5)
        self.declare_parameter("prediction.horizon_sec", 2.5)
        self.declare_parameter("prediction.timestep_sec", 0.25)
        self.declare_parameter("health_rate_hz", 1.0)

        # Core components — initialised in on_configure.
        self._tracker: Optional[EntityTracker] = None
        self._estimator: Optional[PersonalSpaceEstimator] = None
        self._zone_manager: Optional[SemanticZoneManager] = None
        self._hint_generator: Optional[SocialNavigationHints] = None
        self._approach_planner: Optional[ApproachPosePlanner] = None
        self._zone_monitor: Optional[RestrictedZoneMonitor] = None
        self._blockage_detector: Optional[BlockageDetector] = None
        self._predictor: Optional[DynamicObstaclePredictor] = None

        # ROS2 infrastructure — initialised in on_activate.
        self._sub_persons = None
        self._sub_safety = None
        self._pub_entities: Optional[LifecyclePublisher] = None
        self._pub_relations: Optional[LifecyclePublisher] = None
        self._pub_hints: Optional[LifecyclePublisher] = None
        self._pub_alerts: Optional[LifecyclePublisher] = None
        self._pub_health: Optional[LifecyclePublisher] = None
        self._srv_world_model = None
        self._srv_approach_pose = None
        self._srv_add_zone = None
        self._srv_remove_zone = None
        self._srv_health = None
        self._timer = None
        self._health_timer = None

        # Health / diagnostics telemetry.
        self._node_start: float = time.monotonic()
        self._cycle_count: int = 0
        self._error_count: int = 0
        self._warning_count: int = 0
        self._last_cycle_t: float = 0.0
        self._last_latency_ms: float = 0.0

        # Runtime state.
        self._lock = threading.Lock()
        self._safety_state: Optional[SafetyState] = None
        self._last_hint_type: str = ""
        self._privacy_mode: bool = False
        self._last_blocked: bool = False

    # ------------------------------------------------------------------
    # Lifecycle callbacks
    # ------------------------------------------------------------------

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        """Load parameters and instantiate core components."""
        self.get_logger().info("SpatialReasoningNode: configuring …")

        try:
            timeout_sec = (
                self.get_parameter("entity_timeout_sec").get_parameter_value().double_value
            )
            zones_cfg = ProxemicZones(
                intimate_m=self.get_parameter(
                    "personal_space.intimate_m"
                ).get_parameter_value().double_value,
                personal_m=self.get_parameter(
                    "personal_space.personal_m"
                ).get_parameter_value().double_value,
                social_m=self.get_parameter(
                    "personal_space.social_m"
                ).get_parameter_value().double_value,
                public_m=self.get_parameter(
                    "personal_space.public_m"
                ).get_parameter_value().double_value,
                stop_distance_m=self.get_parameter(
                    "personal_space.stop_distance_m"
                ).get_parameter_value().double_value,
                slow_distance_m=self.get_parameter(
                    "personal_space.slow_distance_m"
                ).get_parameter_value().double_value,
                approach_target_m=self.get_parameter(
                    "personal_space.approach_target_m"
                ).get_parameter_value().double_value,
            )

            self._tracker = EntityTracker(timeout_sec=timeout_sec)
            self._estimator = PersonalSpaceEstimator(zones=zones_cfg)
            self._zone_manager = SemanticZoneManager()
            self._hint_generator = SocialNavigationHints(estimator=self._estimator)
            self._approach_planner = ApproachPosePlanner(
                zone_manager=self._zone_manager,
                estimator=self._estimator,
            )
            self._zone_monitor = RestrictedZoneMonitor(zone_manager=self._zone_manager)

            gp = self.get_parameter
            self._blockage_detector = BlockageDetector(
                corridor_half_width_m=gp("blockage.corridor_half_width_m").get_parameter_value().double_value,
                corridor_length_m=gp("blockage.corridor_length_m").get_parameter_value().double_value,
                persistence_sec=gp("blockage.persistence_sec").get_parameter_value().double_value,
            )
            self._predictor = DynamicObstaclePredictor(
                horizon_sec=gp("prediction.horizon_sec").get_parameter_value().double_value,
                timestep_sec=gp("prediction.timestep_sec").get_parameter_value().double_value,
            )

            self.get_logger().info(
                "SpatialReasoningNode: configured (timeout=%.1fs, stop=%.2fm, slow=%.2fm, "
                "+ zone monitor, blockage detector, obstacle predictor)",
                timeout_sec, zones_cfg.stop_distance_m, zones_cfg.slow_distance_m,
            )
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error("on_configure failed: %s", str(exc))
            return TransitionCallbackReturn.FAILURE

        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        """Create subscriptions, publishers, services and the publish timer."""
        self.get_logger().info("SpatialReasoningNode: activating …")

        try:
            rate_hz = (
                self.get_parameter("publish_rate_hz").get_parameter_value().double_value
            )

            # Subscriptions.
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

            # Publishers.
            self._pub_entities = self.create_lifecycle_publisher(
                SpatialEntity,
                "/bonbon/spatial/entities",
                _QOS_RELIABLE,
            )
            self._pub_relations = self.create_lifecycle_publisher(
                SpatialRelation,
                "/bonbon/spatial/relations",
                _QOS_RELIABLE,
            )
            self._pub_hints = self.create_lifecycle_publisher(
                SocialNavigationHint,
                "/bonbon/spatial/hints",
                _QOS_RELIABLE,
            )
            self._pub_alerts = self.create_lifecycle_publisher(
                RiskEvent,
                "/bonbon/spatial/alerts",
                _QOS_RELIABLE,
            )
            self._pub_health = self.create_lifecycle_publisher(
                ModuleHealth,
                "/bonbon/spatial/spatial_reasoning_node/health",
                _QOS_RELIABLE,
            )

            # Services.
            self._srv_world_model = self.create_service(
                GetWorldModel,
                "~/get_world_model",
                self._handle_get_world_model,
            )
            self._srv_approach_pose = self.create_service(
                GetApproachPose,
                "~/get_approach_pose",
                self._handle_get_approach_pose,
            )
            self._srv_add_zone = self.create_service(
                AddRestrictedZone,
                "~/add_restricted_zone",
                self._handle_add_restricted_zone,
            )
            self._srv_remove_zone = self.create_service(
                RemoveRestrictedZone,
                "~/remove_restricted_zone",
                self._handle_remove_restricted_zone,
            )
            self._srv_health = self.create_service(
                HealthCheck,
                "~/health_check",
                self._handle_health_check,
            )

            # Publish timer.
            period_sec = 1.0 / max(rate_hz, 0.1)
            self._timer = self.create_timer(period_sec, self._cb_publish_timer)

            # Health timer (independent of the publish rate).
            health_hz = self.get_parameter("health_rate_hz").get_parameter_value().double_value
            self._health_timer = self.create_timer(
                1.0 / max(health_hz, 0.1), self._cb_health_timer
            )

            self.get_logger().info(
                "SpatialReasoningNode: active (publish rate=%.1f Hz, health=%.1f Hz)",
                rate_hz, health_hz,
            )
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error("on_activate failed: %s", str(exc))
            return TransitionCallbackReturn.FAILURE

        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        """Cancel timer and destroy subscriptions / publishers."""
        self.get_logger().info("SpatialReasoningNode: deactivating …")
        self._destroy_active_resources()
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        """Reset all runtime state."""
        self.get_logger().info("SpatialReasoningNode: cleaning up …")
        with self._lock:
            self._tracker = None
            self._estimator = None
            self._zone_manager = None
            self._hint_generator = None
            self._approach_planner = None
            self._zone_monitor = None
            self._blockage_detector = None
            self._predictor = None
            self._safety_state = None
            self._last_hint_type = ""
            self._privacy_mode = False
            self._last_blocked = False
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        """Handle graceful shutdown from any state."""
        self.get_logger().info("SpatialReasoningNode: shutting down …")
        self._destroy_active_resources()
        return TransitionCallbackReturn.SUCCESS

    # ------------------------------------------------------------------
    # Subscription callbacks
    # ------------------------------------------------------------------

    def _cb_persons(self, msg: PersonStateArray) -> None:
        """Handle incoming PersonStateArray from the vision pipeline."""
        if self._tracker is None:
            return
        with self._lock:
            for person in msg.persons:
                self._tracker.update_person(person)

    def _cb_safety(self, msg: SafetyState) -> None:
        """Cache the latest SafetyState for use in publishing decisions."""
        self._safety_state = msg
        # Privacy mode: do not expose person identity if safety state says so.
        # (No explicit privacy flag in SafetyState; callers can set via service.)

    # ------------------------------------------------------------------
    # Publish timer
    # ------------------------------------------------------------------

    def _cb_publish_timer(self) -> None:
        """Periodic callback: clean stale entities, publish state and hints."""
        if self._tracker is None:
            return
        cycle_start = time.monotonic()
        try:
            self._run_publish_cycle()
            self._cycle_count += 1
            self._last_cycle_t = time.monotonic()
            self._last_latency_ms = (self._last_cycle_t - cycle_start) * 1000.0
        except Exception as exc:  # noqa: BLE001
            self._error_count += 1
            self.get_logger().error("Spatial publish cycle failed: %s", str(exc))

    def _run_publish_cycle(self) -> None:
        """The actual per-cycle work (separated so the timer can wrap it)."""
        with self._lock:
            stale = self._tracker.cleanup_stale()
            if stale:
                self.get_logger().debug("Evicted stale entities: %s", stale)
            entities = self._tracker.get_all()
            entity_count = self._tracker.count()

        self.get_logger().debug("Spatial: %d entities tracked", entity_count)

        stamp = self.get_clock().now().to_msg()

        # Publish individual SpatialEntity messages.
        if self._pub_entities is not None and self._pub_entities.is_activated:
            for e in entities:
                ros_entity = self._tracked_entity_to_ros(e, stamp)
                self._pub_entities.publish(ros_entity)

        # Compute and publish SpatialRelation messages.
        if self._pub_relations is not None and self._pub_relations.is_activated:
            relations = self._compute_relations(entities, stamp)
            for rel in relations:
                self._pub_relations.publish(rel)

        # Derive and conditionally publish navigation hints.
        if (
            self._hint_generator is not None
            and self._pub_hints is not None
            and self._pub_hints.is_activated
        ):
            hints = self._hint_generator.evaluate_all(entities)
            critical = self._hint_generator.most_critical(hints)
            if critical is not None:
                # Only publish (and log) when hint type changes to avoid spam.
                if critical.hint_type != self._last_hint_type:
                    self.get_logger().info(
                        "Navigation hint: %s (urgency=%.2f) — %s",
                        critical.hint_type, critical.urgency, critical.reason,
                    )
                    ros_hint = self._hint_summary_to_ros(critical, stamp)
                    self._pub_hints.publish(ros_hint)
                    self._last_hint_type = critical.hint_type
            elif self._last_hint_type != "":
                # No entities → clear hint.
                self._last_hint_type = ""

        # Restricted-zone entry/exit alerts, blockage detection, and
        # dynamic-obstacle collision prediction.
        self._evaluate_alerts(entities, stamp)

    # ------------------------------------------------------------------
    # Alerting: restricted zones, blockage, obstacle prediction
    # ------------------------------------------------------------------

    def _evaluate_alerts(self, entities, stamp) -> None:
        """Run zone monitor, blockage detector and obstacle predictor; alert."""
        if self._pub_alerts is None or not self._pub_alerts.is_activated:
            return

        # 1. Restricted-zone entry/exit (edge-triggered).
        if self._zone_monitor is not None:
            for alert in self._zone_monitor.update(entities):
                if alert.alert_type != "entry":
                    continue
                self._publish_alert(
                    stamp,
                    risk_type="restricted_zone_entry",
                    severity=_SEV_HIGH,
                    subject_id=alert.person_id or alert.entity_id,
                    distance_m=alert.distance_m,
                    description=alert.description,
                    requires_action=True,
                    suggested_action="notify_operator",
                    confidence=0.95,
                )

        # 2. Forward-corridor blockage (state-triggered).
        if self._blockage_detector is not None:
            blockage = self._blockage_detector.update(entities)
            if blockage.is_blocked and not self._last_blocked:
                self.get_logger().warn("Path blockage: %s", blockage.reason)
                self._publish_alert(
                    stamp,
                    risk_type="path_blocked",
                    severity=_SEV_MEDIUM,
                    subject_id=",".join(blockage.blocking_entity_ids)[:64] or "scene",
                    distance_m=blockage.nearest_blocker_m,
                    description=blockage.reason,
                    requires_action=False,
                    suggested_action="reroute",
                    confidence=0.85,
                )
            self._last_blocked = blockage.is_blocked

        # 3. Dynamic-obstacle collision prediction.
        if self._predictor is not None and entities:
            preds = self._predictor.predict_all(entities)
            crit = self._predictor.most_critical(preds)
            if crit is not None and crit.risk_level in ("high", "medium"):
                sev = _SEV_HIGH if crit.risk_level == "high" else _SEV_MEDIUM
                self._publish_alert(
                    stamp,
                    risk_type="collision_risk",
                    severity=sev,
                    subject_id=crit.entity_id,
                    distance_m=crit.closest_distance_m,
                    description=(
                        f"predicted closest approach {crit.closest_distance_m:.2f}m "
                        f"in {crit.time_to_closest_sec:.1f}s"
                    ),
                    requires_action=(crit.risk_level == "high"),
                    suggested_action="slow_down" if crit.risk_level == "medium" else "stop",
                    confidence=0.8,
                )

    def _publish_alert(
        self,
        stamp,
        *,
        risk_type: str,
        severity: int,
        subject_id: str,
        distance_m: float,
        description: str,
        requires_action: bool,
        suggested_action: str,
        confidence: float,
    ) -> None:
        """Build and publish a :class:`bonbon_msgs/RiskEvent`."""
        import uuid as _uuid

        labels = {0: "info", 1: "low", 2: "medium", 3: "high", 4: "critical"}
        msg = RiskEvent()
        msg.header = Header()
        msg.header.stamp = stamp
        msg.header.frame_id = "base_link"
        msg.risk_id = str(_uuid.uuid4())[:8]
        msg.severity = severity
        msg.severity_label = labels.get(severity, "info")
        msg.risk_type = risk_type
        msg.confidence = float(confidence)
        msg.subject_id = subject_id
        msg.distance_m = float(distance_m)
        msg.description = description
        msg.requires_immediate_action = requires_action
        msg.suggested_action = suggested_action
        self._pub_alerts.publish(msg)

    # ------------------------------------------------------------------
    # Health monitoring / diagnostics
    # ------------------------------------------------------------------

    def _health_status(self) -> tuple:
        """Compute (status, text) from current telemetry."""
        now = time.monotonic()
        # STALE if the publish cycle has not run within 3× its period.
        if self._last_cycle_t and (now - self._last_cycle_t) > 3.0:
            return _HEALTH_STALE, "publish cycle stalled"
        if self._error_count > 0 and self._cycle_count == 0:
            return _HEALTH_ERROR, "all publish cycles failing"
        if self._error_count > 0:
            return _HEALTH_WARN, f"{self._error_count} cycle error(s)"
        if self._tracker is None:
            return _HEALTH_WARN, "not configured"
        return _HEALTH_OK, "nominal"

    def _cb_health_timer(self) -> None:
        """Publish a ModuleHealth heartbeat."""
        if self._pub_health is None or not self._pub_health.is_activated:
            return
        status, text = self._health_status()
        msg = ModuleHealth()
        msg.header = _now_header(self, "base_link")
        msg.module_name = "bonbon_spatial.spatial_reasoning_node"
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

    def _handle_health_check(
        self,
        request: HealthCheck.Request,
        response: HealthCheck.Response,
    ) -> HealthCheck.Response:
        """Synchronous health query (bonbon_srvs/HealthCheck)."""
        status, text = self._health_status()
        response.healthy = status in (_HEALTH_OK, _HEALTH_WARN)
        response.status = text
        response.warnings = [text] if status == _HEALTH_WARN else []
        response.errors = [text] if status in (_HEALTH_ERROR, _HEALTH_STALE) else []
        response.uptime_sec = float(time.monotonic() - self._node_start)
        return response

    # ------------------------------------------------------------------
    # Service handlers
    # ------------------------------------------------------------------

    def _handle_get_world_model(
        self,
        request: GetWorldModel.Request,
        response: GetWorldModel.Response,
    ) -> GetWorldModel.Response:
        """Return the current world model snapshot."""
        if self._tracker is None or self._zone_manager is None:
            response.success = False
            response.error_message = "Node not configured"
            return response

        stamp = self.get_clock().now().to_msg()

        with self._lock:
            entities = self._tracker.get_all()

        response.success = True
        response.entities = [self._tracked_entity_to_ros(e, stamp) for e in entities]

        if request.include_relations:
            response.relations = self._compute_relations(entities, stamp)
        else:
            response.relations = []

        if request.include_zones:
            response.zone_ids = self._zone_manager.get_all_zone_ids()
        else:
            response.zone_ids = []

        self.get_logger().debug(
            "GetWorldModel: %d entities, %d relations, %d zones",
            len(response.entities), len(response.relations), len(response.zone_ids),
        )
        return response

    def _handle_get_approach_pose(
        self,
        request: GetApproachPose.Request,
        response: GetApproachPose.Response,
    ) -> GetApproachPose.Response:
        """Compute an approach pose for a specified person."""
        if self._tracker is None or self._approach_planner is None:
            response.success = False
            response.error_message = "Node not configured"
            return response

        with self._lock:
            entity: Optional[TrackedEntity] = None
            if request.tracking_id > 0:
                entity = self._tracker.get_by_tracking_id(request.tracking_id)
            if entity is None and request.person_id:
                # Try matching by entity_id constructed from person_id.
                entity = self._tracker.get_by_id(f"person_{request.person_id}")
            if entity is None and request.person_id:
                # Last resort: search all entities by person_id field.
                for e in self._tracker.get_all():
                    if e.person_id == request.person_id:
                        entity = e
                        break

        if entity is None:
            response.success = False
            response.error_message = (
                f"Entity not found: person_id='{request.person_id}' "
                f"tracking_id={request.tracking_id}"
            )
            return response

        success, tx, ty, tyaw, msg = self._approach_planner.plan(
            entity=entity,
            desired_distance_m=float(request.desired_distance_m),
            approach_style=request.approach_style or "front",
        )

        pose_stamped = PoseStamped()
        pose_stamped.header = _now_header(self, "map")
        pose_stamped.pose.position.x = tx
        pose_stamped.pose.position.y = ty
        pose_stamped.pose.position.z = 0.0
        pose_stamped.pose.orientation = _yaw_to_quaternion(tyaw)

        response.success = success
        response.approach_pose = pose_stamped
        response.reason = msg
        response.error_message = "" if success else msg
        return response

    def _handle_add_restricted_zone(
        self,
        request: AddRestrictedZone.Request,
        response: AddRestrictedZone.Response,
    ) -> AddRestrictedZone.Response:
        """Add a dynamic restricted zone from a service request."""
        if self._zone_manager is None:
            response.success = False
            response.error_message = "Node not configured"
            return response

        # Convert geometry_msgs/Polygon to list of (x, y) tuples.
        try:
            polygon = [
                (float(pt.x), float(pt.y))
                for pt in request.polygon.points
            ]
            if len(polygon) < 3:
                response.success = False
                response.error_message = (
                    f"Zone '{request.zone_id}' polygon must have at least 3 points."
                )
                return response

            zone = SemanticZone(
                zone_id=request.zone_id,
                zone_type="restricted",
                polygon=polygon,
                min_clearance_m=float(request.buffer_m),
                reason=request.reason,
                is_dynamic=True,
            )
            with self._lock:
                self._zone_manager.add_zone(zone)

            self.get_logger().info(
                "Added restricted zone '%s' (buffer=%.2fm, reason='%s')",
                request.zone_id, request.buffer_m, request.reason,
            )
            response.success = True
            response.error_message = ""
        except Exception as exc:  # noqa: BLE001
            response.success = False
            response.error_message = f"Failed to add zone: {exc}"
            self.get_logger().error(
                "add_restricted_zone error: %s", str(exc)
            )

        return response

    def _handle_remove_restricted_zone(
        self,
        request: RemoveRestrictedZone.Request,
        response: RemoveRestrictedZone.Response,
    ) -> RemoveRestrictedZone.Response:
        """Remove a previously added zone."""
        if self._zone_manager is None:
            response.success = False
            response.error_message = "Node not configured"
            return response

        with self._lock:
            removed = self._zone_manager.remove_zone(request.zone_id)

        if removed:
            self.get_logger().info("Removed zone '%s'", request.zone_id)
            response.success = True
            response.error_message = ""
        else:
            response.success = False
            response.error_message = f"Zone '{request.zone_id}' not found"

        return response

    # ------------------------------------------------------------------
    # Message construction helpers
    # ------------------------------------------------------------------

    def _tracked_entity_to_ros(
        self, entity: TrackedEntity, stamp: BuiltinTime
    ) -> SpatialEntity:
        """Convert a :class:`TrackedEntity` to a ``SpatialEntity`` ROS message.

        When privacy mode is active, ``person_id`` and ``face_id`` fields are
        redacted to protect personally-identifying information.
        """
        msg = SpatialEntity()
        msg.header = Header()
        msg.header.stamp = stamp
        msg.header.frame_id = "map"
        msg.event_id = str(uuid.uuid4())
        msg.observed_at = stamp
        msg.source_module = _SOURCE_MODULE
        msg.entity_id = entity.entity_id
        msg.entity_type = entity.entity_type

        # Redact person identity in privacy mode.
        if self._privacy_mode:
            msg.person_id = ""
        else:
            msg.person_id = entity.person_id

        msg.tracking_id = entity.tracking_id

        # Pose.
        ps = PoseStamped()
        ps.header = msg.header
        ps.pose.position.x = entity.x
        ps.pose.position.y = entity.y
        ps.pose.position.z = entity.z
        ps.pose.orientation.w = 1.0
        msg.pose = ps

        # Velocity.
        vel = Vector3()
        vel.x = entity.vx
        vel.y = entity.vy
        vel.z = 0.0
        msg.velocity_mps = vel

        # Zone assignment.
        if self._zone_manager is not None:
            zone_id = self._zone_manager.find_zone_for_point(entity.x, entity.y)
            msg.zone_id = zone_id or ""
        else:
            msg.zone_id = entity.zone_id

        msg.is_static = False
        msg.is_occluded = False
        msg.confidence = entity.confidence
        msg.time_since_last_obs_sec = 0.0  # freshly received
        msg.person_category = entity.person_category
        msg.is_approaching_robot = entity.is_approaching_robot
        msg.is_moving_away = entity.is_moving_away
        msg.approach_speed_mps = entity.approach_speed_mps
        return msg

    def _compute_relations(
        self, entities: List[TrackedEntity], stamp: BuiltinTime
    ) -> List[SpatialRelation]:
        """Compute pairwise :class:`SpatialRelation` messages for all entities.

        Pairs with distance > 10 m are skipped to keep message volume bounded.
        The robot itself is treated as entity_a_id = "robot".
        """
        relations: List[SpatialRelation] = []

        # Robot-to-person relations.
        for e in entities:
            rel = SpatialRelation()
            rel.header = Header()
            rel.header.stamp = stamp
            rel.header.frame_id = "map"
            rel.event_id = str(uuid.uuid4())
            rel.computed_at = stamp
            rel.source_module = _SOURCE_MODULE
            rel.entity_a_id = "robot"
            rel.entity_b_id = e.entity_id
            d = e.distance_to_robot
            rel.distance_m = d
            rel.bearing_deg = math.degrees(math.atan2(e.y, e.x))

            if e.is_approaching_robot:
                rel.relation_type = "approaching"
            elif e.is_moving_away:
                rel.relation_type = "retreating"
            elif d < 1.5:
                rel.relation_type = "near"
            else:
                rel.relation_type = "far"

            # Personal-space violation check.
            if self._estimator is not None:
                space = self._estimator.estimate(d, e.person_category)
                rel.is_violating_personal_space = space.is_too_close
            else:
                rel.is_violating_personal_space = False

            # Restricted-zone check for the entity's current position.
            if self._zone_manager is not None:
                zone_id = self._zone_manager.find_zone_for_point(e.x, e.y)
                rel.is_in_restricted_zone = (
                    zone_id is not None and self._zone_manager.is_restricted(zone_id)
                )
            else:
                rel.is_in_restricted_zone = False

            rel.is_blocking_path = rel.is_violating_personal_space
            rel.confidence = e.confidence
            relations.append(rel)

        # Person-to-person relations (only when few people to avoid O(n²) spam).
        if len(entities) <= 6:
            for i, ea in enumerate(entities):
                for eb in entities[i + 1 :]:
                    dx = ea.x - eb.x
                    dy = ea.y - eb.y
                    d = math.sqrt(dx ** 2 + dy ** 2)
                    if d > 10.0:
                        continue
                    rel = SpatialRelation()
                    rel.header = Header()
                    rel.header.stamp = stamp
                    rel.header.frame_id = "map"
                    rel.event_id = str(uuid.uuid4())
                    rel.computed_at = stamp
                    rel.source_module = _SOURCE_MODULE
                    rel.entity_a_id = ea.entity_id
                    rel.entity_b_id = eb.entity_id
                    rel.distance_m = d
                    rel.bearing_deg = math.degrees(math.atan2(dy, dx))
                    rel.relation_type = "near" if d < 2.0 else "far"
                    rel.is_violating_personal_space = False
                    rel.is_blocking_path = False
                    rel.is_in_restricted_zone = False
                    rel.confidence = min(ea.confidence, eb.confidence)
                    relations.append(rel)

        return relations

    def _hint_summary_to_ros(
        self, hint: HintSummary, stamp: BuiltinTime
    ) -> SocialNavigationHint:
        """Convert a :class:`HintSummary` to a ``SocialNavigationHint`` ROS message."""
        msg = SocialNavigationHint()
        msg.header = Header()
        msg.header.stamp = stamp
        msg.header.frame_id = "map"
        msg.event_id = str(uuid.uuid4())
        msg.generated_at = stamp
        msg.source_module = _SOURCE_MODULE
        msg.hint_type = hint.hint_type
        msg.urgency = hint.urgency
        msg.reason = hint.reason
        msg.affected_entity_id = hint.affected_entity_id
        msg.suggested_max_vel_mps = hint.suggested_max_vel_mps
        msg.suggested_distance_m = hint.suggested_distance_m
        msg.requires_navigation_replan = hint.requires_navigation_replan
        msg.requires_behavior_response = hint.requires_behavior_response
        msg.requires_tts_announcement = hint.requires_tts_announcement
        msg.suggested_tts_text = hint.suggested_tts_text
        # Leave suggested_pose as default (zero pose) — pose planning is via service.
        msg.suggested_pose = Pose()
        msg.suggested_pose.orientation.w = 1.0
        return msg

    # ------------------------------------------------------------------
    # Teardown helpers
    # ------------------------------------------------------------------

    def _destroy_active_resources(self) -> None:
        """Cancel timer and destroy subscriptions / publishers / services."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._health_timer is not None:
            self._health_timer.cancel()
            self._health_timer = None

        for attr in (
            "_sub_persons",
            "_sub_safety",
            "_pub_entities",
            "_pub_relations",
            "_pub_hints",
            "_pub_alerts",
            "_pub_health",
            "_srv_world_model",
            "_srv_approach_pose",
            "_srv_add_zone",
            "_srv_remove_zone",
            "_srv_health",
        ):
            resource = getattr(self, attr, None)
            if resource is not None:
                try:
                    self.destroy_publisher(resource)  # type: ignore[arg-type]
                except Exception:  # noqa: BLE001
                    try:
                        self.destroy_subscription(resource)  # type: ignore[arg-type]
                    except Exception:  # noqa: BLE001
                        try:
                            self.destroy_service(resource)  # type: ignore[arg-type]
                        except Exception:  # noqa: BLE001
                            pass
                setattr(self, attr, None)


def main(args=None) -> None:
    """Entry point for the spatial_reasoning_node executable."""
    rclpy.init(args=args)
    node = SpatialReasoningNode("spatial_reasoning_node")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
