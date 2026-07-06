"""LowConfidenceObjectHandler — the explicit gate between "detected at
some confidence" and "safe to act on."

`ObjectConfidenceCalibrator` already rejects detections below
`rejection_threshold` (never published at all). This handler operates on
what's left: detections that ARE published (they passed calibration) but
whose confidence is still below the higher `actionable_threshold` — these
must be visible (for dashboard/tracking/permanence) but must never, by
themselves, be treated as a trigger for behavior. That distinction is the
`is_actionable` flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ConfidenceState(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


@dataclass(frozen=True)
class LowConfidenceConfig:
    actionable_threshold: float = 0.6
    high_confidence_threshold: float = 0.85


@dataclass(frozen=True)
class ConfidenceAssessment:
    confidence: float
    state: ConfidenceState
    is_actionable: bool


class LowConfidenceObjectHandler:
    def __init__(self, config: LowConfidenceConfig | None = None) -> None:
        self._cfg = config or LowConfidenceConfig()

    def assess(self, confidence: float) -> ConfidenceAssessment:
        if confidence >= self._cfg.high_confidence_threshold:
            state = ConfidenceState.HIGH
        elif confidence >= self._cfg.actionable_threshold:
            state = ConfidenceState.NORMAL
        else:
            state = ConfidenceState.LOW
        return ConfidenceAssessment(
            confidence=confidence,
            state=state,
            is_actionable=confidence >= self._cfg.actionable_threshold,
        )
