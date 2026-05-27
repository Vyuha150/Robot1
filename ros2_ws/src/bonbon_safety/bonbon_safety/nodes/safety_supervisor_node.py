"""
bonbon_safety.nodes.safety_supervisor_node
============================================
ROS2 Lifecycle node — the central safety authority for the BonBon robot.

Lifecycle transitions
---------------------
configure  → loads config, policy, incident logger, FSM
activate   → starts 10 Hz supervisor timer, subscribes to all sensor topics
deactivate → stops timer, unsubscribes (robot remains in last-known safe state)
cleanup    → closes incident logger, releases all resources
shutdown   → cleanup + node destruction

Safety guarantee
----------------
The safety gate node subscribes to /bonbon/safety/state with QoS
RELIABLE/TRANSIENT_LOCAL so that even if the gate node starts after the
supervisor, it immediately receives the last state.  This prevents a race
condition where the gate processes commands before receiving a safety state.

Every external action triggered by a policy (zero_velocity, disable_actuation,
announce, etc.) is dispatched via a dedicated helper method.  This makes the
control flow auditable and testable.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import rclpy
import rclpy.logging
from bonbon_msgs.msg import (
    BumperState,
    ModuleHealth,
    PersonStateArray,
    ServoStateArray,
    ThermalReadings,
)
from bonbon_msgs.msg import (
    SafetyEvent as SafetyEventMsg,
)

# Custom messages
from bonbon_msgs.msg import (
    SafetyState as SafetyStateMsg,
)
from bonbon_srvs.srv import SafetyReset
from geometry_msgs.msg import Twist
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.timer import Timer
from sensor_msgs.msg import BatteryState, Imu, LaserScan

# ROS2 message types
from std_msgs.msg import Bool

from bonbon_safety.core.incident_logger import IncidentLogger
from bonbon_safety.core.safety_policy import PolicyAction, SafetyPolicy

# Core logic (no ROS2 dependency)
from bonbon_safety.core.safety_state_machine import (
    STATE_PROPERTIES,
    SafetyLevel,
    SafetyStateMachine,
    StateTransition,
)
from bonbon_safety.core.threat_assessor import ThreatAssessor, ThreatAssessorConfig

logger = logging.getLogger(__name__)

# ── QoS profiles ──────────────────────────────────────────────────────────────

RELIABLE_TL = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)
RELIABLE_D50 = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=50,
)
RELIABLE_D5 = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=5,
)
BEST_EFFORT_D1 = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)

# ── Node ─────────────────────────────────────────────────────────────────────


class SafetySupervisorNode(LifecycleNode):
    """
    BonBon safety supervisor lifecycle node.

    Runs at 10 Hz.  Each cycle:
    1. ThreatAssessor.build_snapshot()      — aggregate sensor data
    2. SafetyStateMachine.update(snapshot)  — evaluate next state
    3. If transition: execute policy actions — publish, announce, log
    4. Publish SafetyState heartbeat
    5. ThreatAssessor.reset_transient_flags()
    """

    NODE_NAME = "safety_supervisor"

    def __init__(self) -> None:
        super().__init__(self.NODE_NAME)
        self._lock = threading.Lock()

        # Declared lazily in on_configure — keeping __init__ minimal
        self._fsm: SafetyStateMachine | None = None
        self._assessor: ThreatAssessor | None = None
        self._policy: SafetyPolicy | None = None
        self._incident_logger: IncidentLogger | None = None

        self._supervisor_timer: Timer | None = None
        self._heartbeat_timer: Timer | None = None

        # Publishers (created in on_activate)
        self._pub_safety_state = None
        self._pub_safety_event = None
        self._pub_cmd_vel_zero = None

        # Subscribers
        self._subs: list = []

        # Action clients
        self._nav_cancel_client = None

        # Service servers
        self._srv_reset = None

        # Declare all node parameters
        self._declare_parameters()

        self.get_logger().info(f"Node '{self.NODE_NAME}' created — waiting for configure()")

    # ── Parameter declarations ────────────────────────────────────────────────

    def _declare_parameters(self) -> None:
        self.declare_parameter("supervisor_rate_hz", 10.0)
        self.declare_parameter("policy_file", "")
        self.declare_parameter("incident_db_path", "/var/lib/bonbon/safety_incidents.db")
        self.declare_parameter("robot_id", "bonbon-01")

        # FSM thresholds (can be overridden per deployment)
        self.declare_parameter("human_caution_m", 2.0)
        self.declare_parameter("human_danger_m", 0.5)
        self.declare_parameter("battery_caution_pct", 20.0)
        self.declare_parameter("battery_dock_pct", 10.0)
        self.declare_parameter("lidar_stale_danger", True)
        self.declare_parameter("cpu_temp_caution_c", 75.0)
        self.declare_parameter("cpu_temp_fault_c", 90.0)
        self.declare_parameter("hysteresis_cycles_caution", 3)
        self.declare_parameter("hysteresis_cycles_danger", 5)

        # Staleness thresholds
        self.declare_parameter("lidar_max_age_sec", 0.5)
        self.declare_parameter("imu_max_age_sec", 0.1)
        self.declare_parameter("camera_max_age_sec", 0.2)
        self.declare_parameter("person_max_age_sec", 1.0)

        # Startup self-test timeout
        self.declare_parameter("startup_timeout_sec", 15.0)

    # ── Lifecycle callbacks ───────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        """Load config, instantiate core objects. No I/O yet."""
        self.get_logger().info("Configuring safety supervisor…")
        try:
            p = self.get_parameter

            # Build FSM
            self._fsm = SafetyStateMachine(
                hysteresis_cycles_caution=p("hysteresis_cycles_caution").value,
                hysteresis_cycles_danger=p("hysteresis_cycles_danger").value,
                battery_caution_pct=p("battery_caution_pct").value,
                battery_dock_pct=p("battery_dock_pct").value,
                human_caution_m=p("human_caution_m").value,
                human_danger_m=p("human_danger_m").value,
                lidar_stale_danger=p("lidar_stale_danger").value,
                cpu_temp_caution_c=p("cpu_temp_caution_c").value,
                cpu_temp_fault_c=p("cpu_temp_fault_c").value,
            )
            self._fsm.add_transition_callback(self._on_fsm_transition)

            # Build threat assessor
            assessor_cfg = ThreatAssessorConfig(
                lidar_max_age_sec=p("lidar_max_age_sec").value,
                imu_max_age_sec=p("imu_max_age_sec").value,
                camera_max_age_sec=p("camera_max_age_sec").value,
                person_max_age_sec=p("person_max_age_sec").value,
            )
            self._assessor = ThreatAssessor(assessor_cfg)

            # Load policy
            policy_file = p("policy_file").value
            if policy_file:
                self._policy = SafetyPolicy.from_yaml(Path(policy_file))
            else:
                self._policy = SafetyPolicy.default()
                self.get_logger().warn("No policy_file set — using built-in default policy")

            # Open incident log
            db_path = p("incident_db_path").value
            robot_id = p("robot_id").value
            self._incident_logger = IncidentLogger(db_path, robot_id=robot_id)

            self.get_logger().info("Safety supervisor configured successfully")
            return TransitionCallbackReturn.SUCCESS

        except Exception as exc:
            self.get_logger().error(f"Configuration failed: {exc}")
            return TransitionCallbackReturn.FAILURE

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        """Create publishers, subscribers, timers. Start monitoring."""
        self.get_logger().info("Activating safety supervisor…")
        try:
            self._create_publishers()
            self._create_subscribers()
            self._create_service_servers()
            self._create_action_clients()
            self._start_timers()

            # Publish initial INITIALIZING state so gate node starts locked
            self._publish_safety_state()

            self.get_logger().info(
                "Safety supervisor ACTIVE — monitoring at %.0f Hz",
                self.get_parameter("supervisor_rate_hz").value,
            )
            return TransitionCallbackReturn.SUCCESS

        except Exception as exc:
            self.get_logger().error(f"Activation failed: {exc}")
            return TransitionCallbackReturn.FAILURE

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info("Deactivating safety supervisor…")
        if self._supervisor_timer:
            self._supervisor_timer.cancel()
        if self._heartbeat_timer:
            self._heartbeat_timer.cancel()
        for sub in self._subs:
            self.destroy_subscription(sub)
        self._subs.clear()
        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        if self._incident_logger:
            self._incident_logger.close()
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        self.on_cleanup(state)
        return TransitionCallbackReturn.SUCCESS

    # ── Publisher / subscriber / timer creation ───────────────────────────────

    def _create_publishers(self) -> None:
        self._pub_safety_state = self.create_lifecycle_publisher(
            SafetyStateMsg, "/bonbon/safety/state", RELIABLE_TL
        )
        self._pub_safety_event = self.create_lifecycle_publisher(
            SafetyEventMsg, "/bonbon/safety/event", RELIABLE_D50
        )
        # Zero-velocity publisher — used to override cmd_vel on danger
        self._pub_cmd_vel_zero = self.create_lifecycle_publisher(
            Twist, "/bonbon/cmd_vel/safe", RELIABLE_D5
        )

    def _create_subscribers(self) -> None:
        def sub(msg_type, topic, callback, qos=RELIABLE_D5):
            s = self.create_subscription(msg_type, topic, callback, qos)
            self._subs.append(s)

        sub(LaserScan, "/bonbon/lidar/scan", self._cb_lidar, RELIABLE_D5)
        sub(Imu, "/bonbon/imu/data_raw", self._cb_imu, RELIABLE_D5)
        sub(BumperState, "/bonbon/bumper/state", self._cb_bumper, RELIABLE_D5)
        sub(BatteryState, "/bonbon/battery/state", self._cb_battery, RELIABLE_D5)
        sub(ThermalReadings, "/bonbon/temperature/readings", self._cb_thermal, RELIABLE_D5)
        sub(ServoStateArray, "/bonbon/servo/neck/state", self._cb_servo, RELIABLE_D5)
        sub(ServoStateArray, "/bonbon/servo/arm/state", self._cb_servo, RELIABLE_D5)
        sub(PersonStateArray, "/bonbon/perception/persons", self._cb_persons, RELIABLE_D5)
        sub(Bool, "/bonbon/estop/state", self._cb_estop, RELIABLE_TL)
        sub(
            ModuleHealth,
            "/bonbon/vision/detection_node/health",
            self._cb_module_health,
            RELIABLE_D5,
        )
        sub(ModuleHealth, "/bonbon/speech/asr_node/health", self._cb_module_health, RELIABLE_D5)
        sub(
            ModuleHealth,
            "/bonbon/navigation/planner_node/health",
            self._cb_module_health,
            RELIABLE_D5,
        )
        sub(Bool, "/bonbon/safety/unsafe_command", self._cb_unsafe_command, RELIABLE_D5)
        sub(Bool, "/bonbon/nav/timeout", self._cb_nav_timeout, RELIABLE_D5)

    def _create_service_servers(self) -> None:
        self._srv_reset = self.create_service(
            SafetyReset, "/bonbon/safety/reset", self._handle_reset
        )

    def _create_action_clients(self) -> None:
        self._nav_cancel_client = ActionClient(self, NavigateToPose, "/bonbon/navigate_to_pose")

    def _start_timers(self) -> None:
        rate_hz = self.get_parameter("supervisor_rate_hz").value
        period_sec = 1.0 / rate_hz
        self._supervisor_timer = self.create_timer(period_sec, self._supervisor_cycle)

        # Startup watchdog — fires once to check that all critical sensors came up
        startup_timeout = self.get_parameter("startup_timeout_sec").value
        self._startup_timer = self.create_timer(startup_timeout, self._check_startup_complete)

        self.get_logger().info(
            "Supervisor timer started at %.0f Hz (period %.3f s)", rate_hz, period_sec
        )

    # ── Main supervisor cycle (10 Hz timer callback) ──────────────────────────

    def _supervisor_cycle(self) -> None:
        """
        Core 10 Hz loop. All state evaluation happens here.
        Must complete in < 50ms to avoid timer starvation.
        """
        with self._lock:
            if self._fsm is None or self._assessor is None:
                return

            snapshot = self._assessor.build_snapshot()
            _prev_state = self._fsm.state
            _new_state, transition = self._fsm.update(snapshot)

            if transition is not None:
                # Policy actions are dispatched by _on_fsm_transition (callback)
                # so we don't need to handle them here explicitly.
                pass

            # Always publish state (consumers need the heartbeat)
            self._publish_safety_state()

            # Reset one-shot flags
            self._assessor.reset_transient_flags()

    def _check_startup_complete(self) -> None:
        """
        One-shot timer that fires after startup_timeout_sec.
        If still in INITIALIZING, forces a FAULT with diagnostics.
        """
        self._startup_timer.cancel()  # fire once only
        with self._lock:
            if self._fsm and self._fsm.state == SafetyLevel.INITIALIZING:
                tx = self._fsm.mark_startup_failed(
                    "Startup timeout — one or more critical sensors did not come online"
                )
                self.get_logger().error(
                    "Startup timeout! Critical sensors did not report within %s s.",
                    self.get_parameter("startup_timeout_sec").value,
                )
                self._log_and_notify(tx, trigger="TRIGGER_STARTUP", operator_notified=True)

    def _check_startup_sensors(self) -> None:
        """
        Called from the LIDAR/IMU callbacks once data arrives.
        If all critical sensors are up, complete startup.
        """
        if self._fsm is None or self._assessor is None:
            return
        if self._fsm.state != SafetyLevel.INITIALIZING:
            return

        snap = self._assessor.build_snapshot()
        all_critical_up = not snap.lidar_stale and not snap.imu_stale
        if all_critical_up:
            tx = self._fsm.mark_startup_complete()
            if tx:
                self.get_logger().info("All critical sensors online — startup complete")

    # ── FSM transition callback ───────────────────────────────────────────────

    def _on_fsm_transition(self, transition: StateTransition) -> None:
        """
        Invoked synchronously by the FSM on every state change.
        Dispatches policy actions and logs the event.
        """
        if self._policy is None:
            return

        state_name = transition.to_state.name
        actions = self._policy.on_enter_actions(state_name)

        for action in actions:
            self._dispatch_action(action, transition)

        # Log + notify
        self._log_and_notify(
            transition,
            trigger=f"TRIGGER_{transition.to_state.name}",
            operator_notified=PolicyAction.NOTIFY_OPERATOR in actions,
        )

        # Publish event message
        self._publish_safety_event(transition, actions)

    # ── Policy action dispatcher ──────────────────────────────────────────────

    def _dispatch_action(self, action: PolicyAction, transition: StateTransition) -> None:
        try:
            if action == PolicyAction.ZERO_VELOCITY:
                self._action_zero_velocity()
            elif action == PolicyAction.CAP_VELOCITY:
                pass  # Enforced by safety gate node reading /bonbon/safety/state
            elif action == PolicyAction.CANCEL_NAVIGATION:
                self._action_cancel_navigation()
            elif action == PolicyAction.DISABLE_ACTUATION:
                pass  # safety gate reads /bonbon/safety/state and blocks commands
            elif action == PolicyAction.ENABLE_ACTUATION:
                pass  # safety gate reads /bonbon/safety/state and allows commands
            elif action == PolicyAction.INITIATE_DOCKING:
                self._action_initiate_docking()
            elif action == PolicyAction.TRIGGER_ESTOP:
                self._action_trigger_estop()
            elif action == PolicyAction.RELEASE_ESTOP:
                self._action_release_estop()
            elif action == PolicyAction.ANNOUNCE_AUDIO:
                self._action_announce_audio(transition.to_state.name)
            elif action == PolicyAction.UPDATE_LED_EYES:
                self._action_update_led(transition.to_state.name)
            elif action == PolicyAction.UPDATE_DISPLAY:
                self._action_update_display(transition.to_state.name)
            elif action == PolicyAction.NOTIFY_OPERATOR:
                self._action_notify_operator(transition)
            elif action == PolicyAction.REQUEST_HUMAN_HELP:
                self._action_request_human_help()
            elif action == PolicyAction.LOG_INCIDENT:
                pass  # handled by _log_and_notify
            else:
                self.get_logger().warn(f"Unhandled policy action: {action}")
        except Exception:
            self.get_logger().exception(f"Error dispatching policy action: {action}")

    # ── Action implementations ────────────────────────────────────────────────

    def _action_zero_velocity(self) -> None:
        """Publish a zero Twist to the safe cmd_vel topic immediately."""
        if self._pub_cmd_vel_zero is None:
            return
        zero = Twist()
        self._pub_cmd_vel_zero.publish(zero)
        self.get_logger().info("Action: zero velocity published")

    def _action_cancel_navigation(self) -> None:
        """Cancel any active Nav2 navigation goal."""
        if self._nav_cancel_client and self._nav_cancel_client.server_is_ready():
            self._nav_cancel_client.cancel_all_goals_async()
            self.get_logger().info("Action: navigation goal cancelled")
        else:
            self.get_logger().warn("Navigation action server not available — skipping cancel")

    def _action_initiate_docking(self) -> None:
        """Publish a docking request (picked up by dock_node)."""
        if self._pub_safety_event:
            msg = SafetyEventMsg()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.trigger = SafetyEventMsg.TRIGGER_LOW_BATTERY
            msg.trigger_name = "low_battery_dock"
            msg.description = "Initiating autonomous docking due to low battery"
            self._pub_safety_event.publish(msg)
        self.get_logger().info("Action: docking initiated")

    def _action_trigger_estop(self) -> None:
        """
        Hardware e-stop is triggered via GPIO by the estop_node.
        We signal it by publishing on /bonbon/estop/trigger.
        The estop_node then asserts the relay pin.
        """
        self.get_logger().critical("Action: TRIGGER_ESTOP — requesting hardware e-stop")
        # estop_node monitors /bonbon/safety/state and asserts GPIO on SAFE_STOP

    def _action_release_estop(self) -> None:
        self.get_logger().info("Action: releasing e-stop relay")

    def _action_announce_audio(self, state_name: str) -> None:
        """Publish TTS request for the state audio."""
        if self._policy is None:
            return
        announce_text = self._policy.announce_text(state_name)
        if announce_text:
            self.get_logger().info("Action: announce '%s'", announce_text)
            # Publish TTS request (bonbon_tts listens on /bonbon/tts/request)
            from bonbon_msgs.msg import TTSRequest

            if hasattr(self, "_pub_tts"):
                req = TTSRequest()
                req.text = announce_text
                req.priority = 10  # safety announcements have highest priority
                self._pub_tts.publish(req)

    def _action_update_led(self, state_name: str) -> None:
        if self._policy is None:
            return
        led_state = self._policy.led_state(state_name)
        if led_state:
            self.get_logger().debug("Action: LED eyes → %s", led_state)

    def _action_update_display(self, state_name: str) -> None:
        if self._policy is None:
            return
        text = self._policy.display_text(state_name)
        if text:
            self.get_logger().debug("Action: display → '%s'", text)

    def _action_notify_operator(self, transition: StateTransition) -> None:
        self.get_logger().warn(
            "Action: operator notification — %s → %s: %s",
            transition.from_state.name,
            transition.to_state.name,
            transition.reason,
        )

    def _action_request_human_help(self) -> None:
        self.get_logger().error(
            "Action: REQUEST HUMAN INTERVENTION — robot requires physical attention"
        )

    # ── Publisher helpers ─────────────────────────────────────────────────────

    def _publish_safety_state(self) -> None:
        if self._pub_safety_state is None or self._fsm is None:
            return

        state = self._fsm.state
        props = STATE_PROPERTIES[state]

        msg = SafetyStateMsg()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "base_link"
        msg.state = int(state)
        msg.state_name = state.name
        msg.reason = ""
        msg.time_in_state_sec = self._fsm.time_in_state_sec
        msg.actuation_permitted = props.actuation_permitted
        msg.navigation_permitted = props.navigation_permitted
        msg.max_velocity_mps = props.max_velocity_mps
        msg.degraded_modules = list(self._fsm.degraded_modules)
        msg.requires_manual_reset = props.requires_manual_reset

        self._pub_safety_state.publish(msg)

    def _publish_safety_event(self, transition: StateTransition, actions: list) -> None:
        if self._pub_safety_event is None:
            return

        snap = transition.snapshot
        msg = SafetyEventMsg()
        msg.header.stamp = self.get_clock().now().to_msg()

        # Map state to severity
        if transition.to_state in (SafetyLevel.FAULT, SafetyLevel.SAFE_STOP, SafetyLevel.DANGER):
            msg.severity = SafetyEventMsg.CRITICAL
        elif transition.to_state in (SafetyLevel.CAUTION, SafetyLevel.DEGRADED):
            msg.severity = SafetyEventMsg.WARNING
        else:
            msg.severity = SafetyEventMsg.INFO

        msg.prior_state = int(transition.from_state)
        msg.new_state = int(transition.to_state)
        msg.prior_state_name = transition.from_state.name
        msg.new_state_name = transition.to_state.name
        msg.description = transition.reason
        msg.operator_notified = PolicyAction.NOTIFY_OPERATOR in actions
        msg.auto_recovery_attempted = False

        if snap:
            msg.nearest_obstacle_m = snap.nearest_obstacle_m
            msg.nearest_human_m = snap.nearest_human_m
            msg.battery_percent = snap.battery_percent
            msg.cpu_temp_c = snap.cpu_temp_c

        self._pub_safety_event.publish(msg)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _log_and_notify(
        self,
        transition: StateTransition,
        *,
        trigger: str = "state_machine",
        operator_notified: bool = False,
    ) -> None:
        if self._incident_logger:
            self._incident_logger.log_transition(
                transition,
                trigger=trigger,
                operator_notified=operator_notified,
            )

    # ── Subscriber callbacks ──────────────────────────────────────────────────

    def _cb_lidar(self, msg: LaserScan) -> None:
        if self._assessor is None:
            return
        # Min range, excluding zeros (invalid returns)
        ranges = [r for r in msg.ranges if 0.01 < r < msg.range_max]
        nearest = min(ranges) if ranges else -1.0
        self._assessor.update_lidar_scan(nearest)
        # Check if startup can complete
        self._check_startup_sensors()

    def _cb_imu(self, msg: Imu) -> None:
        if self._assessor is None:
            return
        av = msg.angular_velocity
        norm = (av.x**2 + av.y**2 + av.z**2) ** 0.5
        self._assessor.update_imu(norm)
        self._check_startup_sensors()

    def _cb_bumper(self, msg: BumperState) -> None:
        if self._assessor is None:
            return
        self._assessor.update_bumpers(msg.front, msg.rear)
        # Bumper contact should trigger a cycle immediately
        if msg.front or msg.rear:
            with self._lock:
                self._supervisor_cycle()

    def _cb_battery(self, msg: BatteryState) -> None:
        if self._assessor is None:
            return
        percent = msg.percentage * 100.0 if msg.percentage <= 1.0 else msg.percentage
        self._assessor.update_battery(percent)

    def _cb_thermal(self, msg: ThermalReadings) -> None:
        if self._assessor is None:
            return
        self._assessor.update_temperature(
            cpu_temp_c=msg.cpu_temp_c,
            motor_temp_c=msg.motor_temp_c,
        )

    def _cb_servo(self, msg: ServoStateArray) -> None:
        if self._assessor is None:
            return
        any_fault = any(s.error_code != 0 for s in msg.servos)
        self._assessor.update_servo_state(any_fault)

    def _cb_persons(self, msg: PersonStateArray) -> None:
        if self._assessor is None:
            return
        distances = [p.distance_m for p in msg.persons if p.distance_m > 0]
        nearest = min(distances) if distances else -1.0
        self._assessor.update_persons(nearest)

    def _cb_estop(self, msg: Bool) -> None:
        if self._assessor is None:
            return
        self._assessor.update_estop(msg.data)
        # E-stop must be processed immediately — do not wait for next cycle
        if msg.data:
            with self._lock:
                self._supervisor_cycle()

    def _cb_module_health(self, msg: ModuleHealth) -> None:
        if self._assessor is None or self._fsm is None:
            return
        if msg.status == ModuleHealth.ERROR or msg.status == ModuleHealth.STALE:
            tx = self._fsm.register_module_degraded(msg.module_name)
            if tx:
                self._log_and_notify(tx, trigger="TRIGGER_NODE_CRASH", operator_notified=True)
        elif msg.status == ModuleHealth.OK:
            tx = self._fsm.clear_module_degraded(msg.module_name)
            if tx:
                self._log_and_notify(tx, trigger="TRIGGER_STARTUP")

    def _cb_unsafe_command(self, msg: Bool) -> None:
        if self._assessor:
            self._assessor.update_unsafe_command(msg.data)

    def _cb_nav_timeout(self, msg: Bool) -> None:
        if self._assessor:
            self._assessor.update_navigation_timeout(msg.data)

    # ── Service handlers ──────────────────────────────────────────────────────

    def _handle_reset(
        self,
        request: SafetyReset.Request,
        response: SafetyReset.Response,
    ) -> SafetyReset.Response:
        with self._lock:
            if self._fsm is None:
                response.success = False
                response.message = "FSM not initialised"
                return response

            tx = self._fsm.reset(operator_id=request.operator_id)
            if tx is None:
                response.success = False
                response.message = f"Reset not allowed from state {self._fsm.state.name}"
                return response

            self.get_logger().warn(
                "Manual reset by operator '%s' — entering INITIALIZING",
                request.operator_id,
            )
            self._log_and_notify(tx, trigger="TRIGGER_MANUAL_RESET", operator_notified=True)
            self._publish_safety_state()
            response.success = True
            response.message = "Reset accepted — running startup checks"
            return response


# ── Entry point ───────────────────────────────────────────────────────────────


def main(args=None) -> None:
    rclpy.init(args=args)
    node = SafetySupervisorNode()
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
