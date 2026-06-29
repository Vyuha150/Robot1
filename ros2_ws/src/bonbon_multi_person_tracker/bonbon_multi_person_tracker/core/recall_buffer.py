"""Short-lived memory of recently-departed known people.

When a person's record reaches LEFT_SCENE, their person_track_id is retired —
per the project brief ("new person replaces old person -> create new temporary
profile"), a later arrival always gets a brand-new identity-lifecycle record,
never a resurrected old one. But if that departed person WAS recognized
(known_person_id set from face_id), we don't want the robot to "forget" them
the instant they step out of frame and back in — this buffer lets a brand-new
record immediately recover known_person_id on arrival via a face_id or
body_embedding_id match, without reusing the old person_track_id.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class _RecallEntry:
    known_person_id: str
    body_embedding_id: str
    departed_at: float


class RecallBuffer:
    def __init__(
        self, recall_window_sec: float = 300.0, clock: Callable[[], float] | None = None
    ) -> None:
        self._window = recall_window_sec
        self._clock = clock or time.monotonic
        self._entries: list[_RecallEntry] = []

    def remember(self, known_person_id: str, body_embedding_id: str = "") -> None:
        if not known_person_id and not body_embedding_id:
            return
        self._entries.append(_RecallEntry(known_person_id, body_embedding_id, self._clock()))
        self._evict_expired()

    def try_recall(self, face_id: str = "", body_embedding_id: str = "") -> str:
        """Returns the known_person_id to backfill, or '' if no recall match."""
        self._evict_expired()
        if face_id:
            for e in self._entries:
                if e.known_person_id and e.known_person_id == face_id:
                    return e.known_person_id
        if body_embedding_id:
            for e in self._entries:
                if e.body_embedding_id and e.body_embedding_id == body_embedding_id:
                    return e.known_person_id
        return ""

    def _evict_expired(self) -> None:
        now = self._clock()
        self._entries = [e for e in self._entries if now - e.departed_at <= self._window]

    def __len__(self) -> int:
        return len(self._entries)
