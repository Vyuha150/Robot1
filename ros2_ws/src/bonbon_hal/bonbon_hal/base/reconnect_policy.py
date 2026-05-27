"""
bonbon_hal.base.reconnect_policy
==================================
Configurable exponential-backoff reconnection policy used by all HAL nodes.

Strategy
--------
  attempt 1 : wait base_delay_sec
  attempt 2 : wait base_delay_sec * backoff_factor
  attempt n : wait min(base * factor^(n-1), max_delay_sec)
  after max_attempts : give_up → report to Safety Supervisor

Jitter: ±10% of computed delay so multiple devices don't all retry at once.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ReconnectConfig:
    """All knobs for the reconnect policy — maps directly to ROS2 parameters."""

    max_attempts: int = 5  # 0 = unlimited
    base_delay_sec: float = 1.0  # first retry delay
    max_delay_sec: float = 30.0  # cap on any single delay
    backoff_factor: float = 2.0  # multiply delay each attempt
    jitter_fraction: float = 0.10  # ± this fraction of computed delay
    cooldown_sec: float = 60.0  # after give-up, wait before allowing a reset
    grace_after_connect_sec: float = 2.0  # ignore faults for N sec after connect


class ReconnectPolicy:
    """
    Stateful reconnect policy for one hardware device.

    Typical usage inside a ROS2 node timer callback:
    ::

        if driver.consecutive_errors > MAX_READ_ERRORS:
            if policy.should_attempt():
                delay = policy.next_wait_sec()
                time.sleep(delay)
                ok = driver.reconnect()
                if ok:
                    policy.record_success()
                else:
                    policy.record_failure()
            else:
                # Exhausted — report FAULT to safety supervisor
                ...
    """

    def __init__(self, device_name: str, config: ReconnectConfig | None = None) -> None:
        self._device = device_name
        self._cfg = config or ReconnectConfig()
        self._attempt = 0
        self._gave_up_at: float | None = None
        self._last_connect_ts: float = 0.0

    # ── Query ──────────────────────────────────────────────────────────────────

    def should_attempt(self) -> bool:
        """
        True if another reconnect attempt is permitted right now.
        Returns False after give-up until cooldown expires.
        """
        if self._gave_up_at is not None:
            # Check if cooldown passed → allow one more retry cycle
            if time.monotonic() - self._gave_up_at >= self._cfg.cooldown_sec:
                logger.info("[%s] Cooldown expired — resetting reconnect counter", self._device)
                self.reset()
            else:
                return False

        if self._cfg.max_attempts <= 0:
            return True  # unlimited

        return self._attempt < self._cfg.max_attempts

    def exhausted(self) -> bool:
        return self._gave_up_at is not None

    @property
    def attempt_count(self) -> int:
        return self._attempt

    def next_wait_sec(self) -> float:
        """
        Return how long to wait before the next attempt (with jitter).
        Does NOT block — caller decides whether to sleep.
        """
        raw = min(
            self._cfg.base_delay_sec * (self._cfg.backoff_factor**self._attempt),
            self._cfg.max_delay_sec,
        )
        jitter = raw * self._cfg.jitter_fraction * (2 * random.random() - 1)
        return max(0.1, raw + jitter)

    def in_grace_period(self) -> bool:
        """True if we just connected and should ignore transient faults."""
        if self._last_connect_ts == 0.0:
            return False
        return (time.monotonic() - self._last_connect_ts) < self._cfg.grace_after_connect_sec

    # ── Record outcomes ────────────────────────────────────────────────────────

    def record_failure(self) -> None:
        """Call after a failed reconnect attempt."""
        self._attempt += 1
        if self._cfg.max_attempts > 0 and self._attempt >= self._cfg.max_attempts:
            self._gave_up_at = time.monotonic()
            logger.error(
                "[%s] Reconnect EXHAUSTED after %d attempts — giving up",
                self._device,
                self._attempt,
            )
        else:
            logger.warning(
                "[%s] Reconnect attempt %d/%s failed",
                self._device,
                self._attempt,
                self._cfg.max_attempts if self._cfg.max_attempts > 0 else "∞",
            )

    def record_success(self) -> None:
        """Call after a successful reconnect."""
        logger.info(
            "[%s] Reconnected successfully after %d attempt(s)",
            self._device,
            self._attempt + 1,
        )
        self._last_connect_ts = time.monotonic()
        self.reset()

    def reset(self) -> None:
        """Reset the counter and gave-up state (e.g. after operator reset)."""
        self._attempt = 0
        self._gave_up_at = None
