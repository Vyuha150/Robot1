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
    PersonStateArray,
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
)

# Core components
from bonbon_spatial.core.entity_tracker import EntityTracker, TrackedEntity
from bonbon_spatial.core.personal_space_estimator import (
    PersonalSpaceEstimator,
    ProxemicZones,
)
from bonbon_spatial.core.semantic_zone_manager import SemanticZone, SemanticZoneManager
from bonbon_spatial.core.social_navigation_hints import SocialNavigationHints, HintSummary
from bonbon_spatial.core.approach_pose_planner import ApproachPosePlanner

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

        # Core components — initialised in on_configure.
        self._tracker: Optional[EntityTracker] = None
        self._estimator: Optional[PersonalSpaceEstimator] = None
        self._zone_manager: Optional[SemanticZoneManager] = None
        self._hint_generator: Optional[SocialNavigationHints] = None
        self._approach_planner: Optional[ApproachPosePlanner] = None

        # ROS2 infrastructure — initialised in on_activate.
        self._sub_persons = None
        self._sub_safety = None
        self._pub_entities: Optional[LifecyclePublisher] = None
        self._pub_relations: Optional[LifecyclePublisher] = None
        self._pub_hints: Optional[LifecyclePublisher] = None
        self._srv_world_model = None
        self._srv_approach_pose = None
        self._srv_add_zone = None
        self._srv_remove_zone = None
        self._timer = None

        # Runtime state.
        self._lock = threading.Lock()
        self._safety_state: Optional[SafetyState] = None
        self._last_hint_type: str = ""
        self._privacy_mode: bool = False

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

            self.get_logger().info(
                "SpatialReasoningNode: configured (timeout=%.1fs, stop=%.2fm, slow=%.2fm)",
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

            # Publish timer.
            period_sec = 1.0 / max(rate_hz, 0.1)
            self._timer = self.create_timer(period_sec, self._cb_publish_timer)

            self.get_logger().info(
                "SpatialReasoningNode: active (publish rate=%.1f Hz)", rate_hz
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
            self._safety_state = None
            self._last_hint_type = ""
            self._privacy_mode = False
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

        with self._lock:
            stale = self._tracker.cleanup_stale()
            if stale:
                self.get_logger().debug("Evicted stale entities: %s", stale)
            entities = self._tracker.get_all()
            entity_count = self._tracker.count()

        self.get_logger().info(
            "Spatial: %d entities tracked", entity_count
        )

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

        for attr in (
            "_sub_persons",
            "_sub_safety",
            "_pub_entities",
            "_pub_relations",
            "_pub_hints",
            "_srv_world_model",
            "_srv_approach_pose",
            "_srv_add_zone",
            "_srv_remove_zone",
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
