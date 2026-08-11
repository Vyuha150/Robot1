"""KioskSafetyGate — final check before a wayfinding/panic request reaches ROS2.

Mirrors bonbon_operator_api's SafetyCommandGate. This gate NEVER bypasses the
Safety Supervisor or bonbon_navigation's own safety pipeline — it is a
pre-filter that rejects obviously-invalid or duplicate requests and records
every decision to the audit trail before the ROS2 bridge is even called.

Panic/emergency alerts are always permitted through — a patient in distress
must never be blocked by a validation quirk.
"""

from __future__ import annotations

import logging
import time

from bonbon_patient_kiosk.safety.command_validator import CommandValidator, ValidationError

logger = logging.getLogger(__name__)

_ALWAYS_PERMITTED = frozenset({"panic"})


class SafetyGateError(Exception):
    def __init__(self, message: str, code: str = "SAFETY_GATE_REJECTED") -> None:
        super().__init__(message)
        self.code = code


class KioskSafetyGate:
    def __init__(self, validator: CommandValidator, audit_logger) -> None:
        self._validator = validator
        self._audit = audit_logger

    def check_navigation(
        self, named_location: str, command_id: str, session_id: str, ip_address: str = ""
    ) -> None:
        t0 = time.monotonic()
        try:
            self._validator.validate_named_location(named_location)
        except ValidationError as exc:
            self._audit.log(
                actor_id=session_id,
                actor_role="patient",
                action="command:navigate",
                target=command_id,
                outcome="validation_error",
                detail=str(exc),
                ip_address=ip_address,
                duration_ms=(time.monotonic() - t0) * 1000,
            )
            raise

        if self._validator.check_duplicate(command_id):
            msg = f"Duplicate command_id={command_id} within dedup window"
            self._audit.log(
                actor_id=session_id,
                actor_role="patient",
                action="command:navigate",
                target=command_id,
                outcome="duplicate_rejected",
                detail=msg,
                ip_address=ip_address,
            )
            raise SafetyGateError(msg, "DUPLICATE_COMMAND")

        self._audit.log(
            actor_id=session_id,
            actor_role="patient",
            action="command:navigate",
            target=command_id,
            outcome="accepted",
            request_data={"named_location": named_location},
            ip_address=ip_address,
            duration_ms=(time.monotonic() - t0) * 1000,
        )

    def check_panic(self, reason: str, command_id: str, session_id: str, ip_address: str = "") -> None:
        try:
            self._validator.validate_panic_reason(reason)
        except ValidationError:
            reason = "unspecified"  # never block a panic alert on validation
        self._audit.log(
            actor_id=session_id,
            actor_role="patient",
            action="command:panic",
            target=command_id,
            outcome="accepted_emergency",
            request_data={"reason": reason},
        )
        logger.warning("PANIC alert accepted from session=%s reason=%s", session_id, reason)
