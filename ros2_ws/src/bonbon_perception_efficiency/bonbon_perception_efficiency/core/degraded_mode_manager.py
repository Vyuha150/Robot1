"""DegradedModeManager — tracks a SYSTEM-WIDE perception degraded mode,
distinct from each package's own internal degraded flag (bonbon_vision's
DetectedObjectArray.is_degraded, bonbon_gesture's backend fallback, etc. —
those stay exactly as they are, this does not touch them).

Activates only on SUSTAINED pressure (a configurable duration at
MINIMAL/CRITICAL load), not a single bad cycle — same "don't react to one
frame" principle used throughout this project's lifecycle state machines.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from bonbon_perception_efficiency.core.load_shedding_controller import LoadLevel


@dataclass
class DegradedModeStatus:
    is_degraded: bool
    reason: str
    duration_sec: float


class DegradedModeManager:
    def __init__(
        self, sustained_threshold_sec: float = 10.0, clock: Callable[[], float] | None = None
    ) -> None:
        self._threshold = sustained_threshold_sec
        self._clock = clock or time.monotonic
        self._pressure_since: float | None = None
        self._degraded_since: float | None = None

    def update(self, load_level: LoadLevel, safety_fault_or_above: bool) -> DegradedModeStatus:
        now = self._clock()

        if safety_fault_or_above:
            # A safety FAULT/SAFE_STOP is itself already a serious, reported
            # state — perception degraded mode reflects it immediately
            # without waiting out the sustained-pressure window.
            if self._degraded_since is None:
                self._degraded_since = now
            return DegradedModeStatus(
                True, "safety level FAULT or above", now - self._degraded_since
            )

        under_pressure = load_level in (LoadLevel.MINIMAL, LoadLevel.CRITICAL)
        if not under_pressure:
            self._pressure_since = None
            if self._degraded_since is not None:
                self._degraded_since = None
            return DegradedModeStatus(False, "nominal", 0.0)

        if self._pressure_since is None:
            self._pressure_since = now

        elapsed = now - self._pressure_since
        if elapsed >= self._threshold:
            if self._degraded_since is None:
                self._degraded_since = now
            return DegradedModeStatus(
                True,
                f"sustained {load_level.value} load for {elapsed:.0f}s",
                now - self._degraded_since,
            )

        return DegradedModeStatus(False, f"{load_level.value} load, not yet sustained", 0.0)
