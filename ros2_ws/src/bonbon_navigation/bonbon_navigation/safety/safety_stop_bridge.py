"""
bonbon_navigation.safety.safety_stop_bridge
=============================================
Gates navigation velocity commands against the live SafetyState.

Architecture constraint
-----------------------
The navigation node NEVER publishes directly to /cmd_vel.
All velocity commands pass through:

  NavigationNode → /navigation/cmd_vel_request
  ↓
  SafetyStopBridge → checks SafetyState
  ↓
  /bonbon/safety_gate/cmd_vel  (consumed by Safety Gate node)
  ↓
  SafetyGateNode → /cmd_vel  (to motor controllers)

The bridge enforces:
  * DANGER   → zero velocity (immediate stop)
  * SAFE_STOP→ zero velocity (hardware e-stop engaged)
  * FAULT    → zero velocity
  * CAUTION  → cap linear to caution_speed_mps (0.3 m/s)
  * DOCKING  → cap linear to dock_speed_mps (0.15 m/s)
  * NORMAL   → pass through with max_speed_mps cap

SafetyState heartbeat watchdog: if no SafetyState received within
watchdog_timeout_sec, enter defensive mode (zero velocity).
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Tuple

logger = logging.getLogger(__name__)

# Safety state constants (mirror bonbon_msgs/SafetyState.msg)
SAFETY_INITIALIZING = 0
SAFETY_NORMAL       = 1
SAFETY_CAUTION      = 2
SAFETY_DANGER       = 3
SAFETY_DOCKING      = 4
SAFETY_DEGRADED     = 5
SAFETY_FAULT        = 6
SAFETY_SAFE_STOP    = 7

_MOTION_BLOCKED_STATES = frozenset({
    SAFETY_DANGER,
    SAFETY_FAULT,
    SAFETY_SAFE_STOP,
})


# ── Gated velocity ────────────────────────────────────────────────────────────

@dataclass
class GatedVelocity:
    """Result of filtering a velocity command through the safety bridge."""
    linear_mps:   float
    angular_rps:  float
    was_capped:   bool     # True if speed was reduced
    was_blocked:  bool     # True if motion is fully blocked
    safety_state: int
    reason:       str      = ""


# ── Bridge ────────────────────────────────────────────────────────────────────

class SafetyStopBridge:
    """
    Velocity safety filter.

    Usage::

        bridge = SafetyStopBridge(
            max_speed_mps=0.80,
            caution_speed_mps=0.30,
            dock_speed_mps=0.15,
            watchdog_timeout_sec=2.0,
        )
        bridge.update_safety_state(state=SAFETY_NORMAL, navigation_permitted=True)

        gated = bridge.gate(linear=0.5, angular=0.2)
        publish_cmd_vel(gated.linear_mps, gated.angular_rps)
    """

    def __init__(
        self,
        max_speed_mps:       float = 0.80,
        caution_speed_mps:   float = 0.30,
        dock_speed_mps:      float = 0.15,
        watchdog_timeout_sec: float = 2.0,
    ) -> None:
        self._max_speed     = max_speed_mps
        self._caution_speed = caution_speed_mps
        self._dock_speed    = dock_speed_mps
        self._watchdog      = watchdog_timeout_sec

        self._safety_state:  int   = SAFETY_INITIALIZING
        self._nav_permitted: bool  = False
        self._act_permitted: bool  = False
        self._last_update:   float = 0.0
        self._safety_blocked_count = 0
        self._last_block_log:float = 0.0

    # ── Safety state update ───────────────────────────────────────────────────

    def update_safety_state(
        self,
        state:                int,
        navigation_permitted: bool = True,
        actuation_permitted:  bool = True,
    ) -> None:
        self._safety_state  = state
        self._nav_permitted = navigation_permitted
        self._act_permitted = actuation_permitted
        self._last_update   = time.monotonic()

    # ── Velocity gating ───────────────────────────────────────────────────────

    def gate(self, linear: float, angular: float) -> GatedVelocity:
        """
        Apply safety-state-based velocity limits.

        Parameters
        ----------
        linear:   Requested linear velocity (m/s, positive=forward).
        angular:  Requested angular velocity (rad/s).
        """
        state = self._safety_state

        # Watchdog: no SafetyState received recently
        if self._last_update > 0 and (time.monotonic() - self._last_update) > self._watchdog:
            return self._blocked(state, "safety watchdog timeout — no SafetyState heartbeat")

        # Hard-blocked states
        if state in _MOTION_BLOCKED_STATES:
            self._safety_blocked_count += 1
            return self._blocked(state, f"safety state={state} blocks motion")

        # Navigation permission flag
        if not self._nav_permitted and (abs(linear) > 0.001 or abs(angular) > 0.001):
            return self._blocked(state, "navigation_permitted=False")

        # Apply speed caps
        cap, was_capped = self._speed_cap(state, linear)
        linear_out = math.copysign(min(abs(linear), cap), linear)

        # Angular is only scaled proportionally when linear is capped
        if was_capped and abs(linear) > 0.001:
            scale = abs(linear_out) / abs(linear)
            angular_out = angular * scale
        else:
            angular_out = angular

        reason = (
            f"capped {abs(linear):.2f}→{abs(linear_out):.2f}m/s (state={state})"
            if was_capped else ""
        )

        return GatedVelocity(
            linear_mps   = linear_out,
            angular_rps  = angular_out,
            was_capped   = was_capped,
            was_blocked  = False,
            safety_state = state,
            reason       = reason,
        )

    def _speed_cap(self, state: int, linear: float) -> Tuple[float, bool]:
        """Return (cap_mps, was_capped)."""
        if state == SAFETY_DOCKING:
            cap = self._dock_speed
        elif state == SAFETY_CAUTION:
            cap = self._caution_speed
        elif state == SAFETY_DEGRADED:
            cap = self._caution_speed
        else:
            cap = self._max_speed
        return (cap, abs(linear) > cap)

    def _blocked(self, state: int, reason: str) -> GatedVelocity:
        now = time.monotonic()
        if now - self._last_block_log > 2.0:  # throttle log spam
            logger.warning("SafetyStopBridge BLOCK: %s", reason)
            self._last_block_log = now
        return GatedVelocity(
            linear_mps   = 0.0,
            angular_rps  = 0.0,
            was_capped   = False,
            was_blocked  = True,
            safety_state = state,
            reason       = reason,
        )

    # ── Accessors ─────────────────────────────────────────────────────────────

    @property
    def is_motion_blocked(self) -> bool:
        if (time.monotonic() - self._last_update) > self._watchdog:
            return True
        return self._safety_state in _MOTION_BLOCKED_STATES or not self._nav_permitted

    @property
    def safety_state(self) -> int:
        return self._safety_state

    @property
    def navigation_permitted(self) -> bool:
        return self._nav_permitted

    @property
    def blocked_count(self) -> int:
        return self._safety_blocked_count

    def safety_state_name(self) -> str:
        return {
            SAFETY_INITIALIZING: "INITIALIZING",
            SAFETY_NORMAL:       "NORMAL",
            SAFETY_CAUTION:      "CAUTION",
            SAFETY_DANGER:       "DANGER",
            SAFETY_DOCKING:      "DOCKING",
            SAFETY_DEGRADED:     "DEGRADED",
            SAFETY_FAULT:        "FAULT",
            SAFETY_SAFE_STOP:    "SAFE_STOP",
        }.get(self._safety_state, f"UNKNOWN({self._safety_state})")
