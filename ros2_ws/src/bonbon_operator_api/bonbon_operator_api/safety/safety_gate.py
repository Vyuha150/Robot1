"""SafetyCommandGate — final safety check before any command reaches ROS2.

Rules
-----
1. EMERGENCY STOP: always accepted regardless of safety state.
2. Any command while safety_state == emergency_stop: rejected EXCEPT
   emergency_stop itself (reset flow handled by safety supervisor).
3. Commands from non-authorised roles: rejected (done in dependencies,
   but double-checked here as defence-in-depth).
4. Every decision (accept or reject) is logged to the audit trail.

The gate NEVER bypasses the Safety Supervisor node.  It is a pre-filter
on the HTTP/WebSocket side — not a replacement for the real safety system.
"""

from __future__ import annotations

import logging
import time

from bonbon_operator_api.safety.command_validator import CommandValidator, ValidationError

logger = logging.getLogger(__name__)

# Commands that are always permitted regardless of safety state
_ALWAYS_PERMITTED = frozenset({"emergency_stop"})

# Commands blocked while robot is in a halted state
_BLOCKED_DURING_HALT = frozenset(
    {
        "navigate",
        "dock",
        "resume",
    }
)

# Safety states considered "halted"
_HALTED_STATES = frozenset({"emergency_stop", "safety_stop"})


class SafetyGateError(Exception):
    def __init__(self, message: str, code: str = "SAFETY_GATE_REJECTED") -> None:
        super().__init__(message)
        self.code = code


class SafetyCommandGate:
    """Gate every command through safety checks before it hits ROS2.

    Parameters
    ----------
    validator:
        ``CommandValidator`` instance for structural validation.
    status_aggregator:
        ``RobotStatusAggregator`` to read current safety state from.
    audit_logger:
        ``AuditLogger`` to record gate decisions.
    """

    def __init__(self, validator: CommandValidator, status_aggregator, audit_logger) -> None:
        self._validator = validator
        self._aggregator = status_aggregator
        self._audit = audit_logger

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_and_validate(
        self,
        command_type: str,
        payload,
        command_id: str,
        actor_id: str,
        actor_name: str,
        actor_role: str,
        ip_address: str = "",
    ) -> None:
        """Run all safety checks.  Raises ``SafetyGateError`` or ``ValidationError``
        if the command must be blocked.  Records the decision in the audit log."""

        t0 = time.monotonic()

        # 1. Structural validation (pydantic + content checks)
        try:
            self._validator.validate_generic(command_type, payload)
        except ValidationError as exc:
            self._audit.log(
                actor_id=actor_id,
                actor_name=actor_name,
                actor_role=actor_role,
                action=f"command:{command_type}",
                target=command_id,
                request_data={"command_type": command_type},
                outcome="validation_error",
                detail=str(exc),
                ip_address=ip_address,
                duration_ms=(time.monotonic() - t0) * 1000,
            )
            raise

        # 2. Duplicate check
        if self._validator.check_duplicate(command_id):
            msg = f"Duplicate command_id={command_id} within dedup window"
            logger.warning(msg)
            self._audit.log(
                actor_id=actor_id,
                actor_name=actor_name,
                actor_role=actor_role,
                action=f"command:{command_type}",
                target=command_id,
                outcome="duplicate_rejected",
                detail=msg,
                ip_address=ip_address,
            )
            raise SafetyGateError(msg, "DUPLICATE_COMMAND")

        # 3. Safety state checks
        safety_state = self._get_safety_state()

        if command_type in _ALWAYS_PERMITTED:
            # Emergency stop: log and pass immediately
            self._audit.log(
                actor_id=actor_id,
                actor_name=actor_name,
                actor_role=actor_role,
                action=f"command:{command_type}",
                target=command_id,
                outcome="accepted_emergency",
                detail=f"safety_state={safety_state}",
                ip_address=ip_address,
                duration_ms=(time.monotonic() - t0) * 1000,
            )
            logger.warning("EMERGENCY STOP accepted from user=%s role=%s", actor_name, actor_role)
            return

        if safety_state in _HALTED_STATES and command_type in _BLOCKED_DURING_HALT:
            msg = (
                f"Command '{command_type}' blocked: robot safety state is '{safety_state}'. "
                "Resolve safety halt before issuing motion commands."
            )
            logger.error(msg)
            self._audit.log(
                actor_id=actor_id,
                actor_name=actor_name,
                actor_role=actor_role,
                action=f"command:{command_type}",
                target=command_id,
                outcome="safety_blocked",
                detail=msg,
                ip_address=ip_address,
                duration_ms=(time.monotonic() - t0) * 1000,
            )
            raise SafetyGateError(msg, "SAFETY_STATE_BLOCKED")

        # 4. Accept and audit
        self._audit.log(
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            action=f"command:{command_type}",
            target=command_id,
            outcome="accepted",
            detail=f"safety_state={safety_state}",
            ip_address=ip_address,
            duration_ms=(time.monotonic() - t0) * 1000,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_safety_state(self) -> str:
        try:
            status = self._aggregator.get_status()
            return status.safety.state
        except Exception:
            return "unknown"
