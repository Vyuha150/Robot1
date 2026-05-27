"""
bonbon_safety.nodes.safety_gate_node
======================================
CLASS-A CRITICAL: Safety Gate Node

Every actuation command issued by the AI/navigation layer MUST pass through
this node.  The gate reads the pre-computed capability flags that the Safety
Supervisor embeds in each SafetyState heartbeat and forwards, scales, or
drops commands accordingly — no redundant logic required.

Architecture
------------

  AI / Navigation layer
    /bonbon/servo/neck/command_raw  ─┐
    /bonbon/servo/arm/command_raw   ─┤──► SafetyGateNode ──► HAL layer
    /bonbon/cmd_vel_raw              ─┘         ▲
                                                │
                              /bonbon/safety/state
                              (RELIABLE / TRANSIENT_LOCAL)

Gating rules (from SafetyState capability flags)
-------------------------------------------------
  actuation_permitted=True  → servo commands forwarded as-is
  actuation_permitted=False → servo commands dropped; blocked-count +1
  navigation_permitted=True → Twist forwarded, clamped to max_velocity_mps
  navigation_permitted=False→ Twist replaced with zero Twist; blocked-count +1
  state=INITIALIZING        → nothing forwarded until supervisor confirms sensors

Topics subscribed
-----------------
  /bonbon/safety/state             SafetyState      RELIABLE/TRANSIENT_LOCAL
  /bonbon/servo/neck/command_raw   ServoState       RELIABLE depth=10
  /bonbon/servo/arm/command_raw    ServoStateArray  RELIABLE depth=10
  /bonbon/cmd_vel_raw              Twist            BEST_EFFORT depth=1

Topics published
----------------
  /bonbon/servo/neck/command       ServoState       RELIABLE depth=10   → HAL
  /bonbon/servo/arm/command        ServoStateArray  RELIABLE depth=10   → HAL
  /cmd_vel                         Twist            BEST_EFFORT depth=1  → Nav
  /bonbon/actuation/safety_gate_node/health  ModuleHealth  RELIABLE/TL
  /bonbon/safety_gate/stats        SafetyGateStats  RELIABLE depth=5

Parameters
----------
  caution_velocity_cap_mps  float  default 0.3  — hard cap in CAUTION
  block_servos_in_danger    bool   default true  — drop servo cmds in DANGER
  health_rate_hz            float  default 1.0
  stats_rate_hz             float  default 2.0
  watchdog_timeout_sec      float  default 2.0   — time before gate goes defensive

Defensive mode
--------------
  If /bonbon/safety/state has not been received for watchdog_timeout_sec the
  gate considers the supervisor down.  It publishes zero Twist and drops all
  servo commands until the supervisor recovers — behaving as if state=DANGER.
"""

from __future__ import annotations

import math
import threading
import time

import rclpy
from bonbon_msgs.msg import (
    ModuleHealth,
    ServoState,
    ServoStateArray,
)
from bonbon_msgs.msg import (
    SafetyState as SafetyStateMsg,
)
from geometry_msgs.msg import Twist
from rclpy.lifecycle import LifecycleNode, State, TransitionCallbackReturn
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

# ── QoS profiles ──────────────────────────────────────────────────────────────

RELIABLE_TL = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)
RELIABLE_D10 = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
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

# ── Constants ────────────────────────────────────────────────────────────────

NODE_NAME = "safety_gate_node"
HEALTH_TOPIC = "/bonbon/actuation/safety_gate_node/health"
STATS_TOPIC = "/bonbon/safety_gate/stats"

# ── Gating statistics (plain Python — no bonbon_msgs dependency) ─────────────


