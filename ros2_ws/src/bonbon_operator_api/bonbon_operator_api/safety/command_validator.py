"""CommandValidator — validate command structure and content.

This is a pure-Python layer that checks constraints BEFORE the command
reaches the ROS2 bridge or safety gate.
"""

from __future__ import annotations

import logging
import re
import time
from collections import deque
from typing import Any

from bonbon_operator_api.models.command_models import (
    EmergencyStopCommand,
    NavigateCommand,
    SpeakCommand,
)

logger = logging.getLogger(__name__)

# Words that must never be sent to TTS
_BLOCKED_TTS_PATTERNS = re.compile(
    r"(password|secret|token|api[_\s]?key|credential)", re.IGNORECASE
)

# Navigation hard limits
_NAV_MAX_COORD = 200.0  # metres
_NAV_MIN_SPEED = 0.05  # m/s
_NAV_MAX_SPEED = 1.5  # m/s


class ValidationError(Exception):
    def __init__(self, message: str, code: str = "VALIDATION_ERROR") -> None:
        super().__init__(message)
        self.code = code


class CommandValidator:
    """Validate command payloads for structural and content correctness.

    Parameters
    ----------
    dedup_window_sec:
        Time window for duplicate command detection.
    dedup_capacity:
        Max recent commands held in the dedup buffer.
    """

    def __init__(
        self,
        dedup_window_sec: float = 5.0,
        dedup_capacity: int = 256,
    ) -> None:
        self._dedup_window = dedup_window_sec
        # (command_id, timestamp) pairs — ring buffer
        self._recent: deque[tuple[str, float]] = deque(maxlen=dedup_capacity)

    # ------------------------------------------------------------------
    # Per-command validators
    # ------------------------------------------------------------------

    def validate_speak(self, cmd: SpeakCommand) -> None:
        if not cmd.text.strip():
            raise ValidationError("Speak text must not be empty or whitespace")
        if _BLOCKED_TTS_PATTERNS.search(cmd.text):
            raise ValidationError("Speak text contains disallowed content", "BLOCKED_CONTENT")
        if len(cmd.text) > 500:
            raise ValidationError("Speak text exceeds 500 character limit")

    def validate_navigate(self, cmd: NavigateCommand) -> None:
        for coord, val in (("goal_x", cmd.goal_x), ("goal_y", cmd.goal_y)):
            if abs(val) > _NAV_MAX_COORD:
                raise ValidationError(
                    f"Navigation {coord}={val} exceeds map limit ±{_NAV_MAX_COORD} m",
                    "NAV_OUT_OF_BOUNDS",
                )
        if cmd.speed_limit_mps is not None:
            if not (_NAV_MIN_SPEED <= cmd.speed_limit_mps <= _NAV_MAX_SPEED):
                raise ValidationError(
                    f"speed_limit_mps={cmd.speed_limit_mps} outside "
                    f"[{_NAV_MIN_SPEED}, {_NAV_MAX_SPEED}]",
                    "NAV_SPEED_INVALID",
                )

    def validate_emergency_stop(self, cmd: EmergencyStopCommand) -> None:
        if not cmd.reason.strip():
            raise ValidationError("Emergency stop must include a reason")

    def validate_generic(self, command_type: str, payload: Any) -> None:
        """Route to the appropriate specific validator."""
        if command_type == "speak":
            self.validate_speak(payload)
        elif command_type == "navigate":
            self.validate_navigate(payload)
        elif command_type == "emergency_stop":
            self.validate_emergency_stop(payload)
        # pause/resume/dock/cancel have minimal validation

    # ------------------------------------------------------------------
    # Duplicate detection
    # ------------------------------------------------------------------

    def check_duplicate(self, command_id: str) -> bool:
        """Return True if *command_id* is a duplicate within the dedup window."""
        now = time.monotonic()
        # Expire old entries
        while self._recent and now - self._recent[0][1] > self._dedup_window:
            self._recent.popleft()
        # Check for duplicate
        for cid, _ in self._recent:
            if cid == command_id:
                return True
        self._recent.append((command_id, now))
        return False

    def register_command(self, command_id: str) -> None:
        """Register a command ID in the dedup buffer (idempotent)."""
        self.check_duplicate(command_id)  # side-effect: registers the ID
