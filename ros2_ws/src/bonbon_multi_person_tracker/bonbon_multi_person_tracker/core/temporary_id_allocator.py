"""Allocates stable, human-readable temporary IDs for unidentified persons."""

from __future__ import annotations

import itertools
import uuid


class TemporaryIdAllocator:
    """Generates ``person_track_id`` (UUID-based, for message keys) and
    ``temporary_person_id`` (human-friendly "Person_3", for operator UI/logs)
    pairs. The counter is monotonic for the lifetime of the scene manager —
    it is never reused, even after a person leaves, so two different
    individuals are never shown under the same label within one session.
    """

    def __init__(self) -> None:
        self._counter = itertools.count(1)

    def allocate(self) -> tuple[str, str]:
        n = next(self._counter)
        person_track_id = f"ptrk_{uuid.uuid4().hex[:12]}"
        temporary_person_id = f"Person_{n}"
        return person_track_id, temporary_person_id
