"""Caches the latest VoiceEmotion from bonbon_affective_ai for turn-building.

Honest limitation: bonbon_affective_ai's voice emotion analyzer is currently
triggered directly off raw audio chunks with an empty person_id (see
affective_ai_node._cb_audio) — it is not itself attributed to a specific
speaker. This cache therefore offers only "the most recent voice emotion
reading, if recent enough to plausibly belong to this turn" — not a verified
per-speaker emotion. That is the best honest claim available without
changing bonbon_affective_ai's own attribution (out of scope here — this
package consumes that module's output, it does not change it).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class VoiceEmotionReading:
    dominant_emotion: str
    dominant_confidence: float
    received_at: float


class VoiceEmotionCache:
    def __init__(self, max_age_sec: float = 3.0, clock: Callable[[], float] | None = None) -> None:
        self._max_age = max_age_sec
        self._clock = clock or time.monotonic
        self._latest: VoiceEmotionReading | None = None

    def update(self, dominant_emotion: str, dominant_confidence: float) -> None:
        self._latest = VoiceEmotionReading(dominant_emotion, dominant_confidence, self._clock())

    def get_if_fresh(self) -> tuple[str, float]:
        """Returns ``(dominant_emotion, dominant_confidence)`` if a reading
        arrived within ``max_age_sec``, otherwise ``("", 0.0)`` — never a
        stale guess."""
        if self._latest is None:
            return "", 0.0
        if self._clock() - self._latest.received_at > self._max_age:
            return "", 0.0
        return self._latest.dominant_emotion, self._latest.dominant_confidence
