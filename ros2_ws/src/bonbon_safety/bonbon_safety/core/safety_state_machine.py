"""
bonbon_safety.core.safety_state_machine
========================================
Pure-Python safety state machine for the BonBon service robot.

This module has zero ROS2 dependency so it can be unit-tested in isolation
with standard pytest.  The ROS2 node imports this class and feeds it sensor
readings each cycle; it reads back the resulting SafetyLevel and acts on it.

State diagram
-------------
                         ┌─── e-stop ────────────────────────────────────────►SAFE_STOP
                         │
  ┌──────────────┐  all OK ┌──────────┐  human<0.5m  ┌────────┐  fault   ┌───────┐
  │ INITIALIZING ├────────►│  NORMAL  ├─────────────►│ DANGER ├─────────►│ FAULT │
  └──────┬───────┘         └────┬─────┘               └───┬────┘         └───────┘
         │                      │human<2m                  │cleared
         │ fault                │or sensor WARN            ▼
         ▼                      ▼                     ┌─────────┐
     ┌───────┐             ┌─────────┐  danger        │         │
     │ FAULT │             │ CAUTION ├───────────────►│ DANGER  │
     └───────┘             └────┬────┘                └─────────┘
                                │ all clear
                                ▼
                           ┌─────────┐
              battery<10%  │  NORMAL │
  NORMAL ─────────────────►│ DOCKING │
                           └─────────┘

Key invariants
--------------
1. SAFE_STOP is reachable from ANY state (hardware e-stop).
2. FAULT and SAFE_STOP require `reset()` before any other transition.
3. State properties (actuation_permitted, max_velocity_mps) are immutable
   data attached to each state — consumers never hard-code the rules.
4. Hysteresis counters prevent rapid oscillation between NORMAL ↔ CAUTION
   and DANGER ↔ CAUTION.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum

logger = logging.getLogger(__name__)


# ── State enum ────────────────────────────────────────────────────────────────


class SafetyLevel(IntEnum):
    """Ordered safety levels.  Higher value = more restrictive capability."""

    INITIALIZING = 0
    NORMAL = 1
    CAUTION = 2
    DANGER = 3
    DOCKING = 4  # concurrent with CAUTION velocity semantics
    DEGRADED = 5  # non-critical module offline
    FAULT = 6  # hardware fault — manual reset required
    SAFE_STOP = 7  # e-stop hardware triggered — motor power cut


# ── State properties ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SafetyStateProperties:
    """Immutable capability descriptor for a safety state."""

    actuation_permitted: bool
    navigation_permitted: bool
    max_velocity_mps: float
    requires_manual_reset: bool
    description: str


STATE_PROPERTIES: dict[SafetyLevel, SafetyStateProperties] = {
    SafetyLevel.INITIALIZING: SafetyStateProperties(
        actuation_permitted=False,
        navigation_permitted=False,
        max_velocity_mps=0.0,
        requires_manual_reset=False,
        description="System starting up — awaiting sensor confirmation",
    ),
    SafetyLevel.NORMAL: SafetyStateProperties(
        actuation_permitted=True,
        navigation_permitted=True,
        max_velocity_mps=0.8,
        requires_manual_reset=False,
        description="All systems nominal — full capability",
    ),
    SafetyLevel.CAUTION: SafetyStateProperties(
        actuation_permitted=True,
        navigation_permitted=True,
        max_velocity_mps=0.3,
        requires_manual_reset=False,
        description="Human nearby or sensor marginal — speed capped 0.3 m/s",
    ),
    SafetyLevel.DANGER: SafetyStateProperties(
        actuation_permitted=False,
        navigation_permitted=False,
        max_velocity_mps=0.0,
        requires_manual_reset=False,
        description="Imminent hazard — all motion stopped",
    ),
    SafetyLevel.DOCKING: SafetyStateProperties(
        actuation_permitted=True,
        navigation_permitted=True,
        max_velocity_mps=0.2,
        requires_manual_reset=False,
        description="Low battery — navigating to dock at ≤ 0.2 m/s",
    ),
    SafetyLevel.DEGRADED: SafetyStateProperties(
        actuation_permitted=True,
        navigation_permitted=True,
        max_velocity_mps=0.3,
        requires_manual_reset=False,
        description="Non-critical module offline — partial capability",
    ),
    SafetyLevel.FAULT: SafetyStateProperties(
        actuation_permitted=False,
        navigation_permitted=False,
        max_velocity_mps=0.0,
        requires_manual_reset=True,
        description="Hardware fault — awaiting operator manual reset",
    ),
    SafetyLevel.SAFE_STOP: SafetyStateProperties(
        actuation_permitted=False,
        navigation_permitted=False,
        max_velocity_mps=0.0,
        requires_manual_reset=True,
        description="Emergency stop engaged — motor power physically cut",
    ),
}


# ── Sensor snapshot ───────────────────────────────────────────────────────────


@dataclass
class SensorSnapshot:
    """
    All safety-relevant sensor readings for one supervisor cycle.

    Every field has a sentinel value (negative or None) meaning "unknown /
    not available". The FSM treats unknown data conservatively — it does NOT
    assume the best case.
    """

    # Spatial safety
    nearest_obstacle_m: float = -1.0  # min LIDAR range; -1 = LIDAR offline
    nearest_human_m: float = -1.0  # closest person track; -1 = no track
    cliff_detected_left: bool = False
    cliff_detected_right: bool = False

    # Physical contact
    bumper_front: bool = False
    bumper_rear: bool = False

    # Sensor health flags (False = sensor healthy / online)
    lidar_stale: bool = False  # True if LIDAR scan not received in time
    camera_stale: bool = False
    imu_stale: bool = False
    imu_drift_detected: bool = False  # drift exceeds calibration threshold

    # Power and thermal
    battery_percent: float = 100.0
    cpu_temp_c: float = 20.0
    motor_temp_c: float = 20.0  # from thermistor readings

    # Actuation health
    servo_fault: bool = False  # any Dynamixel overload / error
    odrive_fault: bool = False  # any wheel motor driver error

    # Software triggers
    estop_hardware: bool = False  # GPIO e-stop pin asserted
    unsafe_command_detected: bool = False  # LLM safety filter raised alarm
    navigation_timeout: bool = False  # nav2 goal timed out without arrival

    # Node health (populated by watchdog)
    critical_node_crashed: bool = False  # CLASS A node missing heartbeat
    important_node_crashed: bool = False  # CLASS B node missing heartbeat

    # Timestamp for staleness detection
    timestamp: float = field(default_factory=time.monotonic)


# ── Transition record ─────────────────────────────────────────────────────────


@dataclass
class StateTransition:
    """Records a single state transition for audit logging."""

    from_state: SafetyLevel
    to_state: SafetyLevel
    reason: str
    timestamp: float = field(default_factory=time.monotonic)
    snapshot: SensorSnapshot | None = None


# ── FSM ───────────────────────────────────────────────────────────────────────


class SafetyStateMachine:
    """
    Deterministic, side-effect-free safety state machine.

    The machine does NOT call ROS2, GPIO, or any I/O.  All external effects
    (publishing topics, cutting power) are handled by the caller based on the
    transition returned by `update()`.

    Thread safety: this class is NOT thread-safe.  The ROS2 supervisor node
    calls `update()` from a single timer callback and must protect concurrent
    access with a lock if needed.

    Parameters
    ----------
    hysteresis_cycles_caution:
        Number of consecutive clean cycles before CAUTION → NORMAL.
    hysteresis_cycles_danger:
        Number of consecutive clear cycles before DANGER → CAUTION.
    battery_caution_pct:
        Battery level at which to enter CAUTION (and plan dock route).
    battery_dock_pct:
        Battery level at which to force DOCKING regardless of current task.
    human_caution_m:
        Distance at which human presence triggers CAUTION.
    human_danger_m:
        Distance at which human presence triggers DANGER (full stop).
    lidar_stale_danger:
        If True, a stale LIDAR reading immediately triggers DANGER rather
        than CAUTION.  Recommended True for production.
    cpu_temp_caution_c:
        CPU temperature that triggers CAUTION (throttle AI inference).
    cpu_temp_fault_c:
        CPU temperature that triggers FAULT (risk of hardware damage).
    """

    def __init__(
        self,
        *,
        hysteresis_cycles_caution: int = 3,
        hysteresis_cycles_danger: int = 5,
        battery_caution_pct: float = 20.0,
        battery_dock_pct: float = 10.0,
        human_caution_m: float = 2.0,
        human_danger_m: float = 0.5,
        lidar_stale_danger: bool = True,
        cpu_temp_caution_c: float = 75.0,
        cpu_temp_fault_c: float = 90.0,
    ) -> None:
        self._state: SafetyLevel = SafetyLevel.INITIALIZING
        self._state_entry_time: float = time.monotonic()
        self._degraded_modules: set[str] = set()

        # Hysteresis counters
        self._clear_cycles: int = 0  # cycles with no hazard detected
        self._hysteresis_caution = hysteresis_cycles_caution
        self._hysteresis_danger = hysteresis_cycles_danger

        # Thresholds (stored for later inspection / override tests)
        self.battery_caution_pct = battery_caution_pct
        self.battery_dock_pct = battery_dock_pct
        self.human_caution_m = human_caution_m
        self.human_danger_m = human_danger_m
        self.lidar_stale_danger = lidar_stale_danger
        self.cpu_temp_caution_c = cpu_temp_caution_c
        self.cpu_temp_fault_c = cpu_temp_fault_c

        # Transition history (last 100)
        self._history: list[StateTransition] = []
        self._max_history = 100

        # Startup sequence flag — set by mark_startup_complete(), consumed by update()
        self._startup_complete_pending: bool = False

        # Transition callbacks (set by supervisor node)
        self._on_transition: list[Callable[[StateTransition], None]] = []

        logger.info(
            "SafetyStateMachine initialised",
            extra={
                "initial_state": self._state.name,
                "human_danger_m": human_danger_m,
                "battery_dock_pct": battery_dock_pct,
            },
        )

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def state(self) -> SafetyLevel:
        return self._state

    @property
    def properties(self) -> SafetyStateProperties:
        return STATE_PROPERTIES[self._state]

    @property
    def time_in_state_sec(self) -> float:
        return time.monotonic() - self._state_entry_time

    @property
    def history(self) -> list[StateTransition]:
        """Return a copy of the recent state transition history (newest last)."""
        return list(self._history)

    @property
    def degraded_modules(self) -> frozenset[str]:
        return frozenset(self._degraded_modules)

    def add_transition_callback(self, callback: Callable[[StateTransition], None]) -> None:
        """Register a callback invoked on every state transition."""
        self._on_transition.append(callback)

    def register_module_degraded(self, module_name: str) -> StateTransition | None:
        """Mark a non-critical module as degraded."""
        if module_name not in self._degraded_modules:
            self._degraded_modules.add(module_name)
            logger.warning("Module marked degraded: %s", module_name)
            if self._state == SafetyLevel.NORMAL:
                return self._transition(
                    SafetyLevel.DEGRADED,
                    f"Module offline: {module_name}",
                )
        return None

    def clear_module_degraded(self, module_name: str) -> StateTransition | None:
        """Mark a non-critical module as recovered."""
        self._degraded_modules.discard(module_name)
        if not self._degraded_modules and self._state == SafetyLevel.DEGRADED:
            logger.info("All modules recovered — returning to NORMAL")
            return self._transition(SafetyLevel.NORMAL, "All degraded modules recovered")
        return None

    def reset(self, operator_id: str = "unknown") -> StateTransition | None:
        """
        Operator-triggered reset from FAULT or SAFE_STOP → INITIALIZING.

        Returns a transition record if the reset was valid, None otherwise.
        The supervisor node must re-run the startup self-test after this.
        """
        if self._state not in (SafetyLevel.FAULT, SafetyLevel.SAFE_STOP):
            logger.warning("reset() called from non-resettable state %s", self._state.name)
            return None
        logger.info("Manual reset by operator '%s'", operator_id)
        return self._transition(
            SafetyLevel.INITIALIZING, f"Manual reset by operator '{operator_id}'"
        )

    def mark_startup_complete(self) -> None:
        """
        Called by supervisor after all critical sensors have confirmed online.

        Sets an internal flag so that the INITIALIZING → NORMAL transition
        fires on the next ``update()`` call.  This ensures the caller always
        receives the transition via ``update()`` rather than via this method,
        keeping the single-source-of-truth invariant for transition records.
        """
        if self._state != SafetyLevel.INITIALIZING:
            return
        logger.info("Startup complete — NORMAL transition pending next update()")
        self._startup_complete_pending = True

    def mark_startup_failed(self, reason: str) -> StateTransition:
        """
        Called by supervisor when critical hardware is absent at startup.
        Transitions INITIALIZING → FAULT.
        """
        logger.error("Startup failed: %s", reason)
        return self._transition(SafetyLevel.FAULT, f"Startup failure: {reason}")

    def trigger_docking(self, reason: str = "battery low") -> StateTransition | None:
        """Force a transition to DOCKING from NORMAL or CAUTION."""
        if self._state in (SafetyLevel.NORMAL, SafetyLevel.CAUTION, SafetyLevel.DEGRADED):
            return self._transition(SafetyLevel.DOCKING, reason)
        return None

    def docking_complete(self) -> StateTransition | None:
        """Called when the robot successfully docks and battery begins charging."""
        if self._state == SafetyLevel.DOCKING:
            return self._transition(SafetyLevel.NORMAL, "Docking complete — battery charging")
        return None

    def update(self, snapshot: SensorSnapshot) -> tuple[SafetyLevel, StateTransition | None]:
        """
        Core FSM update — evaluate sensor snapshot and compute next state.

        Must be called once per supervisor cycle (≥ 10 Hz).
        Returns (new_state, transition_or_None).  If no state change occurred,
        transition is None.

        This method is the ONLY place that contains transition logic.  All
        threshold comparisons live here, not scattered across the codebase.
        """
        current = self._state

        # ── 1. Hardware e-stop is unconditional ───────────────────────────────
        if snapshot.estop_hardware and current != SafetyLevel.SAFE_STOP:
            tx = self._transition(
                SafetyLevel.SAFE_STOP,
                "Hardware emergency stop button pressed",
                snapshot,
            )
            return self._state, tx

        # ── 2. States that block further evaluation ───────────────────────────
        if current in (SafetyLevel.SAFE_STOP, SafetyLevel.FAULT):
            # These states require explicit reset() — no auto-recovery
            return current, None

        if current == SafetyLevel.INITIALIZING:
            # Startup sequence: mark_startup_complete() sets the pending flag;
            # the actual transition fires here so all transitions come from update().
            if self._startup_complete_pending:
                self._startup_complete_pending = False
                tx = self._transition(
                    SafetyLevel.NORMAL,
                    "All critical sensors confirmed online",
                    snapshot,
                )
                return self._state, tx
            return current, None

        # ── 3. Docking state: only exit on docking_complete() ─────────────────
        if current == SafetyLevel.DOCKING:
            # But e-stop and critical faults can still interrupt
            if self._is_fault_condition(snapshot):
                tx = self._transition(
                    SafetyLevel.FAULT,
                    self._fault_reason(snapshot),
                    snapshot,
                )
                return self._state, tx
            if self._is_danger_condition(snapshot):
                tx = self._transition(
                    SafetyLevel.DANGER,
                    self._danger_reason(snapshot),
                    snapshot,
                )
                return self._state, tx
            return current, None

        # ── 4. Critical fault conditions (from any non-terminal state) ────────
        if self._is_fault_condition(snapshot):
            self._clear_cycles = 0
            tx = self._transition(
                SafetyLevel.FAULT,
                self._fault_reason(snapshot),
                snapshot,
            )
            return self._state, tx

        # ── 5. Hardware degraded conditions (before DANGER/CAUTION priority) ─────
        if self._is_degraded_condition(snapshot):
            if current in (SafetyLevel.NORMAL, SafetyLevel.CAUTION):
                tx = self._transition(
                    SafetyLevel.DEGRADED,
                    self._degraded_reason(snapshot),
                    snapshot,
                )
                return self._state, tx
            if current == SafetyLevel.DEGRADED:
                return current, None
            # DANGER or higher: fall through — more restrictive state wins

        # ── 6. Battery → force docking ────────────────────────────────────────
        if (
            snapshot.battery_percent >= 0
            and snapshot.battery_percent <= self.battery_dock_pct
            and current != SafetyLevel.DOCKING
        ):
            self._clear_cycles = 0
            tx = self._transition(
                SafetyLevel.DOCKING,
                f"Battery critically low ({snapshot.battery_percent:.0f}%)",
                snapshot,
            )
            return self._state, tx

        # ── 6. DANGER conditions ──────────────────────────────────────────────
        if self._is_danger_condition(snapshot):
            self._clear_cycles = 0
            if current != SafetyLevel.DANGER:
                tx = self._transition(
                    SafetyLevel.DANGER,
                    self._danger_reason(snapshot),
                    snapshot,
                )
                return self._state, tx
            return current, None  # already in DANGER

        # ── 7. CAUTION conditions ─────────────────────────────────────────────
        if self._is_caution_condition(snapshot):
            self._clear_cycles = 0
            if current == SafetyLevel.DANGER:
                # Danger clearing through caution on the way to normal
                tx = self._transition(
                    SafetyLevel.CAUTION,
                    self._caution_reason(snapshot),
                    snapshot,
                )
                return self._state, tx
            if current in (SafetyLevel.NORMAL, SafetyLevel.DEGRADED):
                tx = self._transition(
                    SafetyLevel.CAUTION,
                    self._caution_reason(snapshot),
                    snapshot,
                )
                return self._state, tx
            return current, None  # already in CAUTION or more restrictive

        # ── 8. All-clear hysteresis ───────────────────────────────────────────
        self._clear_cycles += 1

        if current == SafetyLevel.DANGER:
            if self._clear_cycles >= self._hysteresis_danger:
                self._clear_cycles = 0
                target = (
                    SafetyLevel.CAUTION
                    if self._any_caution_condition(snapshot)
                    else SafetyLevel.NORMAL
                )
                tx = self._transition(
                    target,
                    f"Danger condition cleared for {self._hysteresis_danger} cycles",
                    snapshot,
                )
                return self._state, tx

        elif current == SafetyLevel.CAUTION:
            if self._clear_cycles >= self._hysteresis_caution:
                self._clear_cycles = 0
                tx = self._transition(
                    SafetyLevel.NORMAL,
                    f"Caution condition cleared for {self._hysteresis_caution} cycles",
                    snapshot,
                )
                return self._state, tx

        return current, None

    # ── Condition evaluators ──────────────────────────────────────────────────

    def _is_fault_condition(self, s: SensorSnapshot) -> bool:
        """Conditions that require a manual reset to recover."""
        return any(
            [
                s.critical_node_crashed,
                s.servo_fault and s.odrive_fault,  # both drive systems dead
                s.cpu_temp_c >= self.cpu_temp_fault_c,
            ]
        )

    def _fault_reason(self, s: SensorSnapshot) -> str:
        if s.critical_node_crashed:
            return "Critical safety node crash"
        if s.servo_fault and s.odrive_fault:
            return "Both servo and wheel motor systems faulted"
        if s.cpu_temp_c >= self.cpu_temp_fault_c:
            return f"CPU overtemperature: {s.cpu_temp_c:.1f} °C ≥ {self.cpu_temp_fault_c} °C"
        return "Unknown fault condition"

    def _is_danger_condition(self, s: SensorSnapshot) -> bool:
        """Conditions that require immediate full stop."""
        human_danger = s.nearest_human_m >= 0 and s.nearest_human_m <= self.human_danger_m
        lidar_danger = s.lidar_stale and self.lidar_stale_danger
        return any(
            [
                s.bumper_front,
                s.bumper_rear,
                s.cliff_detected_left,
                s.cliff_detected_right,
                human_danger,
                lidar_danger,
                s.imu_drift_detected,
            ]
        )

    def _danger_reason(self, s: SensorSnapshot) -> str:
        if s.bumper_front or s.bumper_rear:
            return "Physical bumper contact"
        if s.cliff_detected_left or s.cliff_detected_right:
            return "Cliff detected"
        if s.nearest_human_m >= 0 and s.nearest_human_m <= self.human_danger_m:
            return f"Human within danger zone ({s.nearest_human_m:.2f} m)"
        if s.lidar_stale:
            return "LIDAR data stale — navigation unsafe"
        if s.imu_drift_detected:
            return "IMU drift detected — localization unreliable"
        return "Danger condition"

    def _is_degraded_condition(self, s: SensorSnapshot) -> bool:
        """Conditions that indicate hardware degradation but not immediate danger.
        These trigger DEGRADED state (not CAUTION) so the distinction is visible."""
        return s.servo_fault or s.odrive_fault

    def _degraded_reason(self, s: SensorSnapshot) -> str:
        if s.servo_fault:
            return "Servo fault detected"
        if s.odrive_fault:
            return "Wheel motor fault detected"
        return "Hardware degradation detected"

    def _is_caution_condition(self, s: SensorSnapshot) -> bool:
        """Conditions that require speed reduction."""
        human_caution = s.nearest_human_m >= 0 and s.nearest_human_m <= self.human_caution_m
        return any(
            [
                human_caution,
                s.lidar_stale and not self.lidar_stale_danger,
                s.camera_stale,
                s.imu_stale,
                # Note: servo_fault / odrive_fault → DEGRADED (not CAUTION)
                s.important_node_crashed,
                0 <= s.battery_percent <= self.battery_caution_pct,
                s.cpu_temp_c >= self.cpu_temp_caution_c,
                s.unsafe_command_detected,
                s.navigation_timeout,
            ]
        )

    def _caution_reason(self, s: SensorSnapshot) -> str:
        if s.nearest_human_m >= 0 and s.nearest_human_m <= self.human_caution_m:
            return f"Human within caution zone ({s.nearest_human_m:.2f} m)"
        if s.lidar_stale:
            return "LIDAR data stale — reduced speed mode"
        if s.camera_stale:
            return "Camera offline — reduced speed mode"
        if s.imu_stale:
            return "IMU data stale — reduced speed mode"
        if s.important_node_crashed:
            return "Important navigation/perception node crashed"
        if 0 <= s.battery_percent <= self.battery_caution_pct:
            return f"Battery low ({s.battery_percent:.0f}%) — planning dock route"
        if s.cpu_temp_c >= self.cpu_temp_caution_c:
            return f"CPU temperature elevated ({s.cpu_temp_c:.1f} °C)"
        if s.unsafe_command_detected:
            return "Unsafe LLM command detected and rejected"
        if s.navigation_timeout:
            return "Navigation goal timed out"
        return "Caution condition"

    def _any_caution_condition(self, s: SensorSnapshot) -> bool:
        return self._is_caution_condition(s)

    # ── Internal transition helper ─────────────────────────────────────────────

    def _transition(
        self,
        new_state: SafetyLevel,
        reason: str,
        snapshot: SensorSnapshot | None = None,
    ) -> StateTransition:
        old_state = self._state
        self._state = new_state
        self._state_entry_time = time.monotonic()

        tx = StateTransition(
            from_state=old_state,
            to_state=new_state,
            reason=reason,
            snapshot=snapshot,
        )

        # Maintain bounded history
        self._history.append(tx)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        logger.warning(
            "Safety state transition: %s → %s — %s",
            old_state.name,
            new_state.name,
            reason,
            extra={
                "from_state": old_state.name,
                "to_state": new_state.name,
                "reason": reason,
                "actuation_permitted": STATE_PROPERTIES[new_state].actuation_permitted,
                "max_velocity_mps": STATE_PROPERTIES[new_state].max_velocity_mps,
            },
        )

        for cb in self._on_transition:
            try:
                cb(tx)
            except Exception:  # noqa: BLE001
                logger.exception("Error in transition callback")

        return tx

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def transition_history(self) -> list[StateTransition]:
        """Return a copy of the recent transition history."""
        return list(self._history)

    def summary(self) -> dict:
        """Return a JSON-serialisable summary suitable for health endpoints."""
        return {
            "state": self._state.name,
            "state_value": int(self._state),
            "time_in_state_sec": round(self.time_in_state_sec, 1),
            "actuation_permitted": self.properties.actuation_permitted,
            "navigation_permitted": self.properties.navigation_permitted,
            "max_velocity_mps": self.properties.max_velocity_mps,
            "requires_manual_reset": self.properties.requires_manual_reset,
            "degraded_modules": sorted(self._degraded_modules),
            "clear_cycles": self._clear_cycles,
            "transition_count": len(self._history),
        }
