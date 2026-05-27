"""
bonbon_navigation.behaviors.docking_controller
================================================
Precision docking / charging station approach controller.

Docking phases
--------------
IDLE → APPROACHING → ALIGNING → FINAL_APPROACH → CONTACT → (done)
                                                          ↓ on fail
                                                       FAILED

APPROACHING:     Nav2 guides the robot to a pre-dock waypoint
                 (pre_dock_distance_m in front of charger).
ALIGNING:        Visual (ArUco) or IR beacon alignment.
                 Commands small angular corrections until heading error
                 < max_heading_error_rad.
FINAL_APPROACH:  Slow (dock_speed_mps) straight advance until
                 contact is detected or distance_to_dock_m < threshold.
CONTACT:         Charging current confirmed — docking complete.

The controller is driven by the navigation node's timer; it does NOT
create its own ROS2 timers or subscribers.  Sensor data is injected via
update_* methods.  Motion commands are issued via the injected cmd_vel callback.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from bonbon_navigation.config.nav_config import DockingConfig

logger = logging.getLogger(__name__)


# ── Phases ────────────────────────────────────────────────────────────────────


class DockingPhase(StrEnum):
    IDLE = "IDLE"
    APPROACHING = "APPROACHING"
    ALIGNING = "ALIGNING"
    FINAL_APPROACH = "FINAL_APPROACH"
    CONTACT = "CONTACT"
    FAILED = "FAILED"
    UNDOCKING = "UNDOCKING"


# ── State ─────────────────────────────────────────────────────────────────────


@dataclass
class DockingState:
    charger_id: str = ""
    phase: DockingPhase = DockingPhase.IDLE
    retry_count: int = 0
    distance_to_dock_m: float = -1.0
    alignment_error_m: float = 0.0
    alignment_error_rad: float = 0.0
    contact_detected: bool = False
    charging_current_a: float = 0.0
    failure_reason: str = ""
    phase_started_at: float = field(default_factory=time.monotonic)


# ── Controller ────────────────────────────────────────────────────────────────

CmdVelFn = Callable[[float, float], None]  # (linear_mps, angular_rps)


class DockingController:
    """
    Precision docking state machine.

    Usage::

        dc = DockingController(cfg)
        dc.set_cmd_vel_fn(lambda linear, angular: publish_vel(linear, angular))
        dc.set_coarse_nav_fn(lambda pose: nav2_client.navigate(pose))
        dc.set_stop_fn(lambda: publish_vel(0, 0))

        # Trigger docking
        dc.start("charger_a", charger_x=0.3, charger_y=0.3, charger_yaw=math.pi/2)

        # In navigation timer loop (10 Hz):
        dc.update_ir_beacon(distance_m=0.45, lateral_err=0.01, heading_err=0.05)
        phase = dc.tick()
    """

    def __init__(self, cfg: DockingConfig) -> None:
        self._cfg = cfg
        self._state = DockingState()

        # Callbacks — default to no-ops
        self._cmd_vel_fn: CmdVelFn = lambda lin, a: None
        self._stop_fn: Callable[[], None] = lambda: None
        self._coarse_nav_fn: Callable = lambda pose: None

        # Latest sensor readings
        self._ir_distance: float = -1.0
        self._ir_lateral: float = 0.0
        self._ir_heading: float = 0.0
        self._aruco_detected: bool = False
        self._aruco_distance: float = -1.0
        self._aruco_lateral: float = 0.0
        self._aruco_heading: float = 0.0

        # Charger pose
        self._charger_x: float = 0.0
        self._charger_y: float = 0.0
        self._charger_yaw: float = 0.0

    # ── Callback injection ────────────────────────────────────────────────────

    def set_cmd_vel_fn(self, fn: CmdVelFn) -> None:
        self._cmd_vel_fn = fn

    def set_stop_fn(self, fn: Callable[[], None]) -> None:
        self._stop_fn = fn

    def set_coarse_nav_fn(self, fn: Callable) -> None:
        self._coarse_nav_fn = fn

    # ── Sensor ingestion ──────────────────────────────────────────────────────

    def update_ir_beacon(
        self,
        distance_m: float,
        lateral_err: float = 0.0,
        heading_err: float = 0.0,
    ) -> None:
        self._ir_distance = distance_m
        self._ir_lateral = lateral_err
        self._ir_heading = heading_err

    def update_aruco(
        self,
        detected: bool,
        distance_m: float = -1.0,
        lateral_err: float = 0.0,
        heading_err: float = 0.0,
    ) -> None:
        self._aruco_detected = detected
        self._aruco_distance = distance_m
        self._aruco_lateral = lateral_err
        self._aruco_heading = heading_err

    def update_contact(
        self,
        contact_detected: bool,
        charging_current_a: float = 0.0,
    ) -> None:
        self._state.contact_detected = contact_detected
        self._state.charging_current_a = charging_current_a

    # ── Control ───────────────────────────────────────────────────────────────

    def start(
        self,
        charger_id: str,
        charger_x: float,
        charger_y: float,
        charger_yaw: float,
    ) -> None:
        """Begin docking sequence for a charger."""
        self._charger_x = charger_x
        self._charger_y = charger_y
        self._charger_yaw = charger_yaw
        self._state = DockingState(
            charger_id=charger_id,
            phase=DockingPhase.APPROACHING,
            phase_started_at=time.monotonic(),
        )
        logger.info(
            "Docking started: charger=%s  pos=(%.2f,%.2f)", charger_id, charger_x, charger_y
        )

        # Request coarse navigation to pre-dock waypoint
        pre_x, pre_y = self._pre_dock_pose()
        try:
            self._coarse_nav_fn((pre_x, pre_y, charger_yaw))
        except Exception as exc:
            logger.warning("Coarse nav to pre-dock failed: %s", exc)

    def tick(self) -> DockingPhase:
        """
        Advance the docking state machine by one step.
        Call at 10 Hz.  Returns current phase.
        """
        if not self._cfg.enabled:
            return DockingPhase.IDLE

        s = self._state
        now = time.monotonic()
        elapsed = now - s.phase_started_at

        if s.phase == DockingPhase.IDLE:
            return s.phase

        elif s.phase == DockingPhase.APPROACHING:
            # Transition to ALIGNING once robot reaches pre-dock
            d = self._best_distance()
            s.distance_to_dock_m = d
            if 0.0 < d <= (self._cfg.pre_dock_distance_m + 0.20):
                self._transition(DockingPhase.ALIGNING)
            # Timeout check
            if elapsed > 60.0:
                self._fail("approach timeout")

        elif s.phase == DockingPhase.ALIGNING:
            lat, hdg = self._best_alignment()
            s.alignment_error_m = lat
            s.alignment_error_rad = hdg
            # Correct heading
            if abs(hdg) > self._cfg.max_heading_error_rad:
                angular = -math.copysign(0.15, hdg)
                self._cmd_vel_fn(0.0, angular)
            else:
                self._stop_fn()
                if abs(lat) <= self._cfg.max_alignment_error_m:
                    self._transition(DockingPhase.FINAL_APPROACH)
            if elapsed > self._cfg.alignment_timeout_sec:
                if s.retry_count < self._cfg.max_dock_attempts:
                    s.retry_count += 1
                    logger.warning("Docking alignment timeout — retry %d", s.retry_count)
                    self._transition(DockingPhase.APPROACHING)
                    pre_x, pre_y = self._pre_dock_pose()
                    try:
                        self._coarse_nav_fn((pre_x, pre_y, self._charger_yaw))
                    except Exception:
                        pass
                else:
                    self._fail("alignment timeout after max retries")

        elif s.phase == DockingPhase.FINAL_APPROACH:
            d = self._best_distance()
            s.distance_to_dock_m = d
            if s.contact_detected or (0.0 < d <= 0.05):
                self._stop_fn()
                self._transition(DockingPhase.CONTACT)
                logger.info(
                    "Docking CONTACT: charger=%s  current=%.2fA", s.charger_id, s.charging_current_a
                )
            else:
                # Slow forward advance with minor heading correction
                lat, hdg = self._best_alignment()
                angular = -math.copysign(0.05, hdg) if abs(hdg) > 0.05 else 0.0
                self._cmd_vel_fn(self._cfg.final_approach_speed_mps, angular)
            if elapsed > self._cfg.final_approach_timeout_sec:
                self._stop_fn()
                if s.retry_count < self._cfg.max_dock_attempts:
                    s.retry_count += 1
                    self._transition(DockingPhase.ALIGNING)
                else:
                    self._fail("final approach timeout after max retries")

        elif s.phase == DockingPhase.CONTACT:
            pass  # terminal success state — nav node handles it

        elif s.phase == DockingPhase.FAILED:
            pass  # terminal failure state

        elif s.phase == DockingPhase.UNDOCKING:
            if elapsed >= (
                self._cfg.undock_reverse_distance_m / max(self._cfg.undock_speed_mps, 0.01)
            ):
                self._stop_fn()
                self._state = DockingState()  # reset to IDLE

        return s.phase

    def start_undocking(self) -> None:
        """Reverse off the charger."""
        self._state.phase = DockingPhase.UNDOCKING
        self._state.phase_started_at = time.monotonic()
        self._cmd_vel_fn(-self._cfg.undock_speed_mps, 0.0)
        logger.info("Undocking: reversing %.2fm", self._cfg.undock_reverse_distance_m)

    def abort(self) -> None:
        self._stop_fn()
        self._state.phase = DockingPhase.IDLE

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _pre_dock_pose(self) -> tuple[float, float]:
        """Compute pre-dock waypoint (pre_dock_distance_m in front of charger)."""
        # "In front of" means opposite to the charger's approach direction
        dx = -math.cos(self._charger_yaw) * self._cfg.pre_dock_distance_m
        dy = -math.sin(self._charger_yaw) * self._cfg.pre_dock_distance_m
        return (self._charger_x + dx, self._charger_y + dy)

    def _best_distance(self) -> float:
        """Return the best available distance estimate to the dock."""
        if self._cfg.use_aruco_marker and self._aruco_detected and self._aruco_distance > 0:
            return self._aruco_distance
        if self._cfg.use_ir_beacon and self._ir_distance > 0:
            return self._ir_distance
        return -1.0

    def _best_alignment(self) -> tuple[float, float]:
        """Return (lateral_err_m, heading_err_rad)."""
        if self._cfg.use_aruco_marker and self._aruco_detected:
            return (self._aruco_lateral, self._aruco_heading)
        return (self._ir_lateral, self._ir_heading)

    def _transition(self, phase: DockingPhase) -> None:
        logger.info("Docking transition: %s → %s", self._state.phase.value, phase.value)
        self._state.phase = phase
        self._state.phase_started_at = time.monotonic()

    def _fail(self, reason: str) -> None:
        self._stop_fn()
        self._state.failure_reason = reason
        self._state.phase = DockingPhase.FAILED
        logger.error("Docking FAILED: %s (charger=%s)", reason, self._state.charger_id)

    @property
    def state(self) -> DockingState:
        return self._state

    @property
    def phase(self) -> DockingPhase:
        return self._state.phase

    @property
    def is_done(self) -> bool:
        return self._state.phase in (DockingPhase.CONTACT, DockingPhase.FAILED)

    @property
    def succeeded(self) -> bool:
        return self._state.phase == DockingPhase.CONTACT
