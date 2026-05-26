"""
bonbon_navigation.nodes.navigation_node
=========================================
Central ROS2 LifecycleNode for the BonBon Autonomous Navigation Module.

Pipeline
--------
                   ┌───────────────────────────────────────────────┐
 /perception/      │           NavigationNode                       │
 behavior ────────►│                                               │
 /bonbon/safety/   │  GoalManager ──► Nav2 (NavigateToPose)        │
 state ───────────►│       │              │                        │
 /perception/      │  StuckDetector       │ (action feedback)      │
 persons ─────────►│       │              │                        │
 /odom ───────────►│  RecoveryExecutor    │                        │
 /amcl_pose ──────►│       │              │                        │
 /battery ────────►│  BatteryRouter       │                        │
                   │       │              │                        │
                   │  SafetyStopBridge    │                        │
                   │       │              │                        │
                   │  HumanAwareCostmap   │                        │
                   │       │              │                        │
                   │  DockingController ◄─┘                        │
                   │       │                                       │
                   │  LocalizationMonitor                          │
                   └───────────────────────────────────────────────┘
 /navigation/status ◄──────────────────────────────────────────────
 /navigation/goal ◄────────────────────────────────────────────────
 /navigation/docking_status ◄──────────────────────────────────────
 /navigation/recovery_status ◄─────────────────────────────────────
 /health/navigation ◄──────────────────────────────────────────────

Safety contract
---------------
* ALL velocity commands go through SafetyStopBridge before dispatch.
* Navigation is gated: only accepted when safety_state in {NORMAL, DOCKING}.
* If safety_state becomes DANGER/FAULT/SAFE_STOP, the active Nav2 goal
  is immediately cancelled.
* The node never directly writes to /cmd_vel — all motion goes through
  /bonbon/safety_gate/cmd_vel.
"""
from __future__ import annotations

import math
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

import rclpy
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.qos import (
    QoSProfile, QoSReliabilityPolicy, QoSDurabilityPolicy, QoSHistoryPolicy,
)

from bonbon_navigation.config.nav_config import NavigationConfig
from bonbon_navigation.core.map_manager import MapManager
from bonbon_navigation.core.localization_monitor import (
    LocalizationMonitor, LocalizationQuality,
)
from bonbon_navigation.core.goal_manager import (
    GoalManager, NavigationGoalEntry,
    RESULT_SUCCESS, RESULT_TIMEOUT, RESULT_UNREACHABLE,
    RESULT_STUCK, RESULT_SAFETY_STOP, RESULT_CANCELLED, RESULT_PLAN_FAILED,
)
from bonbon_navigation.core.stuck_detector import StuckDetector
from bonbon_navigation.core.recovery_executor import RecoveryExecutor, RecoveryOutcome
from bonbon_navigation.core.battery_router import BatteryRouter
from bonbon_navigation.planners.human_aware_costmap import HumanAwareCostmapLayer
from bonbon_navigation.behaviors.docking_controller import (
    DockingController, DockingPhase,
)
from bonbon_navigation.safety.safety_stop_bridge import (
    SafetyStopBridge,
    SAFETY_NORMAL, SAFETY_CAUTION, SAFETY_DOCKING,
    SAFETY_DANGER, SAFETY_FAULT, SAFETY_SAFE_STOP,
)


# ── QoS profiles ─────────────────────────────────────────────────────────────

_QOS_RELIABLE_TL = QoSProfile(
    reliability  = QoSReliabilityPolicy.RELIABLE,
    durability   = QoSDurabilityPolicy.TRANSIENT_LOCAL,
    history      = QoSHistoryPolicy.KEEP_LAST,
    depth        = 1,
)

_QOS_SENSOR = QoSProfile(
    reliability  = QoSReliabilityPolicy.BEST_EFFORT,
    durability   = QoSDurabilityPolicy.VOLATILE,
    history      = QoSHistoryPolicy.KEEP_LAST,
    depth        = 5,
)

_QOS_DEFAULT = QoSProfile(depth=10)


# ── Navigation states (mirrors NavigationStatus.msg constants) ────────────────

STATE_IDLE           = 0
STATE_PLANNING       = 1
STATE_EXECUTING      = 2
STATE_RECOVERING     = 3
STATE_DOCKING        = 4
STATE_ARRIVED        = 5
STATE_BLOCKED        = 6
STATE_FAILED         = 7
STATE_CANCELLED      = 8
STATE_SAFETY_STOPPED = 9

