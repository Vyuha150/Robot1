"""
bonbon_perception_ai.memory.memory_manager
==========================================
Unified interface that combines FAISSVectorStore and StructuredStore.

Callers interact exclusively with MemoryManager; the two backing stores are
an implementation detail.

Privacy controls
----------------
* anonymize_persons = True  → person IDs are hashed before storage
* store_faces = False        → face_id is never persisted
* forget_person(id)         → hard-delete from all stores (GDPR)
* purge_old_data()          → time-based eviction of old episodes
"""

from __future__ import annotations

import hashlib
from typing import Any

from bonbon_perception_ai.config.perception_config import MemoryConfig
from bonbon_perception_ai.memory.structured_store import StructuredStore
from bonbon_perception_ai.memory.vector_store import EpisodeRecord, FAISSVectorStore
from bonbon_perception_ai.understanding.intent_engine import UserIntent
from bonbon_perception_ai.understanding.scene_analyzer import SceneSnapshot


class MemoryManager:
    """
    High-level memory API for the perception AI node.

    Call open() before first use; call close() on shutdown.
    """

    def __init__(self, cfg: MemoryConfig) -> None:
        self.cfg = cfg
        self._vector = FAISSVectorStore(cfg)
        self._structured = StructuredStore(cfg)
        self._open = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def open(self) -> None:
        self._vector.load()
        self._structured.open()
        self._open = True

    def close(self) -> None:
        self._structured.close()
        self._open = False

    # ── Scene memory ──────────────────────────────────────────────────────────

    def record_scene(self, snap: SceneSnapshot) -> None:
        """Persist a scene snapshot to both stores."""
        if not self._open:
            return
        self._vector.add(snap)
        self._structured.log_scene(snap)

        # Also update known-objects table
        for cls_name in snap.present_object_classes:
            self._structured.upsert_object(cls_name, confidence=0.8)

    def recall_similar_scenes(self, query: SceneSnapshot, k: int = 5) -> list[EpisodeRecord]:
        """Return up to k past scenes semantically similar to query."""
        if not self._open:
            return []
        return self._vector.search(query, k)

    # ── Person memory ─────────────────────────────────────────────────────────

    def record_person(
        self,
        person_id: str,
        face_id: str = "",
    ) -> None:
        if not self._open:
            return
        safe_id = self._safe_id(person_id)
        safe_fid = face_id if self.cfg.privacy_store_faces else ""
        self._structured.upsert_person(
            safe_id,
            face_id=safe_fid,
            is_anonymous=self.cfg.privacy_anonymize_persons,
        )

    def record_interaction(self, person_id: str, intent: UserIntent) -> None:
        if not self._open:
            return
        safe_id = self._safe_id(person_id)
        self._structured.upsert_person(safe_id)
        self._structured.log_interaction(safe_id, intent)

    def get_person_history(self, person_id: str) -> dict[str, Any] | None:
        if not self._open:
            return None
        safe_id = self._safe_id(person_id)
        info = self._structured.get_person(safe_id)
        if info is None:
            return None
        interactions = self._structured.get_recent_interactions(safe_id)
        return {"person": info, "interactions": interactions}

    def is_known_person(self, person_id: str) -> bool:
        return self.get_person_history(person_id) is not None

    # ── GDPR / privacy ────────────────────────────────────────────────────────

    def forget_person(self, person_id: str) -> None:
        """Permanently erase all memory of a person."""
        if not self._open:
            return
        safe_id = self._safe_id(person_id)
        self._structured.forget_person(safe_id)

    def purge_old_data(self) -> int:
        """Delete episodes older than episode_ttl_days. Returns rows deleted."""
        if not self._open:
            return 0
        max_age = self.cfg.episode_ttl_days * 86_400
        return self._structured.purge_stale(max_age)

    # ── Diagnostics ───────────────────────────────────────────────────────────

    @property
    def episode_count(self) -> int:
        return self._vector.episode_count

    @property
    def vector_backend(self) -> str:
        return self._vector.backend

    def list_known_persons(self) -> list[dict[str, Any]]:
        if not self._open:
            return []
        return self._structured.list_persons()

    def list_known_objects(self) -> list[dict[str, Any]]:
        if not self._open:
            return []
        return self._structured.get_known_objects()

    # ── Privacy helper ────────────────────────────────────────────────────────

    def _safe_id(self, person_id: str) -> str:
        """When anonymize_persons is True, hash the person ID."""
        if not self.cfg.privacy_anonymize_persons:
            return person_id
        h = hashlib.sha256(person_id.encode()).hexdigest()[:12]
        return f"anon_{h}"
