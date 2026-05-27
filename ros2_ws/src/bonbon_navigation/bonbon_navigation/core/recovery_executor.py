"""
bonbon_navigation.core.recovery_executor
==========================================
Recovery behavior state machine for failed/stuck navigation.

Recovery cascade (configurable)
--------------------------------
1. wait          — pause N seconds for dynamic obstacles to move
2. clear_costmap — clear local costmap, retry planning
3. backup        — reverse 0.3 m to create clearance
4. spin          — rotate 360° to re-perceive environment
5. replan        — request a fresh global plan
6. announce      — TTS: "Could you please clear the way?"
7. escalate      — publish staff alert, mark goal as failed

Each behavior has a configurable maximum attempt count.  After all
behaviors are exhausted the goal is declared permanently failed.

The executor is stateless between goals — call reset() on each new goal.
Actual motion commands (backup, spin) are delegated to callbacks injected
at construction, keeping this class free of ROS2 dependencies.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from bonbon_navigation.config.nav_config import RecoveryConfig

logger = logging.getLogger(__name__)


# ── Result ────────────────────────────────────────────────────────────────────


class RecoveryOutcome(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"  # behavior complete; retry navigation
    EXHAUSTED = "EXHAUSTED"  # all behaviors tried; give up


@dataclass
class RecoveryState:
    behavior: str = ""  # current behavior name
    attempt: int = 0  # attempt within current behavior
    total_attempts: int = 0  # across all behaviors
    behavior_index: int = 0  # position in behavior_sequence
    outcome: RecoveryOutcome = RecoveryOutcome.IN_PROGRESS
    trigger_reason: str = ""
    started_at: float = field(default_factory=time.monotonic)
    behavior_started_at: float = field(default_factory=time.monotonic)


# ── Callbacks type aliases ────────────────────────────────────────────────────

ClearCostmapFn = Callable[[], None]
BackupFn = Callable[[float, float], None]  # (distance_m, speed_mps)
SpinFn = Callable[[float, int], None]  # (speed_rps, rotations)
AnnounceFn = Callable[[str], None]  # (text)
EscalateFn = Callable[[str], None]  # (reason)


# ── Executor ──────────────────────────────────────────────────────────────────


class RecoveryExecutor:
    """
    Drives the recovery behavior cascade.

    Inject actual ROS2-backed callables via the `set_*` methods before use.

    Usage::

        exec = RecoveryExecutor(cfg)
        exec.set_clear_costmap_fn(nav2_client.clear_costmap)
        exec.set_backup_fn(backup_controller.execute)
        exec.set_spin_fn(spin_controller.execute)
        exec.set_announce_fn(tts_client.speak)
        exec.set_escalate_fn(safety_client.escalate)

        exec.reset(trigger_reason="stuck")
        while True:
            outcome = exec.step()
            if outcome != RecoveryOutcome.IN_PROGRESS:
                break
    """

    def __init__(self, cfg: RecoveryConfig) -> None:
        self._cfg = cfg
        self._state: RecoveryState | None = None

        # Callbacks — default to no-ops
        self._clear_fn: ClearCostmapFn = lambda: None
        self._backup_fn: BackupFn = lambda d, s: None
        self._spin_fn: SpinFn = lambda r, n: None
        self._announce_fn: AnnounceFn = lambda t: None
        self._escalate_fn: EscalateFn = lambda r: None

    # ── Callback injection ────────────────────────────────────────────────────

    def set_clear_costmap_fn(self, fn: ClearCostmapFn) -> None:
        self._clear_fn = fn

    def set_backup_fn(self, fn: BackupFn) -> None:
        self._backup_fn = fn

    def set_spin_fn(self, fn: SpinFn) -> None:
        self._spin_fn = fn

    def set_announce_fn(self, fn: AnnounceFn) -> None:
        self._announce_fn = fn

    def set_escalate_fn(self, fn: EscalateFn) -> None:
        self._escalate_fn = fn

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def reset(self, trigger_reason: str = "") -> None:
        """Call at the start of a recovery session (new goal or new stuck event)."""
        if not self._cfg.enabled:
            return
        self._state = RecoveryState(
            behavior=self._cfg.behavior_sequence[0] if self._cfg.behavior_sequence else "",
            behavior_index=0,
            trigger_reason=trigger_reason,
        )
        logger.info(
            "Recovery started: trigger=%r  sequence=%s", trigger_reason, self._cfg.behavior_sequence
        )

    def is_active(self) -> bool:
        return self._state is not None and self._state.outcome == RecoveryOutcome.IN_PROGRESS

    def get_state(self) -> RecoveryState | None:
        return self._state

    # ── Step ──────────────────────────────────────────────────────────────────

    def step(self) -> RecoveryOutcome:
        """
        Execute the current recovery behavior step.

        Must be called repeatedly (e.g. at 5 Hz) while is_active().
        Returns the current outcome.
        """
        if not self._cfg.enabled or self._state is None:
            return RecoveryOutcome.SUCCEEDED

        s = self._state

        # If already exhausted, stay exhausted
        if s.outcome == RecoveryOutcome.EXHAUSTED:
            return s.outcome

        # Check total retry limit
        if s.total_attempts >= self._cfg.max_retries_per_goal:
            logger.warning("Recovery exhausted: %d attempts", s.total_attempts)
            s.outcome = RecoveryOutcome.EXHAUSTED
            return s.outcome

        # Execute current behavior
        outcome = self._execute_behavior(s)

        if outcome == RecoveryOutcome.SUCCEEDED:
            # Move to next behavior in sequence
            s.behavior_index += 1
            if s.behavior_index >= len(self._cfg.behavior_sequence):
                logger.info("Recovery sequence complete: all behaviors tried")
                s.outcome = RecoveryOutcome.SUCCEEDED
                return s.outcome
            s.behavior = self._cfg.behavior_sequence[s.behavior_index]
            s.attempt = 0
            s.behavior_started_at = time.monotonic()
            logger.info("Recovery advancing to: %s", s.behavior)
            return RecoveryOutcome.IN_PROGRESS

        # Propagate terminal outcomes set directly by behaviors (e.g. escalate → EXHAUSTED)
        if s.outcome != RecoveryOutcome.IN_PROGRESS:
            return s.outcome

        return RecoveryOutcome.IN_PROGRESS

    # ── Behavior implementations ──────────────────────────────────────────────

    def _execute_behavior(self, s: RecoveryState) -> RecoveryOutcome:
        """
        Execute one tick of the current behavior.
        Returns SUCCEEDED when the behavior is done (move to next),
        IN_PROGRESS while still running.
        """
        b = s.behavior
        now = time.monotonic()
        elapsed = now - s.behavior_started_at

        if b == "wait":
            if s.attempt == 0:
                logger.info(
                    "Recovery WAIT: pausing %.1fs for obstacle to clear", self._cfg.wait_sec
                )
                s.attempt = 1
                return RecoveryOutcome.IN_PROGRESS
            if elapsed >= self._cfg.wait_sec:
                s.total_attempts += 1
                return RecoveryOutcome.SUCCEEDED
            return RecoveryOutcome.IN_PROGRESS

        elif b == "clear_costmap":
            if s.attempt == 0:
                logger.info("Recovery CLEAR_COSTMAP: clearing local costmap")
                try:
                    self._clear_fn()
                except Exception as exc:
                    logger.warning("clear_costmap failed: %s", exc)
                s.attempt = 1
                s.total_attempts += 1
                return RecoveryOutcome.SUCCEEDED  # instant

        elif b == "backup":
            if s.attempt == 0:
                logger.info(
                    "Recovery BACKUP: reversing %.2fm at %.2fm/s",
                    self._cfg.backup_distance_m,
                    self._cfg.backup_speed_mps,
                )
                try:
                    self._backup_fn(self._cfg.backup_distance_m, self._cfg.backup_speed_mps)
                except Exception as exc:
                    logger.warning("backup failed: %s", exc)
                s.attempt = 1
                return RecoveryOutcome.IN_PROGRESS
            # Allow 10 s for backup to complete
            if elapsed >= (
                self._cfg.backup_distance_m / max(self._cfg.backup_speed_mps, 0.01) + 3.0
            ):
                s.total_attempts += 1
                return RecoveryOutcome.SUCCEEDED

        elif b == "spin":
            if s.attempt == 0:
                logger.info("Recovery SPIN: rotating %d × 360°", self._cfg.spin_full_rotations)
                try:
                    self._spin_fn(self._cfg.spin_angular_speed_rps, self._cfg.spin_full_rotations)
                except Exception as exc:
                    logger.warning("spin failed: %s", exc)
                s.attempt = 1
                return RecoveryOutcome.IN_PROGRESS
            # Time estimate: 2π / speed * rotations + 2 s margin
            import math

            spin_time = (
                2
                * math.pi
                / max(self._cfg.spin_angular_speed_rps, 0.1)
                * self._cfg.spin_full_rotations
                + 2.0
            )
            if elapsed >= spin_time:
                s.total_attempts += 1
                return RecoveryOutcome.SUCCEEDED

        elif b == "replan":
            if s.attempt == 0:
                logger.info("Recovery REPLAN: requesting fresh global plan")
                s.attempt = 1
                s.total_attempts += 1
                return RecoveryOutcome.SUCCEEDED  # instant; nav node will retry

        elif b == "announce":
            if s.attempt == 0:
                logger.info("Recovery ANNOUNCE: requesting human clearance")
                try:
                    self._announce_fn(
                        "Excuse me, could you please step aside? I need to pass. Thank you!"
                    )
                except Exception as exc:
                    logger.warning("announce failed: %s", exc)
                s.attempt = 1
                return RecoveryOutcome.IN_PROGRESS
            if elapsed >= self._cfg.announce_repeat_sec:
                s.total_attempts += 1
                return RecoveryOutcome.SUCCEEDED

        elif b == "escalate":
            if s.attempt == 0:
                logger.warning("Recovery ESCALATE: requesting human staff assistance")
                try:
                    self._escalate_fn(f"Robot stuck — cannot navigate: {s.trigger_reason}")
                    self._announce_fn(
                        "I'm sorry, I'm unable to proceed. "
                        "I've alerted a staff member to assist."
                    )
                except Exception as exc:
                    logger.warning("escalate failed: %s", exc)
                s.attempt = 1
                s.total_attempts += 1
                # After escalation, mark as exhausted
                s.outcome = RecoveryOutcome.EXHAUSTED
                return RecoveryOutcome.EXHAUSTED

        else:
            logger.warning("Unknown recovery behavior: %r", b)
            s.total_attempts += 1
            return RecoveryOutcome.SUCCEEDED

        return RecoveryOutcome.IN_PROGRESS
