"""
bonbon_navigation.core.stuck_detector
=======================================
Detects when the robot is stuck (not making progress toward its goal).

Two complementary checks
------------------------
1. **Progress check** — the robot must move at least `min_progress_m`
   over a rolling `window_sec` window.  Checked at `check_rate_hz`.
2. **Velocity check** — if the commanded speed is nonzero but the measured
   odometry speed stays near zero for `zero_velocity_window_sec`, the robot
   is stuck against an obstacle.

A robot is declared stuck only after `stuck_threshold_count` consecutive
failed windows to suppress false positives from temporary slowing.

Thread safety: `update()` and `is_stuck()` may be called from different
threads; the internal state is protected by value-copy semantics.
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass

from bonbon_navigation.config.nav_config import StuckDetectorConfig

logger = logging.getLogger(__name__)


# ── Position sample ───────────────────────────────────────────────────────────


@dataclass
class PositionSample:
    x: float
    y: float
    t: float  # time.monotonic()


# ── Result ────────────────────────────────────────────────────────────────────


@dataclass
class StuckResult:
    is_stuck: bool
    reason: str  # "" if not stuck
    progress_m: float  # displacement over last window
    window_sec: float  # actual window evaluated
    consecutive_fails: int
    velocity_mps: float  # last measured velocity


# ── Detector ─────────────────────────────────────────────────────────────────


class StuckDetector:
    """
    Usage::

        detector = StuckDetector(cfg)
        detector.reset()          # called on each new goal

        # inside odometry callback:
        detector.update(x, y, measured_velocity_mps)

        result = detector.check()
        if result.is_stuck:
            trigger_recovery()
    """

    def __init__(self, cfg: StuckDetectorConfig) -> None:
        self._cfg = cfg
        self._history: deque[PositionSample] = deque()
        self._consecutive_fails = 0
        self._last_velocity = 0.0
        self._active = False
        self._zero_vel_start: float | None = None

    def reset(self) -> None:
        """Reset all state — call at start of each new goal."""
        self._history.clear()
        self._consecutive_fails = 0
        self._last_velocity = 0.0
        self._active = True
        self._zero_vel_start = None
        logger.debug("StuckDetector reset")

    def deactivate(self) -> None:
        """Stop monitoring — call when goal completes or is cancelled."""
        self._active = False
        self._history.clear()

    def update(self, x: float, y: float, velocity_mps: float) -> None:
        """
        Ingest a new odometry sample.

        Parameters
        ----------
        x, y:          Robot position in map frame.
        velocity_mps:  Current linear speed (always ≥ 0).
        """
        if not self._active or not self._cfg.enabled:
            return
        now = time.monotonic()
        self._history.append(PositionSample(x=x, y=y, t=now))
        self._last_velocity = abs(velocity_mps)

        # Track zero-velocity period
        if self._last_velocity < self._cfg.min_velocity_mps:
            if self._zero_vel_start is None:
                self._zero_vel_start = now
        else:
            self._zero_vel_start = None

        # Trim old samples outside the window
        cutoff = now - self._cfg.window_sec
        while self._history and self._history[0].t < cutoff:
            self._history.popleft()

    def check(self) -> StuckResult:
        """
        Evaluate the current stuck status.

        Returns a StuckResult; does NOT raise.
        """
        if not self._active or not self._cfg.enabled:
            return StuckResult(
                is_stuck=False,
                reason="",
                progress_m=0.0,
                window_sec=0.0,
                consecutive_fails=0,
                velocity_mps=self._last_velocity,
            )

        # Need at least 2 samples and a full window
        if len(self._history) < 2:
            return StuckResult(
                is_stuck=False,
                reason="insufficient samples",
                progress_m=0.0,
                window_sec=0.0,
                consecutive_fails=self._consecutive_fails,
                velocity_mps=self._last_velocity,
            )

        oldest = self._history[0]
        newest = self._history[-1]
        actual_window = newest.t - oldest.t

        if actual_window < self._cfg.window_sec * 0.5:
            # Window not yet full
            return StuckResult(
                is_stuck=False,
                reason="window not full",
                progress_m=0.0,
                window_sec=actual_window,
                consecutive_fails=self._consecutive_fails,
                velocity_mps=self._last_velocity,
            )

        # Compute total displacement over window
        progress = math.hypot(newest.x - oldest.x, newest.y - oldest.y)

        # Check zero-velocity window
        zero_vel_stuck = False
        zero_vel_reason = ""
        if self._zero_vel_start is not None:
            zero_dur = time.monotonic() - self._zero_vel_start
            if zero_dur >= self._cfg.zero_velocity_window_sec:
                zero_vel_stuck = True
                zero_vel_reason = (
                    f"zero velocity for {zero_dur:.1f}s "
                    f"(threshold {self._cfg.zero_velocity_window_sec}s)"
                )

        progress_stuck = progress < self._cfg.min_progress_m
        is_fail = progress_stuck or zero_vel_stuck

        if is_fail:
            self._consecutive_fails += 1
            reason = (
                zero_vel_reason
                if zero_vel_stuck
                else f"progress {progress:.3f}m < {self._cfg.min_progress_m}m over {actual_window:.1f}s"
            )
        else:
            self._consecutive_fails = 0
            reason = ""

        is_stuck = self._consecutive_fails >= self._cfg.stuck_threshold_count

        if is_stuck:
            logger.warning(
                "Robot STUCK: %s  (consecutive_fails=%d)",
                reason,
                self._consecutive_fails,
            )

        return StuckResult(
            is_stuck=is_stuck,
            reason=reason if is_stuck else "",
            progress_m=progress,
            window_sec=actual_window,
            consecutive_fails=self._consecutive_fails,
            velocity_mps=self._last_velocity,
        )

    @property
    def consecutive_fails(self) -> int:
        return self._consecutive_fails

    @property
    def is_active(self) -> bool:
        return self._active
