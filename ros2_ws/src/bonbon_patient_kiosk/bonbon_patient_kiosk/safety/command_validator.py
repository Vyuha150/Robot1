"""CommandValidator — structural validation before anything reaches ROS2.

Scope is intentionally narrow: this package only ever issues two kinds of
ROS2-bound requests — a wayfinding/navigation request and a panic/emergency
alert. Chat text goes to bonbon_llm's own safety stack (SafetyCommandFilter,
HallucinationGuard), not duplicated here.
"""

from __future__ import annotations

import re
import time
from collections import deque

logger_name = __name__

# named_location must match bonbon_navigation's map_manager key format —
# lowercase, digits, underscores only.
_VALID_NAMED_LOCATION = re.compile(r"^[a-z0-9_]{1,64}$")


class ValidationError(Exception):
    def __init__(self, message: str, code: str = "VALIDATION_ERROR") -> None:
        super().__init__(message)
        self.code = code


class CommandValidator:
    def __init__(self, dedup_window_sec: float = 5.0, dedup_capacity: int = 256) -> None:
        self._dedup_window = dedup_window_sec
        self._recent: deque[tuple[str, float]] = deque(maxlen=dedup_capacity)

    def validate_named_location(self, named_location: str) -> None:
        if not named_location or not _VALID_NAMED_LOCATION.match(named_location):
            raise ValidationError(
                f"named_location '{named_location}' is not a valid location key",
                "INVALID_LOCATION",
            )

    def validate_panic_reason(self, reason: str) -> None:
        if not reason.strip():
            raise ValidationError("Panic alert must include a reason")
        if len(reason) > 300:
            raise ValidationError("Panic reason exceeds 300 character limit")

    def check_duplicate(self, command_id: str) -> bool:
        now = time.monotonic()
        while self._recent and now - self._recent[0][1] > self._dedup_window:
            self._recent.popleft()
        for cid, _ in self._recent:
            if cid == command_id:
                return True
        self._recent.append((command_id, now))
        return False
