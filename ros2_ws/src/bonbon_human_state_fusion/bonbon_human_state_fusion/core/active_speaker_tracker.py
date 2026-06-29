"""Tracks per-person speaking recency from SpeakerTurn events.

Also answers "who was speaking most recently overall" — used to bridge
UserIntent/TextEmotion (keyed by the diarizer's per-utterance speaker_id, a
different ID space than person_track_id) to a person_track_id: text always
follows speech, and there is normally one active speaker at a time, so the
most recent speaker turn is the best honest guess for "whose words these
are." When no turn is recent enough, no attribution is made — never guessed
across an implausible gap.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

SPEAKING = "speaking"
RECENTLY_SPOKE = "recently_spoke"
SILENT = "silent"
UNKNOWN = "unknown"


@dataclass
class _SpeechRecord:
    last_transcript: str
    last_transcript_confidence: float
    last_speech_time: float


class ActiveSpeakerTracker:
    def __init__(
        self,
        speaking_window_sec: float = 2.0,
        recently_spoke_window_sec: float = 15.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._speaking_window = speaking_window_sec
        self._recently_spoke_window = recently_spoke_window_sec
        self._clock = clock or time.monotonic
        self._records: dict[str, _SpeechRecord] = {}
        self._most_recent_person_track_id: str = ""
        self._most_recent_time: float = -1.0

    def record_turn(
        self, person_track_id: str, transcript: str, transcript_confidence: float
    ) -> None:
        if not person_track_id:
            return
        now = self._clock()
        self._records[person_track_id] = _SpeechRecord(transcript, transcript_confidence, now)
        if now >= self._most_recent_time:
            self._most_recent_time = now
            self._most_recent_person_track_id = person_track_id

    def status_for(self, person_track_id: str) -> str:
        rec = self._records.get(person_track_id)
        if rec is None:
            return UNKNOWN
        age = self._clock() - rec.last_speech_time
        if age <= self._speaking_window:
            return SPEAKING
        if age <= self._recently_spoke_window:
            return RECENTLY_SPOKE
        return SILENT

    def last_transcript_for(self, person_track_id: str) -> tuple[str, float]:
        rec = self._records.get(person_track_id)
        if rec is None:
            return "", 0.0
        return rec.last_transcript, rec.last_transcript_confidence

    def most_recent_speaker(self, max_age_sec: float) -> str:
        """Returns the person_track_id of whoever spoke most recently, if
        within *max_age_sec* — otherwise "" (never a stale guess)."""
        if not self._most_recent_person_track_id:
            return ""
        if self._clock() - self._most_recent_time > max_age_sec:
            return ""
        return self._most_recent_person_track_id

    def forget(self, person_track_id: str) -> None:
        self._records.pop(person_track_id, None)
        if self._most_recent_person_track_id == person_track_id:
            self._most_recent_person_track_id = ""
            self._most_recent_time = -1.0
