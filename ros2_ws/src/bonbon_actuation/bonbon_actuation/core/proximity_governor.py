"""ProximityGovernor — derates expressive motion near people and in child-safe mode.

The actuation node moves a head and two arms. Fast arm sweeps that are
perfectly acceptable in an empty corridor are *not* acceptable 40 cm from a
child's face. This governor converts live spatial context into a single
``speed_scale`` multiplier and a hard ``block`` flag that the node applies
before dispatching any gesture.

Inputs (all optional; the governor degrades gracefully when a signal is absent)
------------------------------------------------------------------------------
* ``nearest_person_m``  — distance to the closest tracked person (metres).
* ``hint_type``         — social-navigation hint from bonbon_spatial
                          ('stop' | 'slow_down' | 'keep_distance' | …).
* ``operating_mode``    — 'normal' | 'child_safe' | 'elderly' | 'demo' | …
* ``person_category``   — 'adult' | 'child' | 'elderly' | 'wheelchair' | …

Outputs
-------
``evaluate()`` returns a :class:`ProximityDecision` carrying:
* ``speed_scale``       — multiply the requested speed by this (0..1).
* ``block_large_motion``— True → arm-sweeping gestures must be suppressed.
* ``reason``            — human-readable explanation for logs / diagnostics.

No ROS2 dependency — pure logic, fully unit-testable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

_logger = logging.getLogger(__name__)

# Distance bands (metres) at which arm motion is derated.
STOP_DISTANCE_M = 0.45      # closer than this → freeze large motion
SLOW_DISTANCE_M = 1.0       # closer than this → heavily derate
CAUTION_DISTANCE_M = 2.0    # closer than this → mild derate

# Per-mode global speed caps.
_MODE_SPEED_CAP = {
    "normal": 1.0,
    "demo": 1.0,
    "elderly": 0.7,
    "child_safe": 0.55,
    "degraded": 0.5,
    "emergency": 1.0,  # emergency gestures must remain crisp/visible
}

# Vulnerable categories get an extra derate and a larger stop band.
_VULNERABLE = frozenset({"child", "elderly", "wheelchair"})
_VULNERABLE_SPEED_FACTOR = 0.7
_VULNERABLE_STOP_MULT = 1.4


@dataclass
class ProximityDecision:
    """Result of a proximity evaluation."""

    speed_scale: float          # multiplier in (0, 1]
    block_large_motion: bool    # True → suppress arm-sweeping gestures
    reason: str                 # explanation for logs / diagnostics


class ProximityGovernor:
    """Derates expressive motion based on live human proximity and mode.

    Thread-safety: callers should hold an external lock if mutating the cached
    inputs from multiple threads. ``evaluate`` itself is pure.
    """

    def __init__(self) -> None:
        self._nearest_person_m: float = float("inf")
        self._hint_type: str = ""
        self._operating_mode: str = "normal"
        self._person_category: str = "adult"

    # ── State updates (fed from ROS2 subscriptions) ──────────────────────────

    def update_proximity(self, nearest_person_m: float, person_category: str = "adult") -> None:
        self._nearest_person_m = max(0.0, float(nearest_person_m))
        self._person_category = person_category or "adult"

    def update_hint(self, hint_type: str) -> None:
        self._hint_type = hint_type or ""

    def set_operating_mode(self, mode: str) -> None:
        self._operating_mode = mode or "normal"

    def clear_proximity(self) -> None:
        """Called when person tracks expire — restores full speed."""
        self._nearest_person_m = float("inf")
        self._person_category = "adult"
        self._hint_type = ""

    @property
    def operating_mode(self) -> str:
        return self._operating_mode

    @property
    def nearest_person_m(self) -> float:
        return self._nearest_person_m

    # ── Core evaluation ──────────────────────────────────────────────────────

    def evaluate(self, requested_priority: int = 5) -> ProximityDecision:
        """Compute the speed scale and motion-block flag for the current context.

        Args:
            requested_priority: Priority of the gesture about to run. Emergency
                gestures (>= 20) bypass proximity derating so they remain
                clearly visible.

        Returns:
            A :class:`ProximityDecision`.
        """
        # Emergency gestures must remain crisp and visible.
        if requested_priority >= 20:
            return ProximityDecision(1.0, False, "emergency priority — no derate")

        reasons: list[str] = []
        scale = _MODE_SPEED_CAP.get(self._operating_mode, 1.0)
        if scale < 1.0:
            reasons.append(f"mode={self._operating_mode}(cap={scale:.2f})")

        is_vulnerable = self._person_category in _VULNERABLE
        stop_band = STOP_DISTANCE_M * (_VULNERABLE_STOP_MULT if is_vulnerable else 1.0)
        slow_band = SLOW_DISTANCE_M * (_VULNERABLE_STOP_MULT if is_vulnerable else 1.0)

        block = False
        dist = self._nearest_person_m

        if dist <= stop_band:
            block = True
            scale = min(scale, 0.25)
            reasons.append(f"person {dist:.2f}m ≤ stop band {stop_band:.2f}m → freeze arms")
        elif dist <= slow_band:
            scale = min(scale, 0.4)
            reasons.append(f"person {dist:.2f}m ≤ slow band {slow_band:.2f}m → derate")
        elif dist <= CAUTION_DISTANCE_M:
            scale = min(scale, 0.7)
            reasons.append(f"person {dist:.2f}m ≤ caution {CAUTION_DISTANCE_M:.1f}m → mild derate")

        # Social-navigation hint can independently force a slowdown / stop.
        if self._hint_type == "stop":
            block = True
            scale = min(scale, 0.25)
            reasons.append("spatial hint=stop → freeze arms")
        elif self._hint_type == "slow_down":
            scale = min(scale, 0.5)
            reasons.append("spatial hint=slow_down")

        # Vulnerable-category extra derate.
        if is_vulnerable:
            scale *= _VULNERABLE_SPEED_FACTOR
            reasons.append(f"vulnerable={self._person_category}")

        # Never fully stop motion (a frozen servo is itself a fault); floor it.
        scale = max(0.1, min(1.0, scale))

        reason = "; ".join(reasons) if reasons else "clear — full speed"
        _logger.debug("ProximityGovernor: scale=%.2f block=%s (%s)", scale, block, reason)
        return ProximityDecision(speed_scale=scale, block_large_motion=block, reason=reason)