class GateStats:
    """Thread-safe monotonic counters for pass/block decisions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.servo_passed: int = 0
        self.servo_blocked: int = 0
        self.vel_passed: int = 0
        self.vel_scaled: int = 0
        self.vel_blocked: int = 0
        self.total_blocked: int = 0
        self._start_time: float = time.monotonic()

    def record_servo_pass(self) -> None:
        with self._lock:
            self.servo_passed += 1

    def record_servo_block(self) -> None:
        with self._lock:
            self.servo_blocked += 1
            self.total_blocked += 1

    def record_vel_pass(self) -> None:
        with self._lock:
            self.vel_passed += 1

    def record_vel_scale(self) -> None:
        with self._lock:
            self.vel_scaled += 1
            self.vel_passed += 1  # it was forwarded, just reduced

    def record_vel_block(self) -> None:
        with self._lock:
            self.vel_blocked += 1
            self.total_blocked += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "servo_passed": self.servo_passed,
                "servo_blocked": self.servo_blocked,
                "vel_passed": self.vel_passed,
                "vel_scaled": self.vel_scaled,
                "vel_blocked": self.vel_blocked,
                "total_blocked": self.total_blocked,
                "uptime_sec": time.monotonic() - self._start_time,
            }


# ── Node ──────────────────────────────────────────────────────────────────────


class SafetyGateNode(LifecycleNode):
    """
    BonBon safety gate — lifecycle node, CLASS-A CRITICAL.

    The node MUST be activated before any actuation command is accepted.
    While in INACTIVE or UNCONFIGURED state, ALL commands are silently dropped.
    """

    def __init__(self) -> None:
        super().__init__(NODE_NAME)
        self._lock = threading.Lock()

        # Current safety state (updated by subscriber)
        self._safety_state: SafetyStateMsg | None = None
        self._state_recv_time: float = 0.0  # time.monotonic()
        self._supervisor_ok: bool = False

        self._stats = GateStats()
        self._start_time = time.monotonic()
        self._error_count: int = 0
        self._warning_count: int = 0
        self._processed_count: int = 0

        # Publishers / subscribers — created in on_activate
        self._pub_neck: object | None = None
        self._pub_arm: object | None = None
        self._pub_vel: object | None = None
        self._pub_health: object | None = None

        self._health_timer = None
        self._watchdog_timer = None

        # Declare all params so they appear in `ros2 param list`
        self._declare_parameters()

        self.get_logger().info(f"[{NODE_NAME}] Node created — awaiting configure()")

    # ── Parameter declarations ────────────────────────────────────────────────

    def _declare_parameters(self) -> None:
        self.declare_parameter("caution_velocity_cap_mps", 0.3)
        self.declare_parameter("block_servos_in_danger", True)
        self.declare_parameter("health_rate_hz", 1.0)
        self.declare_parameter("stats_rate_hz", 2.0)
        self.declare_parameter("watchdog_timeout_sec", 2.0)

    # ── Lifecycle transitions ─────────────────────────────────────────────────

    def on_configure(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info(f"[{NODE_NAME}] Configuring…")
        try:
            self._caution_vel_cap = self.get_parameter("caution_velocity_cap_mps").value
            self._block_servos_in_danger = self.get_parameter("block_servos_in_danger").value
            self._health_rate_hz = self.get_parameter("health_rate_hz").value
            self._watchdog_timeout_sec = self.get_parameter("watchdog_timeout_sec").value
        except Exception as exc:
            self.get_logger().error(f"[{NODE_NAME}] Parameter load failed: {exc}")
            return TransitionCallbackReturn.FAILURE

        self.get_logger().info(
            f"[{NODE_NAME}] Configured — caution_vel_cap={self._caution_vel_cap} m/s "
            f"block_servos_in_danger={self._block_servos_in_danger} "
            f"watchdog_timeout={self._watchdog_timeout_sec}s"
        )
        return TransitionCallbackReturn.SUCCESS

    def on_activate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info(f"[{NODE_NAME}] Activating…")

        # ── Safety state subscriber (must exist before any command sub) ────────
        self._sub_safety = self.create_subscription(
            SafetyStateMsg,
            "/bonbon/safety/state",
            self._on_safety_state,
            RELIABLE_TL,
        )

        # ── Command subscribers (raw — from AI / navigation) ──────────────────
        self._sub_neck_raw = self.create_subscription(
            ServoState,
            "/bonbon/servo/neck/command_raw",
            self._on_neck_command_raw,
            RELIABLE_D10,
        )
        self._sub_arm_raw = self.create_subscription(
            ServoStateArray,
            "/bonbon/servo/arm/command_raw",
            self._on_arm_command_raw,
            RELIABLE_D10,
        )
        self._sub_vel_raw = self.create_subscription(
            Twist,
            "/bonbon/cmd_vel_raw",
            self._on_vel_raw,
            BEST_EFFORT_D1,
        )

        # ── Publishers (gated — to HAL nodes) ────────────────────────────────
        self._pub_neck = self.create_lifecycle_publisher(
            ServoState, "/bonbon/servo/neck/command", RELIABLE_D10
        )
        self._pub_arm = self.create_lifecycle_publisher(
            ServoStateArray, "/bonbon/servo/arm/command", RELIABLE_D10
        )
        self._pub_vel = self.create_lifecycle_publisher(Twist, "/cmd_vel", BEST_EFFORT_D1)
        self._pub_health = self.create_lifecycle_publisher(ModuleHealth, HEALTH_TOPIC, RELIABLE_TL)

        # ── Timers ────────────────────────────────────────────────────────────
        health_period = 1.0 / max(self._health_rate_hz, 0.1)
        self._health_timer = self.create_timer(health_period, self._publish_health)

        watchdog_period = max(self._watchdog_timeout_sec / 2.0, 0.1)
        self._watchdog_timer = self.create_timer(watchdog_period, self._check_supervisor_watchdog)

        self.get_logger().info(f"[{NODE_NAME}] Active — gate is OPEN (waiting for SafetyState)")
        return TransitionCallbackReturn.SUCCESS

    def on_deactivate(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info(f"[{NODE_NAME}] Deactivating — publishing final zero-vel")
        self._publish_zero_vel()

        if self._health_timer:
            self._health_timer.cancel()
            self._health_timer = None
        if self._watchdog_timer:
            self._watchdog_timer.cancel()
            self._watchdog_timer = None

        with self._lock:
            self._safety_state = None
            self._supervisor_ok = False

        return TransitionCallbackReturn.SUCCESS

    def on_cleanup(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info(f"[{NODE_NAME}] Cleanup")
        self._pub_neck = None
        self._pub_arm = None
        self._pub_vel = None
        self._pub_health = None
        return TransitionCallbackReturn.SUCCESS

    def on_shutdown(self, state: State) -> TransitionCallbackReturn:
        self.get_logger().info(f"[{NODE_NAME}] Shutdown")
        self._publish_zero_vel()
        return TransitionCallbackReturn.SUCCESS

    # ── Subscriber callbacks ──────────────────────────────────────────────────

    def _on_safety_state(self, msg: SafetyStateMsg) -> None:
        with self._lock:
            self._safety_state = msg
            self._state_recv_time = time.monotonic()
            self._supervisor_ok = True
        self.get_logger().debug(
            f"[{NODE_NAME}] Safety state: {msg.state_name} "
            f"actuation={msg.actuation_permitted} "
            f"nav={msg.navigation_permitted} "
            f"max_vel={msg.max_velocity_mps:.2f} m/s"
        )

    def _on_neck_command_raw(self, msg: ServoState) -> None:
        """Gate neck servo command from AI layer."""
        if not self._can_actuate():
            self._stats.record_servo_block()
            self._warning_count += 1
            self.get_logger().debug(
                f"[{NODE_NAME}] BLOCKED neck servo cmd " f"(state={self._current_state_name()})"
            )
            return

        if self._pub_neck is not None:
            self._pub_neck.publish(msg)
            self._stats.record_servo_pass()
            self._processed_count += 1

    def _on_arm_command_raw(self, msg: ServoStateArray) -> None:
        """Gate arm servo command array from AI layer."""
        if not self._can_actuate():
            self._stats.record_servo_block()
            self._warning_count += 1
            self.get_logger().debug(
                f"[{NODE_NAME}] BLOCKED arm servo cmd " f"(state={self._current_state_name()})"
            )
            return

        if self._pub_arm is not None:
            self._pub_arm.publish(msg)
            self._stats.record_servo_pass()
            self._processed_count += 1

    def _on_vel_raw(self, msg: Twist) -> None:
        """
        Gate and scale velocity command from Nav2 / AI layer.

        If navigation_permitted=False → zero Twist published.
        If navigation_permitted=True  → Twist clamped to max_velocity_mps.
        """
        if not self._can_navigate():
            self._publish_zero_vel()
            self._stats.record_vel_block()
            self._warning_count += 1
            self.get_logger().debug(
                f"[{NODE_NAME}] BLOCKED cmd_vel " f"(state={self._current_state_name()})"
            )
            return

        with self._lock:
            state = self._safety_state

        if state is None:
            # Defensive: no safety state yet — emit zero
            self._publish_zero_vel()
            self._stats.record_vel_block()
            return

        max_vel = state.max_velocity_mps
        scaled, did_scale = self._clamp_twist(msg, max_vel)

        if self._pub_vel is not None:
            self._pub_vel.publish(scaled)
            self._processed_count += 1
            if did_scale:
                self._stats.record_vel_scale()
                self.get_logger().debug(
                    f"[{NODE_NAME}] Velocity SCALED to {max_vel:.2f} m/s "
                    f"(state={self._current_state_name()})"
                )
            else:
                self._stats.record_vel_pass()

    # ── Gating helpers ────────────────────────────────────────────────────────

    def _can_actuate(self) -> bool:
        """Return True only if servos are permitted by current safety state."""
        with self._lock:
            if not self._supervisor_ok:
                return False
            if self._safety_state is None:
                return False
            # Extra: if state is DANGER and block_servos_in_danger is set
            state_val = self._safety_state.state
            if self._block_servos_in_danger and state_val in (
                SafetyStateMsg.DANGER,
                SafetyStateMsg.FAULT,
                SafetyStateMsg.SAFE_STOP,
                SafetyStateMsg.INITIALIZING,
            ):
                return False
            return bool(self._safety_state.actuation_permitted)

    def _can_navigate(self) -> bool:
        """Return True only if navigation is permitted by current safety state."""
        with self._lock:
            if not self._supervisor_ok:
                return False
            if self._safety_state is None:
                return False
            return bool(self._safety_state.navigation_permitted)

    @staticmethod
    def _clamp_twist(msg: Twist, max_vel_mps: float) -> tuple[Twist, bool]:
        """
        Clamp the linear speed of a Twist to max_vel_mps.

        Returns (clamped_twist, did_scale_down).
        Angular velocity is not clamped — the safety supervisor sets
        max_velocity_mps for linear motion only.
        """
        if max_vel_mps <= 0.0:
            zero = Twist()
            return zero, True

        # Compute current linear speed (2-D ground plane)
        vx = msg.linear.x
        vy = msg.linear.y
        speed = math.sqrt(vx * vx + vy * vy)

        if speed <= max_vel_mps or speed < 1e-6:
            return msg, False

        scale = max_vel_mps / speed
        clamped = Twist()
        clamped.linear.x = vx * scale
        clamped.linear.y = vy * scale
        clamped.linear.z = msg.linear.z
        clamped.angular.x = msg.angular.x
        clamped.angular.y = msg.angular.y
        clamped.angular.z = msg.angular.z
        return clamped, True

    def _publish_zero_vel(self) -> None:
        """Publish an all-zero Twist to immediately halt navigation."""
        if self._pub_vel is not None:
            self._pub_vel.publish(Twist())

    def _current_state_name(self) -> str:
        with self._lock:
            if self._safety_state is None:
                return "UNKNOWN"
            return self._safety_state.state_name or str(self._safety_state.state)

    # ── Watchdog ─────────────────────────────────────────────────────────────

    def _check_supervisor_watchdog(self) -> None:
        """
        Detect supervisor heartbeat loss.

        If no SafetyState has been received for watchdog_timeout_sec the gate
        enters defensive mode: it blocks all actuation until the supervisor
        recovers.  A single WARN log per transition prevents log flooding.
        """
        now = time.monotonic()
        with self._lock:
            age = now - self._state_recv_time if self._state_recv_time else float("inf")
            was_ok = self._supervisor_ok

        if age > self._watchdog_timeout_sec:
            with self._lock:
                self._supervisor_ok = False
            if was_ok:
                self._warning_count += 1
                self.get_logger().warn(
                    f"[{NODE_NAME}] Safety supervisor HEARTBEAT LOST "
                    f"(last seen {age:.1f}s ago) — entering defensive mode"
                )
            self._publish_zero_vel()

        elif not was_ok and age <= self._watchdog_timeout_sec:
            # Supervisor came back
            with self._lock:
                self._supervisor_ok = True
            self.get_logger().info(f"[{NODE_NAME}] Safety supervisor heartbeat RECOVERED")

    # ── Health publishing ─────────────────────────────────────────────────────

    def _publish_health(self) -> None:
        if self._pub_health is None:
            return

        now = self.get_clock().now().to_msg()
        uptime = time.monotonic() - self._start_time

        stats = self._stats.snapshot()
        with self._lock:
            supervisor_ok = self._supervisor_ok
            state_name = self._safety_state.state_name if self._safety_state else "UNKNOWN"
            blocked_total = stats["total_blocked"]

        # Determine health status
        if not supervisor_ok:
            status = ModuleHealth.ERROR
            status_txt = "Supervisor HEARTBEAT LOST — defensive mode active"
        elif blocked_total > 0:
            status = ModuleHealth.WARN
            status_txt = f"Gate active. {blocked_total} commands blocked. " f"Safety: {state_name}"
        else:
            status = ModuleHealth.OK
            status_txt = f"Gate active. All commands passed. Safety: {state_name}"

        msg = ModuleHealth()
        msg.header.stamp = now
        msg.module_name = NODE_NAME
        msg.status = status
        msg.status_text = status_txt
        msg.uptime_sec = uptime
        msg.last_successful_cycle_sec = 0.0
        msg.error_count = self._error_count
        msg.warning_count = self._warning_count
        msg.processed_count = self._processed_count
        msg.latency_ms = 0.0

        self._pub_health.publish(msg)


# ── Entry point ───────────────────────────────────────────────────────────────


def main(args=None) -> None:
    rclpy.init(args=args)
    node = SafetyGateNode()
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
