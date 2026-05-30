"""OperatorAlerter — deduplicating, rate-limited operator-alert manager.

The behaviour engine is the single place that decides a human operator must be
notified (medical emergency, restricted-zone breach, predicted collision,
repeated command rejection, safety fault). Raising a fresh ROS2 alert on every
matching message would flood the operator console, so this module:

* **Deduplicates** alerts by ``(alert_type, subject_id)`` within a cooldown.
* **Escalates** when an alert's severity rises above a previously-sent one for
  the same key (a re-alert fires immediately, bypassing the cooldown).
* **Rate-limits** each alert key independently.

It holds no ROS2 dependency — the node converts an :class:`AlertDecision` into a
``RiskEvent`` and publishes it. Pure logic → fully unit-testable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

_logger = logging.getLogger(__name__)

# Severity ordering (mirrors bonbon_msgs/RiskEvent severity constants).
SEVERITY_INFO = 0
SEVERITY_LOW = 1
SEVERITY_MEDIUM = 2
SEVERITY_HIGH = 3
SEVERITY_CRITICAL = 4

_SEVERITY_LABEL = {0: "info", 1: "low", 2: "medium", 3: "high", 4: "critical"}

DEFAULT_COOLDOWN_SEC = 10.0


@dataclass
class AlertDecision:
    """The outcome of an alert request."""

    should_send: bool
    alert_type: str
    severity: int
    severity_label: str
    subject_id: str
    description: str
    suppressed_reason: str = ""


class OperatorAlerter:
    """Decides whether an operator alert should actually be dispatched.

    Args:
        cooldown_sec: Per-(type, subject) minimum seconds between repeat alerts
            of the same-or-lower severity.
        clock: Monotonic time source (injectable for tests).
    """

    def __init__(
        self,
        cooldown_sec: float = DEFAULT_COOLDOWN_SEC,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._cooldown = cooldown_sec
        import time as _time
        self._clock = clock or _time.monotonic
        # key → (last_sent_time, last_severity)
        self._last: Dict[Tuple[str, str], Tuple[float, int]] = {}
        # Telemetry
        self.total_requested = 0
        self.total_sent = 0
        self.total_suppressed = 0

    def request(
        self,
        alert_type: str,
        severity: int,
        subject_id: str,
        description: str,
    ) -> AlertDecision:
        """Request an operator alert; decide whether it fires now.

        Args:
            alert_type: e.g. 'medical_emergency', 'restricted_zone',
                'collision_risk', 'command_rejected', 'safety_fault'.
            severity: One of the SEVERITY_* constants.
            subject_id: Entity/person/scene the alert concerns (dedup key).
            description: Human-readable detail.

        Returns:
            An :class:`AlertDecision`. ``should_send`` is True when the node
            should publish the alert.
        """
        self.total_requested += 1
        key = (alert_type, subject_id)
        now = self._clock()
        label = _SEVERITY_LABEL.get(severity, "info")

        prev = self._last.get(key)
        if prev is not None:
            last_time, last_sev = prev
            within_cooldown = (now - last_time) < self._cooldown
            escalated = severity > last_sev
            if within_cooldown and not escalated:
                self.total_suppressed += 1
                return AlertDecision(
                    should_send=False,
                    alert_type=alert_type,
                    severity=severity,
                    severity_label=label,
                    subject_id=subject_id,
                    description=description,
                    suppressed_reason=(
                        f"duplicate within {self._cooldown:.0f}s cooldown "
                        f"(severity {label} ≤ previous {_SEVERITY_LABEL.get(last_sev)})"
                    ),
                )

        # Fire.
        self._last[key] = (now, severity)
        self.total_sent += 1
        if severity >= SEVERITY_HIGH:
            _logger.warning("OPERATOR ALERT [%s] %s: %s", label, alert_type, description)
        else:
            _logger.info("Operator alert [%s] %s: %s", label, alert_type, description)
        return AlertDecision(
            should_send=True,
            alert_type=alert_type,
            severity=severity,
            severity_label=label,
            subject_id=subject_id,
            description=description,
        )

    def reset(self) -> None:
        """Clear dedup history (e.g. on deactivate)."""
        self._last.clear()
