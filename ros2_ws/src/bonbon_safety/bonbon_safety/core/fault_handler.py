"""Reusable fault-handling engine shared by every BonBon module.

This is the cross-cutting reliability layer the project was missing. It does
*not* replace the safety supervisor, HAL driver faults, or per-module health
reporting — it standardises how any module turns a detected fault into the full
required pipeline:

    detect → log → diagnostic event → safe fallback → recovery attempt → escalate

Core pieces
-----------
* :class:`Watchdog`     — detects *staleness* (a topic/sensor that stopped) and
                          *timeouts* (an operation that ran too long).
* :class:`RecoveryPolicy` — bounded retry with backoff + a terminal escalation
                          level when retries are exhausted.
* :class:`FaultHandler` — per-fault state machine that runs the pipeline and
                          emits :class:`FaultEvent` records via injected sinks.

Everything here is pure Python with an injectable clock, so it is fully unit
testable without ROS2. Nodes wire the sinks (``log_sink``, ``diagnostic_sink``,
``escalation_sink``) to their logger, a diagnostics publisher, and the
OperatorAlerter respectively.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

from bonbon_safety.core.fault_levels import (
    FALLBACK_LABEL,
    FallbackLevel,
    requires_operator,
)

_logger = logging.getLogger(__name__)

Clock = Callable[[], float]


# ── Fault event record ──────────────────────────────────────────────────────

@dataclass
class FaultEvent:
    """One occurrence of a fault, as it moves through the pipeline."""

    fault_id: str
    module: str
    level: FallbackLevel
    detail: str
    phase: str  # 'detected' | 'recovering' | 'recovered' | 'escalated' | 'cleared'
    recovery_attempt: int = 0
    timestamp: float = 0.0

    @property
    def level_label(self) -> str:
        return FALLBACK_LABEL[self.level]


# ── Watchdog: staleness + timeout detection ───────────────────────────────────

class Watchdog:
    """Detects a heartbeat/topic going stale, or an operation overrunning.

    Usage (staleness)::

        wd = Watchdog(timeout_sec=1.0)
        wd.pet()                 # call on every received message
        if wd.is_stale():        # call from a periodic check
            ...handle stale...

    Usage (operation timeout)::

        wd.start_operation()
        ...
        if wd.operation_exceeded(0.08):   # 80 ms budget
            ...handle timeout...
    """

    def __init__(self, timeout_sec: float, clock: Optional[Clock] = None) -> None:
        import time as _time
        self._timeout = max(0.0, timeout_sec)
        self._clock = clock or _time.monotonic
        self._last_pet: Optional[float] = None
        self._op_start: Optional[float] = None

    def pet(self) -> None:
        """Record a heartbeat (a message arrived / a cycle completed)."""
        self._last_pet = self._clock()

    def is_stale(self) -> bool:
        """True when no pet has occurred within ``timeout_sec``.

        A never-petted watchdog is considered stale (nothing has arrived yet).
        """
        if self._last_pet is None:
            return True
        return (self._clock() - self._last_pet) > self._timeout

    def seconds_since_pet(self) -> float:
        if self._last_pet is None:
            return float("inf")
        return self._clock() - self._last_pet

    def start_operation(self) -> None:
        self._op_start = self._clock()

    def operation_exceeded(self, budget_sec: float) -> bool:
        if self._op_start is None:
            return False
        return (self._clock() - self._op_start) > budget_sec

    def reset(self) -> None:
        self._last_pet = None
        self._op_start = None


# ── Recovery policy: bounded retry with backoff ───────────────────────────────

@dataclass
class RecoveryPolicy:
    """Bounded automatic-recovery policy for a fault.

    Attributes:
        max_attempts: How many recovery attempts before escalating.
        backoff_sec: Initial delay before the first retry.
        backoff_mult: Multiplier applied to the delay after each attempt.
        max_backoff_sec: Cap on the backoff delay.
        terminal_level: Fallback level to escalate to once attempts are spent.
    """

    max_attempts: int = 3
    backoff_sec: float = 0.5
    backoff_mult: float = 2.0
    max_backoff_sec: float = 10.0
    terminal_level: FallbackLevel = FallbackLevel.SAFE_STOP

    def delay_for_attempt(self, attempt: int) -> float:
        """Backoff delay (seconds) before the *attempt*-th retry (1-indexed)."""
        if attempt <= 0:
            return 0.0
        delay = self.backoff_sec * (self.backoff_mult ** (attempt - 1))
        return min(delay, self.max_backoff_sec)


# ── Fault definition (catalogue entry) ────────────────────────────────────────

@dataclass
class FaultDefinition:
    """Static description of a known failure mode (a catalogue row)."""

    fault_id: str
    module: str
    detection: str           # how it is detected
    level: FallbackLevel     # fallback level when active
    recovery: str            # recovery action (human-readable)
    user_facing: str         # what the user/robot does visibly
    operator_alert: bool     # whether an operator is alerted
    policy: RecoveryPolicy = field(default_factory=RecoveryPolicy)


# ── Fault handler: the per-fault pipeline ─────────────────────────────────────

class FaultHandler:
    """Runs the standard fault pipeline for a set of known fault definitions.

    Sinks (all optional; default to module logging):
        log_sink(event)         — structured log of every phase.
        diagnostic_sink(event)  — publish a diagnostics event.
        escalation_sink(event)  — raise an operator alert / safety escalation.
        recovery_fns[fault_id]  — callables returning True on successful recovery.
    """

    def __init__(
        self,
        definitions: Dict[str, FaultDefinition],
        *,
        clock: Optional[Clock] = None,
        log_sink: Optional[Callable[[FaultEvent], None]] = None,
        diagnostic_sink: Optional[Callable[[FaultEvent], None]] = None,
        escalation_sink: Optional[Callable[[FaultEvent], None]] = None,
    ) -> None:
        import time as _time
        self._defs = definitions
        self._clock = clock or _time.monotonic
        self._log_sink = log_sink or self._default_log
        self._diag_sink = diagnostic_sink
        self._esc_sink = escalation_sink
        self._recovery_fns: Dict[str, Callable[[], bool]] = {}
        # Live state per fault id.
        self._active: Dict[str, FaultEvent] = {}
        self._attempts: Dict[str, int] = {}

    # ── registration ─────────────────────────────────────────────────────────

    def register_recovery(self, fault_id: str, fn: Callable[[], bool]) -> None:
        """Register a recovery callable for ``fault_id`` (returns True on success)."""
        self._recovery_fns[fault_id] = fn

    # ── pipeline ──────────────────────────────────────────────────────────────

    def raise_fault(self, fault_id: str, detail: str = "") -> FaultEvent:
        """Report that ``fault_id`` is active. Runs detect→log→diagnostic→escalate.

        Idempotent while the fault stays active (re-raising updates detail but
        does not re-escalate unless the level rises).
        """
        defn = self._defs.get(fault_id)
        if defn is None:
            raise KeyError(f"Unknown fault_id '{fault_id}'")

        already = fault_id in self._active
        event = FaultEvent(
            fault_id=fault_id, module=defn.module, level=defn.level,
            detail=detail or defn.detection, phase="detected",
            recovery_attempt=self._attempts.get(fault_id, 0),
            timestamp=self._clock(),
        )
        self._active[fault_id] = event
        self._log_sink(event)
        if self._diag_sink:
            self._diag_sink(event)

        # Escalate to operator on first activation when the level demands it.
        if not already and (defn.operator_alert or requires_operator(defn.level)):
            esc = FaultEvent(**{**event.__dict__, "phase": "escalated"})
            if self._esc_sink:
                self._esc_sink(esc)
            self._log_sink(esc)
        return event

    def attempt_recovery(self, fault_id: str) -> bool:
        """Run one bounded recovery attempt for an active fault.

        Returns True if recovery succeeded (and the fault is cleared). When
        attempts are exhausted, escalates to the policy's terminal level.
        """
        if fault_id not in self._active:
            return True  # nothing to recover
        defn = self._defs[fault_id]
        fn = self._recovery_fns.get(fault_id)
        attempt = self._attempts.get(fault_id, 0) + 1
        self._attempts[fault_id] = attempt

        self._log_sink(FaultEvent(
            fault_id, defn.module, defn.level,
            f"recovery attempt {attempt}/{defn.policy.max_attempts}",
            phase="recovering", recovery_attempt=attempt, timestamp=self._clock(),
        ))

        succeeded = False
        if fn is not None:
            try:
                succeeded = bool(fn())
            except Exception as exc:  # noqa: BLE001
                _logger.error("Recovery fn for '%s' raised: %s", fault_id, exc)
                succeeded = False

        if succeeded:
            self.clear_fault(fault_id)
            return True

        if attempt >= defn.policy.max_attempts:
            # Exhausted — escalate to terminal level and require operator.
            term = FaultEvent(
                fault_id, defn.module, defn.policy.terminal_level,
                f"recovery exhausted after {attempt} attempts",
                phase="escalated", recovery_attempt=attempt, timestamp=self._clock(),
            )
            self._active[fault_id] = term
            self._log_sink(term)
            if self._diag_sink:
                self._diag_sink(term)
            if self._esc_sink:
                self._esc_sink(term)
        return False

    def clear_fault(self, fault_id: str) -> None:
        """Mark a fault resolved and reset its recovery counter."""
        if fault_id not in self._active:
            return
        defn = self._defs[fault_id]
        self._attempts.pop(fault_id, None)
        del self._active[fault_id]
        self._log_sink(FaultEvent(
            fault_id, defn.module, FallbackLevel.NORMAL, "fault cleared",
            phase="cleared", timestamp=self._clock(),
        ))

    # ── queries ───────────────────────────────────────────────────────────────

    def is_active(self, fault_id: str) -> bool:
        return fault_id in self._active

    def active_faults(self) -> Dict[str, FaultEvent]:
        return dict(self._active)

    def current_level(self) -> FallbackLevel:
        """The most severe fallback level across all active faults."""
        if not self._active:
            return FallbackLevel.NORMAL
        return FallbackLevel(max(int(e.level) for e in self._active.values()))

    @staticmethod
    def _default_log(event: FaultEvent) -> None:
        msg = "[fault:%s] %s/%s %s — %s"
        args = (event.phase, event.module, event.fault_id,
                event.level_label, event.detail)
        if event.level >= FallbackLevel.SAFE_STOP:
            _logger.error(msg, *args)
        elif event.level >= FallbackLevel.SAFE_PAUSE:
            _logger.warning(msg, *args)
        else:
            _logger.info(msg, *args)