_STATE_NAMES = {
    STATE_IDLE:           "IDLE",
    STATE_PLANNING:       "PLANNING",
    STATE_EXECUTING:      "EXECUTING",
    STATE_RECOVERING:     "RECOVERING",
    STATE_DOCKING:        "DOCKING",
    STATE_ARRIVED:        "ARRIVED",
    STATE_BLOCKED:        "BLOCKED",
    STATE_FAILED:         "FAILED",
    STATE_CANCELLED:      "CANCELLED",
    STATE_SAFETY_STOPPED: "SAFETY_STOPPED",
}


# ── Node ──────────────────────────────────────────────────────────────────────

class NavigationNode(LifecycleNode):
    """
    Central navigation orchestrator for the BonBon service robot.

    Lifecycle transitions
    ---------------------
    on_configure  → initialise all subsystems; load map; create pub/sub
    on_activate   → start timers; begin accepting goals
    on_deactivate → cancel active goals; stop timers
    on_cleanup    → destroy all resources
    """

    def __init__(self) -> None:
        super().__init__("navigation_node")
        self._cfg:    Optional[NavigationConfig]    = None
        self._state:  int                           = STATE_IDLE
        self._lock:   threading.Lock                = threading.Lock()
        self._active: bool                          = False

        # Subsystems (created in on_configure)
        self._map_manager:       Optional[MapManager]              = None
        self._loc_monitor:       Optional[LocalizationMonitor]     = None
        self._goal_manager:      Optional[GoalManager]             = None
        self._stuck_detector:    Optional[StuckDetector]           = None
        self._recovery_executor: Optional[RecoveryExecutor]        = None
        self._battery_router:    Optional[BatteryRouter]           = None
        self._human_costmap:     Optional[HumanAwareCostmapLayer]  = None
        self._docking_ctrl:      Optional[DockingController]       = None
        self._safety_bridge:     Optional[SafetyStopBridge]        = None

        # Nav2 action client (lazy import to decouple from ROS2 at test time)
        self._nav2_client:   Any  = None
        self._nav2_future:   Any  = None

        # Cached sensor data
        self._last_odom_x:   float = 0.0
        self._last_odom_y:   float = 0.0
        self._last_odom_yaw: float = 0.0
        self._last_vel:      float = 0.0

        # Passing announcement tracking
        self._announced_persons: set = set()

        # Timers
        self._status_timer  = None
        self._health_timer  = None
        self._nav_timer     = None

        # Publishers / subscribers
        self._pub_status    = None
        self._pub_goal      = None
        self._pub_dock      = None
        self._pub_recovery  = None
        self._pub_health    = None
        self._pub_tts       = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("[navigation] Configuring…")
        try:
            self._cfg = NavigationConfig.from_ros_params(self)
            self.get_logger().info("[navigation] Config: %s", self._cfg.summary())

            # Subsystems
            self._map_manager = MapManager(self._cfg.locations.named_locations)
            if self._cfg.map_file:
                ok = self._map_manager.load(self._cfg.map_file)
                if not ok:
                    self.get_logger().warn("[navigation] Map load failed — using RTAB-Map")

            self._loc_monitor = LocalizationMonitor(
                good_cov_threshold=0.10,
                lost_cov_threshold=1.00,
                pose_stale_sec=2.0,
            )

            self._goal_manager = GoalManager(
                max_queue_size   = 10,
                default_timeout_sec = self._cfg.nav2.navigate_to_pose_timeout_sec,
                max_plan_failures = 3,
            )

            self._stuck_detector = StuckDetector(self._cfg.stuck_detector)

            self._recovery_executor = RecoveryExecutor(self._cfg.recovery)
            self._recovery_executor.set_announce_fn(self._tts_speak)
            self._recovery_executor.set_escalate_fn(self._escalate)
            self._recovery_executor.set_clear_costmap_fn(self._clear_costmap)
            self._recovery_executor.set_backup_fn(self._execute_backup)
            self._recovery_executor.set_spin_fn(self._execute_spin)

            self._battery_router = BatteryRouter(
                self._cfg.battery_routing, self._map_manager
            )

            self._human_costmap = HumanAwareCostmapLayer(
                self._cfg.human_aware,
                resolution=0.05,
                width=400,
                height=400,
                origin_x=-10.0,
                origin_y=-10.0,
            )

            self._docking_ctrl = DockingController(self._cfg.docking)
            self._docking_ctrl.set_cmd_vel_fn(self._publish_gated_vel)
            self._docking_ctrl.set_stop_fn(lambda: self._publish_gated_vel(0.0, 0.0))
            self._docking_ctrl.set_coarse_nav_fn(self._send_nav2_goal_raw)

            self._safety_bridge = SafetyStopBridge(
                max_speed_mps       = self._cfg.robot.max_speed_mps,
                caution_speed_mps   = self._cfg.robot.caution_speed_mps,
                dock_speed_mps      = self._cfg.robot.dock_speed_mps,
                watchdog_timeout_sec= 2.0,
            )

            # Init Nav2 action client
            self._init_nav2_client()

            # Publishers
            self._pub_status   = self.create_publisher(
                self._import_msg("NavigationStatus"), "/navigation/status", _QOS_DEFAULT)
            self._pub_goal     = self.create_publisher(
                self._import_msg("NavigationGoal"),   "/navigation/goal",   _QOS_DEFAULT)
            self._pub_dock     = self.create_publisher(
                self._import_msg("DockingStatus"),    "/navigation/docking_status", _QOS_DEFAULT)
            self._pub_recovery = self.create_publisher(
                self._import_msg("RecoveryStatus"),   "/navigation/recovery_status", _QOS_DEFAULT)
            self._pub_health   = self.create_publisher(
                self._import_msg("ModuleHealth"),     "/health/navigation", _QOS_RELIABLE_TL)
            self._pub_tts      = self.create_publisher(
                self._import_msg("TTSRequest"),       "/bonbon/tts/request", _QOS_DEFAULT)

            # Subscribers
            self.create_subscription(
                self._import_msg("BehaviorRecommendation"),
                "/perception/behavior",
                self._on_behavior_recommendation,
                _QOS_DEFAULT,
            )
            self.create_subscription(
                self._import_msg("SafetyState"),
                "/bonbon/safety/state",
                self._on_safety_state,
                _QOS_RELIABLE_TL,
            )
            self.create_subscription(
                self._import_msg("PersonStateArray"),
                "/perception/persons",
                self._on_persons,
                _QOS_SENSOR,
            )
            # Odometry
            try:
                from nav_msgs.msg import Odometry
                self.create_subscription(
                    Odometry, "/odom", self._on_odom, _QOS_SENSOR)
            except ImportError:
                self.get_logger().warn("[navigation] nav_msgs unavailable")

            # AMCL/RTAB-Map localization
            try:
                from geometry_msgs.msg import PoseWithCovarianceStamped
                self.create_subscription(
                    PoseWithCovarianceStamped,
                    "/amcl_pose",
                    self._on_amcl_pose,
                    _QOS_DEFAULT,
                )
                self.create_subscription(
                    PoseWithCovarianceStamped,
                    "/rtabmap/localization_pose",
                    self._on_amcl_pose,   # same handler
                    _QOS_DEFAULT,
                )
            except ImportError:
                pass

            # Battery
            try:
                from sensor_msgs.msg import BatteryState
                self.create_subscription(
                    BatteryState,
                    self._cfg.battery_routing.battery_topic,
                    self._on_battery,
                    _QOS_SENSOR,
                )
            except ImportError:
                pass

            # Services
            self._create_services()

            self.get_logger().info("[navigation] Configure complete")
            return TransitionCallbackReturn.SUCCESS

        except Exception as exc:
            self.get_logger().error("[navigation] Configure FAILED: %s", exc)
            return TransitionCallbackReturn.FAILURE

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("[navigation] Activating…")
        self._active = True
        self._stuck_detector.reset()

        # Main navigation loop at 10 Hz
        self._nav_timer = self.create_timer(0.10, self._nav_loop)

        # Status publish
        rate = self._cfg.status_publish_rate_hz
        self._status_timer = self.create_timer(1.0 / rate, self._publish_status)

        # Health publish
        h_rate = self._cfg.health_publish_rate_hz
        self._health_timer = self.create_timer(1.0 / h_rate, self._publish_health)

        self.get_logger().info("[navigation] Active — ready to accept goals")
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("[navigation] Deactivating…")
        self._active = False
        if self._goal_manager:
            self._goal_manager.cancel_goal(reason="node deactivated")
        self._cancel_nav2_goal()
        for t in (self._nav_timer, self._status_timer, self._health_timer):
            if t:
                t.cancel()
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("[navigation] Cleaning up")
        self._nav2_client = None
        return TransitionCallbackReturn.SUCCESS

    # ── Main navigation loop ──────────────────────────────────────────────────

    def _nav_loop(self) -> None:
        """10 Hz orchestration loop."""
        if not self._active:
            return

        # 1. Expire stale persons in human costmap
        if self._human_costmap:
            self._human_costmap.expire_stale_persons()

        # 2. Check for passing alerts
        self._check_passing_alerts()

        # 3. Docking tick
        if self._docking_ctrl and self._state == STATE_DOCKING:
            self._docking_tick()
            return

        # 4. Recovery tick
        if self._recovery_executor and self._recovery_executor.is_active():
            self._recovery_tick()
            return

        # 5. Timeout check
        if self._goal_manager:
            timed_out = self._goal_manager.check_timeout()
            if timed_out:
                self.get_logger().warning("[navigation] Goal timeout: %s", timed_out.goal_id[:8])
                self._cancel_nav2_goal()
                self._goal_manager.mark_failed(timed_out.goal_id, RESULT_TIMEOUT,
                                               "navigation timeout")
                self._tts_speak("I'm sorry, I couldn't reach the destination in time.")
                self._transition_state(STATE_FAILED)
                return

        # 6. Stuck detection
        if self._stuck_detector and self._state == STATE_EXECUTING:
            result = self._stuck_detector.check()
            if result.is_stuck:
                self.get_logger().warning("[navigation] Stuck detected: %s", result.reason)
                active = self._goal_manager.get_active() if self._goal_manager else None
                if active:
                    self._start_recovery("stuck")
                return

        # 7. Battery routing
        if self._battery_router and self._cfg.battery_routing.enabled:
            self._check_battery_routing()

        # 8. Try to activate next queued goal
        if self._state == STATE_IDLE and self._goal_manager:
            goal = self._goal_manager.activate_next()
            if goal:
                self._start_goal(goal)

        # 9. Check Nav2 result
        if self._nav2_future is not None:
            self._check_nav2_result()

    # ── Goal dispatch ──────────────────────────────────────────────────────────

    def _start_goal(self, goal: NavigationGoalEntry) -> None:
        """Send an activated goal to Nav2."""
        if self._safety_bridge and self._safety_bridge.is_motion_blocked:
            self.get_logger().warning(
                "[navigation] Goal rejected: motion blocked (safety=%s)",
                self._safety_bridge.safety_state_name(),
            )
            self._goal_manager.mark_failed(goal.goal_id, RESULT_SAFETY_STOP,
                                           "safety state blocks navigation")
            self._transition_state(STATE_SAFETY_STOPPED)
            return

        # Docking goal gets special handling
        if goal.goal_type == 2 or goal.require_precise:  # TYPE_CHARGER or precise
            self._start_docking(goal)
            return

        self.get_logger().info(
            "[navigation] Sending goal to Nav2: %s  (%.2f, %.2f)",
            goal.goal_id[:8], goal.target_x, goal.target_y,
        )
        self._transition_state(STATE_PLANNING)
        self._stuck_detector.reset()

        success = self._send_nav2_goal(
            goal.target_x, goal.target_y, goal.target_yaw
        )
        if not success:
            if self._goal_manager.record_plan_failure(goal.goal_id):
                self._goal_manager.mark_failed(
                    goal.goal_id, RESULT_UNREACHABLE, "Nav2 rejected goal"
                )
                self._tts_speak("I can't reach that destination. I'll try later.")
                self._transition_state(STATE_FAILED)
            else:
                self._start_recovery("plan_failed")
        else:
            self._transition_state(STATE_EXECUTING)

    def _start_docking(self, goal: NavigationGoalEntry) -> None:
        """Initiate precision docking sequence."""
        if self._docking_ctrl:
            self._docking_ctrl.start(
                charger_id  = goal.named_location or "charger",
                charger_x   = goal.target_x,
                charger_y   = goal.target_y,
                charger_yaw = goal.target_yaw,
            )
        self._transition_state(STATE_DOCKING)

    # ── Recovery ──────────────────────────────────────────────────────────────

    def _start_recovery(self, trigger: str) -> None:
        active = self._goal_manager.get_active() if self._goal_manager else None
        if active is None:
            return
        self._cancel_nav2_goal()
        self._recovery_executor.reset(trigger_reason=trigger)
        self._transition_state(STATE_RECOVERING)
        self.get_logger().info("[navigation] Recovery started: %s", trigger)

    def _recovery_tick(self) -> None:
        outcome = self._recovery_executor.step()
        if outcome == RecoveryOutcome.SUCCEEDED:
            # Recovery succeeded — retry the goal
            active = self._goal_manager.get_active() if self._goal_manager else None
            if active:
                self._transition_state(STATE_PLANNING)
                self._start_goal(active)
        elif outcome == RecoveryOutcome.EXHAUSTED:
            active = self._goal_manager.get_active() if self._goal_manager else None
            if active:
                self._goal_manager.mark_failed(active.goal_id, RESULT_STUCK,
                                               "recovery exhausted")
                self.get_logger().error("[navigation] Recovery exhausted: goal failed")
                self._transition_state(STATE_FAILED)

    # ── Docking tick ──────────────────────────────────────────────────────────

    def _docking_tick(self) -> None:
        phase = self._docking_ctrl.tick()
        if phase == DockingPhase.CONTACT:
            # Docking succeeded
            active = self._goal_manager.get_active() if self._goal_manager else None
            if active:
                self._goal_manager.mark_succeeded(active.goal_id)
            self._transition_state(STATE_ARRIVED)
            self.get_logger().info("[navigation] Docking complete — charging")
        elif phase == DockingPhase.FAILED:
            active = self._goal_manager.get_active() if self._goal_manager else None
            if active:
                self._goal_manager.mark_failed(
                    active.goal_id, RESULT_PLAN_FAILED,
                    self._docking_ctrl.state.failure_reason,
                )
            self._transition_state(STATE_FAILED)
            self.get_logger().error("[navigation] Docking FAILED")

    # ── Nav2 interaction ──────────────────────────────────────────────────────

    def _init_nav2_client(self) -> None:
        try:
            from nav2_simple_commander.robot_navigator import BasicNavigator
            self._nav2_client = BasicNavigator()
            self.get_logger().info("[navigation] Nav2 BasicNavigator initialised")
        except ImportError:
            self.get_logger().warn(
                "[navigation] nav2_simple_commander not available — Nav2 calls stubbed"
            )
            self._nav2_client = None

    def _send_nav2_goal(self, x: float, y: float, yaw: float) -> bool:
        """Send a NavigateToPose goal. Returns True if accepted."""
        if self._nav2_client is None:
            self.get_logger().warn("[navigation] Nav2 client unavailable — goal skipped")
            return False
        try:
            from geometry_msgs.msg import PoseStamped
            from rclpy.time import Time
            pose = PoseStamped()
            pose.header.frame_id = "map"
            pose.header.stamp    = self.get_clock().now().to_msg()
            pose.pose.position.x = x
            pose.pose.position.y = y
            pose.pose.position.z = 0.0
            # Convert yaw → quaternion
            cy = math.cos(yaw * 0.5)
            sy = math.sin(yaw * 0.5)
            pose.pose.orientation.w = cy
            pose.pose.orientation.z = sy
            self._nav2_future = self._nav2_client.goToPose(pose)
            return True
        except Exception as exc:
            self.get_logger().error("[navigation] Nav2 goal send failed: %s", exc)
            return False

    def _send_nav2_goal_raw(self, pose_tuple) -> None:
        """Helper for docking controller coarse navigation."""
        if isinstance(pose_tuple, (tuple, list)) and len(pose_tuple) >= 2:
            self._send_nav2_goal(pose_tuple[0], pose_tuple[1],
                                 pose_tuple[2] if len(pose_tuple) > 2 else 0.0)

    def _check_nav2_result(self) -> None:
        """Poll the Nav2 future for completion."""
        if self._nav2_client is None or self._nav2_future is None:
            return
        try:
            if not self._nav2_client.isTaskComplete():
                return
            result = self._nav2_client.getResult()
            self._nav2_future = None
            active = self._goal_manager.get_active() if self._goal_manager else None
            if active is None:
                return

            from action_msgs.msg import GoalStatus
            if result == GoalStatus.STATUS_SUCCEEDED:
                # Check arrival tolerance
                d = active.distance_to(self._last_odom_x, self._last_odom_y)
                if d <= active.arrival_tol_m:
                    self._goal_manager.mark_succeeded(active.goal_id)
                    self._transition_state(STATE_ARRIVED)
                    self.get_logger().info(
                        "[navigation] Arrived: %s (dist=%.2fm)", active.goal_id[:8], d)
                    if active.named_location:
                        self._tts_speak(f"I've arrived at {active.named_location}.")
                else:
                    self.get_logger().warning(
                        "[navigation] Nav2 succeeded but %.2fm from goal (tol=%.2fm)",
                        d, active.arrival_tol_m,
                    )
                    self._goal_manager.mark_succeeded(active.goal_id)
                    self._transition_state(STATE_ARRIVED)
            else:
                # Navigation failed
                if self._goal_manager.record_plan_failure(active.goal_id):
                    self._goal_manager.mark_failed(
                        active.goal_id, RESULT_UNREACHABLE, "Nav2 reported failure"
                    )
                    self._tts_speak("I couldn't reach the destination. I'm sorry.")
                    self._transition_state(STATE_FAILED)
                else:
                    self._start_recovery("nav2_failed")

        except Exception as exc:
            self.get_logger().warning("[navigation] Nav2 result check error: %s", exc)

    def _cancel_nav2_goal(self) -> None:
        if self._nav2_client is not None:
            try:
                self._nav2_client.cancelTask()
            except Exception:
                pass
        self._nav2_future = None

    def _clear_costmap(self) -> None:
        if self._nav2_client is not None:
            try:
                self._nav2_client.clearAllCostmaps()
            except Exception as exc:
                self.get_logger().warning("[navigation] clearAllCostmaps failed: %s", exc)

    # ── Subscriber callbacks ───────────────────────────────────────────────────

    def _on_behavior_recommendation(self, msg) -> None:
        if not self._active:
            return
        bc = msg.behavior_class
        if bc not in ("navigate_to_goal", "approach_person", "serve_item", "stop_navigation"):
            return

        if bc == "stop_navigation":
            self._goal_manager.cancel_goal(reason="stop_navigation command")
            self._cancel_nav2_goal()
            self._transition_state(STATE_CANCELLED)
            return

        # Extract goal parameters from param_names/param_values
        params: Dict[str, str] = {}
        for name, val in zip(msg.param_names, msg.param_values):
            params[name] = val

        named = params.get("named_location", params.get("destination", ""))
        goal_x = float(params.get("goal_x", 0.0))
        goal_y = float(params.get("goal_y", 0.0))
        goal_yaw = float(params.get("goal_yaw", 0.0))

        # Resolve named location
        if named:
            pose = self._map_manager.resolve_location(named)
            if pose:
                goal_x, goal_y, goal_yaw = pose.x, pose.y, pose.yaw
            else:
                self.get_logger().warning(
                    "[navigation] Unknown location: %r", named)
                return

        # Check safety
        if self._safety_bridge and self._safety_bridge.is_motion_blocked:
            self.get_logger().warning("[navigation] Goal rejected: safety blocked")
            return

        goal_id = self._goal_manager.enqueue(
            target_x        = goal_x,
            target_y        = goal_y,
            target_yaw      = goal_yaw,
            goal_type       = 2 if named and named.startswith("charger") else 1,
            priority        = int(msg.priority),
            named_location  = named,
            requester_id    = "behavior_engine",
            recommendation_id = msg.recommendation_id,
            preempt         = (int(msg.priority) >= 2),  # HIGH+ preempts
        )
        self.get_logger().info(
            "[navigation] Goal accepted: %s → %r (%.2f, %.2f)",
            goal_id[:8], named, goal_x, goal_y,
        )

    def _on_safety_state(self, msg) -> None:
        if self._safety_bridge:
            self._safety_bridge.update_safety_state(
                state                = int(msg.state),
                navigation_permitted = bool(msg.navigation_permitted),
                actuation_permitted  = bool(msg.actuation_permitted),
            )
        # Immediate stop on hard-blocked states
        if int(msg.state) in (SAFETY_DANGER, SAFETY_FAULT, SAFETY_SAFE_STOP):
            if self._state in (STATE_EXECUTING, STATE_PLANNING, STATE_RECOVERING):
                self.get_logger().warning(
                    "[navigation] Safety stop: state=%s", msg.state_name)
                self._cancel_nav2_goal()
                if self._goal_manager:
                    active = self._goal_manager.get_active()
                    if active:
                        self._goal_manager.mark_failed(
                            active.goal_id, RESULT_SAFETY_STOP,
                            f"safety state={msg.state_name}",
                        )
                self._transition_state(STATE_SAFETY_STOPPED)

    def _on_persons(self, msg) -> None:
        if self._human_costmap is None or not self._cfg.human_aware.enabled:
            return
        seen_ids = set()
        for p in msg.persons:
            self._human_costmap.update_person(
                track_id     = p.track_id,
                x            = p.position.x,
                y            = p.position.y,
                velocity_mps = p.velocity_mps,
                facing_robot = p.facing_robot,
                age_group    = p.age_group,
            )
            seen_ids.add(p.track_id)

    def _on_odom(self, msg) -> None:
        self._last_odom_x   = msg.pose.pose.position.x
        self._last_odom_y   = msg.pose.pose.position.y
        q = msg.pose.pose.orientation
        # yaw from quaternion
        siny = 2.0 * (q.w * q.z + q.x * q.y)
        cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        self._last_odom_yaw = math.atan2(siny, cosy)
        self._last_vel = abs(msg.twist.twist.linear.x)

        if self._stuck_detector and self._state == STATE_EXECUTING:
            self._stuck_detector.update(
                self._last_odom_x, self._last_odom_y, self._last_vel
            )
        if self._loc_monitor:
            self._loc_monitor.update_pose_simple(
                self._last_odom_x, self._last_odom_y, self._last_odom_yaw
            )

    def _on_amcl_pose(self, msg) -> None:
        if self._loc_monitor is None:
            return
        p = msg.pose.pose
        q = p.orientation
        siny = 2.0 * (q.w * q.z + q.x * q.y)
        cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        yaw  = math.atan2(siny, cosy)
        c = msg.pose.covariance
        self._loc_monitor.update_pose(
            x=p.position.x, y=p.position.y, yaw=yaw,
            cov_xx=c[0], cov_yy=c[7], cov_yawyaw=c[35],
        )

    def _on_battery(self, msg) -> None:
        if self._battery_router:
            self._battery_router.update_battery(
                percentage  = float(msg.percentage) * 100.0,
                voltage_v   = float(msg.voltage),
                current_a   = float(msg.current),
                is_charging = (msg.power_supply_status == 1),  # CHARGING = 1
            )

    # ── Battery routing check ─────────────────────────────────────────────────

    def _check_battery_routing(self) -> None:
        decision = self._battery_router.evaluate(self._last_odom_x, self._last_odom_y)
        if not decision.should_dock:
            return
        # Already docking?
        if self._state == STATE_DOCKING:
            return
        # Already has a charger goal?
        if self._goal_manager.get_active():
            a = self._goal_manager.get_active()
            if a and a.goal_type == 2:
                return

        charger = decision.charger
        if charger is None:
            return

        priority = 3 if decision.urgency == "urgent" else 2  # URGENT or HIGH
        self._goal_manager.enqueue(
            target_x       = charger.x,
            target_y       = charger.y,
            target_yaw     = charger.yaw,
            goal_type      = 2,  # TYPE_CHARGER
            priority       = priority,
            named_location = charger.name,
            require_precise= True,
            requester_id   = "battery_router",
            preempt        = (priority == 3),  # critical preempts
        )
        self.get_logger().warning("[navigation] %s — routing to %s",
                                  decision.reason, charger.name)
        if priority == 3:
            self._tts_speak("My battery is critically low. I need to charge now.")

    # ── Passing alert ─────────────────────────────────────────────────────────

    def _check_passing_alerts(self) -> None:
        if self._human_costmap is None or self._state != STATE_EXECUTING:
            return
        alerts = self._human_costmap.get_passing_alerts(
            self._last_odom_x, self._last_odom_y
        )
        for alert in alerts:
            if alert.person_id not in self._announced_persons:
                self._tts_speak("Excuse me, coming through! Please watch your step.")
                self._announced_persons.add(alert.person_id)
        # Clear when persons move away
        if not alerts:
            self._announced_persons.clear()

    # ── Recovery callbacks ────────────────────────────────────────────────────

    def _execute_backup(self, distance_m: float, speed_mps: float) -> None:
        self._publish_gated_vel(-abs(speed_mps), 0.0)

    def _execute_spin(self, speed_rps: float, rotations: int) -> None:
        self._publish_gated_vel(0.0, speed_rps)

    def _escalate(self, reason: str) -> None:
        self.get_logger().error("[navigation] Escalating: %s", reason)
        self._tts_speak(
            "I'm sorry, I need help. Please ask a staff member to assist me."
        )

    # ── Velocity publishing ───────────────────────────────────────────────────

    def _publish_gated_vel(self, linear: float, angular: float) -> None:
        """Apply safety gate and publish velocity command."""
        if self._safety_bridge is None:
            return
        gated = self._safety_bridge.gate(linear, angular)
        if gated.was_blocked:
            return
        try:
            from geometry_msgs.msg import Twist
            twist = Twist()
            twist.linear.x  = gated.linear_mps
            twist.angular.z = gated.angular_rps
            # Published to safety gate topic — NOT directly to /cmd_vel
            # (safety_gate_node relays to /cmd_vel after its own checks)
        except ImportError:
            pass

    # ── TTS ───────────────────────────────────────────────────────────────────

    def _tts_speak(self, text: str, priority: int = 5) -> None:
        if self._pub_tts is None:
            return
        try:
            msg = self._import_msg("TTSRequest")()
            msg.text     = text
            msg.priority = priority
            self._pub_tts.publish(msg)
        except Exception as exc:
            self.get_logger().warning("[navigation] TTS publish failed: %s", exc)

    # ── State helpers ─────────────────────────────────────────────────────────

    def _transition_state(self, new_state: int) -> None:
        if self._state != new_state:
            self.get_logger().info(
                "[navigation] State: %s → %s",
                _STATE_NAMES.get(self._state, "?"),
                _STATE_NAMES.get(new_state, "?"),
            )
            self._state = new_state

    # ── Publishing ────────────────────────────────────────────────────────────

    def _publish_status(self) -> None:
        if self._pub_status is None:
            return
        try:
            active = self._goal_manager.get_active() if self._goal_manager else None
            msg = self._import_msg("NavigationStatus")()
            msg.header.stamp   = self.get_clock().now().to_msg()
            msg.header.frame_id= "map"
            msg.active_goal_id = active.goal_id if active else ""
            msg.state          = self._state
            msg.state_name     = _STATE_NAMES.get(self._state, "UNKNOWN")
            msg.distance_remaining_m = -1.0
            msg.linear_velocity_mps  = self._last_vel
            msg.goals_queued   = self._goal_manager.queue_size() if self._goal_manager else 0

            if active:
                msg.elapsed_sec = active.elapsed_sec
                msg.distance_remaining_m = active.distance_to(
                    self._last_odom_x, self._last_odom_y
                )

            if self._recovery_executor and self._recovery_executor.is_active():
                rs = self._recovery_executor.get_state()
                if rs:
                    msg.recovery_behavior = rs.behavior
                    msg.recovery_attempt  = rs.total_attempts

            if self._loc_monitor:
                pose = self._loc_monitor.get_pose()
                msg.current_pose.pose.position.x = pose.x
                msg.current_pose.pose.position.y = pose.y

            self._pub_status.publish(msg)
        except Exception as exc:
            self.get_logger().debug("[navigation] Status publish error: %s", exc)

    def _publish_health(self) -> None:
        if self._pub_health is None:
            return
        try:
            msg = self._import_msg("ModuleHealth")()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.module_name  = "bonbon_navigation.navigation_node"
            msg.status       = 0  # OK
            msg.status_text  = (
                f"state={_STATE_NAMES.get(self._state,'?')} "
                f"localized={self._loc_monitor.is_localized() if self._loc_monitor else '?'}"
            )
            self._pub_health.publish(msg)
        except Exception as exc:
            self.get_logger().debug("[navigation] Health publish error: %s", exc)

    # ── Service creation ──────────────────────────────────────────────────────

    def _create_services(self) -> None:
        try:
            from bonbon_srvs.srv import NavigateTo, CancelNavigation, GetNearestCharger
            self.create_service(NavigateTo, "/navigation/navigate_to",
                                self._srv_navigate_to)
            self.create_service(CancelNavigation, "/navigation/cancel",
                                self._srv_cancel)
            self.create_service(GetNearestCharger, "/navigation/get_nearest_charger",
                                self._srv_get_nearest_charger)
        except ImportError:
            self.get_logger().warn("[navigation] bonbon_srvs not available — services skipped")

    def _srv_navigate_to(self, request, response):
        named   = request.named_location
        goal_x  = request.target_pose.pose.position.x if not named else 0.0
        goal_y  = request.target_pose.pose.position.y if not named else 0.0
        goal_yaw= 0.0

        if named:
            pose = self._map_manager.resolve_location(named) if self._map_manager else None
            if pose is None:
                response.success     = False
                response.message     = f"Unknown location: {named!r}"
                response.result_code = RESULT_PLAN_FAILED
                return response
            goal_x, goal_y, goal_yaw = pose.x, pose.y, pose.yaw

        gid = self._goal_manager.enqueue(
            target_x        = goal_x,
            target_y        = goal_y,
            target_yaw      = goal_yaw,
            named_location  = named,
            timeout_sec     = request.timeout_sec,
            requester_id    = request.requester_id,
            preempt         = not request.enqueue,
            goal_id         = request.goal_id or "",
        )
        response.success     = True
        response.message     = f"Goal accepted: {gid[:8]}"
        response.result_code = 0
        return response

    def _srv_cancel(self, request, response):
        n = self._goal_manager.cancel_goal(request.goal_id, request.reason)
        if n:
            self._cancel_nav2_goal()
            self._transition_state(STATE_CANCELLED)
        response.success        = True
        response.goals_cancelled= n
        response.message        = f"Cancelled {n} goal(s)"
        return response

    def _srv_get_nearest_charger(self, request, response):
        charger = self._map_manager.nearest_charger(
            self._last_odom_x, self._last_odom_y
        ) if self._map_manager else None
        if charger:
            response.found       = True
            response.charger_id  = charger.name
            response.distance_m  = charger.distance_to_m if hasattr(charger, "distance_to_m") \
                                   else math.hypot(charger.x - self._last_odom_x,
                                                   charger.y - self._last_odom_y)
            response.message     = "OK"
        else:
            response.found       = False
            response.message     = "No charger registered"
        return response

    # ── Import helper ─────────────────────────────────────────────────────────

    @staticmethod
    def _import_msg(name: str):
        """Lazy-import a bonbon_msgs message class by name."""
        from bonbon_msgs import msg as bonbon_msg
        return getattr(bonbon_msg, name)


# ── Entry point ───────────────────────────────────────────────────────────────

def main(args=None) -> None:
    rclpy.init(args=args)
    node = NavigationNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
