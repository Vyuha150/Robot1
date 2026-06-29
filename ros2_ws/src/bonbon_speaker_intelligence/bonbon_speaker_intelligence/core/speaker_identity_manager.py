"""Persistent speaker identity across utterances.

Why this exists
----------------
bonbon_speech's diarizer resets its speaker labels every utterance call
(``SPEAKER_00``, ``SPEAKER_01``, ...) — there is no acoustic-embedding model
anywhere in this repo that could recognise "this is the same voice as five
seconds ago" across separate diarizer invocations. Re-implementing a
voiceprint model here would be real ML work this project doesn't have, and
inventing a fake one would be worse than not having identity continuity at
all.

What this DOES do, honestly
----------------------------
Uses the one real, already-available continuity signal: direction-of-arrival
(``doa_angle_deg``, from the HAL mic array). If a new utterance's DOA is
within ``doa_tolerance_deg`` of a recently-active speaker's last known DOA
(within ``recency_window_sec``), it's treated as the same speaker. Otherwise
a new persistent ``speaker_id`` is allocated. This is a real, working
heuristic — not a placeholder — but it is NOT a voiceprint: two different
people standing in the same direction in quick succession will be merged,
and the same person moving will be treated as new. Document this limitation
to callers; do not oversell it as identity recognition.

A real acoustic speaker-embedding backend would slot in here as an
additional/alternative match strategy without changing the public interface.
"""

from __future__ import annotations

import itertools
import time
from collections.abc import Callable
from dataclasses import dataclass

_UNKNOWN_DOA_DEG = -1.0  # sentinel convention shared with AudioChunk/SpeechCommand


def _is_unknown_doa(doa_deg: float) -> bool:
    """True for the HAL '-1.0 = unknown' sentinel — NOT true for ordinary
    negative bearings (which legitimately range -180..180, negative meaning
    the robot's right side, per the SpatialEntity/PersonState convention)."""
    return abs(doa_deg - _UNKNOWN_DOA_DEG) < 1e-6


@dataclass
class SpeakerIdentityConfig:
    doa_tolerance_deg: float = 20.0
    recency_window_sec: float = 8.0


class SpeakerIdentityManager:
    def __init__(
        self,
        config: SpeakerIdentityConfig | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._cfg = config or SpeakerIdentityConfig()
        self._clock = clock or time.monotonic
        # speaker_id -> (last_doa_deg, last_active_t)
        self._registry: dict[str, tuple[float, float]] = {}
        self._counter = itertools.count(1)

    def resolve(self, doa_deg: float) -> tuple[str, bool]:
        """Returns ``(speaker_id, is_new_speaker)``.

        Args:
            doa_deg: Direction-of-arrival for this utterance, degrees.
                Negative values (e.g. -1.0, the HAL convention for "unknown")
                are treated as unknown and never match an existing speaker —
                an unknown DOA always allocates a new identity rather than
                guessing.
        """
        now = self._clock()
        self._evict_stale(now)

        best_id: str | None = None
        best_delta = float("inf")
        if not _is_unknown_doa(doa_deg):
            for speaker_id, (last_doa, last_t) in self._registry.items():
                if now - last_t > self._cfg.recency_window_sec:
                    continue
                if _is_unknown_doa(last_doa):
                    continue
                delta = abs(_angle_diff(doa_deg, last_doa))
                if delta <= self._cfg.doa_tolerance_deg and delta < best_delta:
                    best_id, best_delta = speaker_id, delta

        if best_id is not None:
            self._registry[best_id] = (doa_deg, now)
            return best_id, False

        new_id = f"voice_{next(self._counter)}"
        self._registry[new_id] = (doa_deg, now)
        return new_id, True

    def _evict_stale(self, now: float) -> None:
        stale = [
            sid
            for sid, (_, t) in self._registry.items()
            if now - t > self._cfg.recency_window_sec * 4
        ]
        for sid in stale:
            del self._registry[sid]

    @property
    def known_speaker_count(self) -> int:
        return len(self._registry)


def _angle_diff(a: float, b: float) -> float:
    """Smallest signed difference between two angles in degrees, wrapped to [-180, 180]."""
    d = (a - b + 180.0) % 360.0 - 180.0
    return d
