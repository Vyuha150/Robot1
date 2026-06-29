"""Object memory hook — interface + in-memory store.

Full persistence into bonbon_data_stores (the project's existing persistence
package) is a real integration this package doesn't own — this hook defines
the seam (record/query an object's last-known state by class+area) with an
in-memory implementation so callers have a working default without a DB
dependency. A real backend would implement the same interface against
bonbon_data_stores.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ObjectMemoryEntry:
    object_track_id: str
    class_name: str
    last_x: float
    last_y: float
    last_z: float
    last_seen_at: float


class ObjectMemoryHookInterface(ABC):
    @abstractmethod
    def remember(self, entry: ObjectMemoryEntry) -> None: ...

    @abstractmethod
    def recall(self, object_track_id: str) -> ObjectMemoryEntry | None: ...

    @abstractmethod
    def recall_by_class(self, class_name: str) -> list[ObjectMemoryEntry]: ...


class InMemoryObjectMemoryHook(ObjectMemoryHookInterface):
    def __init__(self, max_entries: int = 500) -> None:
        self._entries: dict[str, ObjectMemoryEntry] = {}
        self._max_entries = max_entries

    def remember(self, entry: ObjectMemoryEntry) -> None:
        if entry.object_track_id not in self._entries and len(self._entries) >= self._max_entries:
            oldest_id = min(self._entries, key=lambda k: self._entries[k].last_seen_at)
            del self._entries[oldest_id]
        self._entries[entry.object_track_id] = entry

    def recall(self, object_track_id: str) -> ObjectMemoryEntry | None:
        return self._entries.get(object_track_id)

    def recall_by_class(self, class_name: str) -> list[ObjectMemoryEntry]:
        return [e for e in self._entries.values() if e.class_name == class_name]
