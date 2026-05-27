"""
bonbon_perception_ai.memory.structured_store
============================================
SQLite-backed store for structured robot memory.

Schema
------
persons           — one row per tracked person
interactions      — one row per speech interaction
scene_episodes    — lightweight log of analyzed scenes
known_objects     — persistent object observations

Privacy
-------
* `forget_person(person_id)` hard-deletes all linked rows (GDPR-style).
* `purge_stale(max_age_sec)` removes old scene_episodes.
* face_id is stored only when cfg.privacy_store_faces is True.
* db_path = "" (default) → in-memory database; useful for tests.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

from bonbon_perception_ai.config.perception_config import MemoryConfig
from bonbon_perception_ai.understanding.intent_engine import UserIntent
from bonbon_perception_ai.understanding.scene_analyzer import SceneSnapshot

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS persons (
    id                  TEXT PRIMARY KEY,
    first_seen_at       REAL NOT NULL,
    last_seen_at        REAL NOT NULL,
    interaction_count   INTEGER DEFAULT 0,
    is_anonymous        INTEGER DEFAULT 1,
    face_id             TEXT    DEFAULT '',
    metadata_json       TEXT    DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS interactions (
    id              TEXT PRIMARY KEY,
    person_id       TEXT,
    timestamp       REAL NOT NULL,
    intent_class    TEXT DEFAULT '',
    intent_text     TEXT DEFAULT '',
    outcome         TEXT DEFAULT 'pending',
    slots_json      TEXT DEFAULT '{}',
    FOREIGN KEY (person_id) REFERENCES persons(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scene_episodes (
    id                  TEXT PRIMARY KEY,
    timestamp           REAL NOT NULL,
    dominant_activity   TEXT,
    person_count        INTEGER,
    object_classes_json TEXT,
    description         TEXT,
    confidence          REAL
);

CREATE TABLE IF NOT EXISTS known_objects (
    id              TEXT PRIMARY KEY,
    class_name      TEXT NOT NULL,
    first_seen_at   REAL,
    last_seen_at    REAL,
    location_x      REAL DEFAULT 0.0,
    location_y      REAL DEFAULT 0.0,
    confidence      REAL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_interactions_person  ON interactions(person_id);
CREATE INDEX IF NOT EXISTS idx_episodes_timestamp   ON scene_episodes(timestamp);
CREATE INDEX IF NOT EXISTS idx_known_objects_class  ON known_objects(class_name);
"""


class StructuredStore:
    """
    Thread-safe SQLite structured memory.

    All public methods may be called from any thread.
    """

    def __init__(self, cfg: MemoryConfig) -> None:
        self.cfg = cfg
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def open(self) -> None:
        db_path = self.cfg.db_path or ":memory:"
        # check_same_thread=False because we serialize with self._lock
        self._conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    # ── Person ────────────────────────────────────────────────────────────────

    def upsert_person(
        self,
        person_id: str,
        face_id: str = "",
        is_anonymous: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = time.time()
        f_id = face_id if self.cfg.privacy_store_faces else ""
        meta = json.dumps(metadata or {})
        with self._lock:
            self._conn.execute(  # type: ignore[union-attr]
                """
                INSERT INTO persons(id, first_seen_at, last_seen_at,
                                    interaction_count, is_anonymous, face_id, metadata_json)
                VALUES (?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    last_seen_at      = excluded.last_seen_at,
                    interaction_count = interaction_count + 1,
                    face_id           = excluded.face_id
                """,
                (person_id, now, now, int(is_anonymous), f_id, meta),
            )

    def get_person(self, person_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(  # type: ignore[union-attr]
                "SELECT * FROM persons WHERE id = ?", (person_id,)
            ).fetchone()
        if row is None:
            return None
        cols = [
            "id",
            "first_seen_at",
            "last_seen_at",
            "interaction_count",
            "is_anonymous",
            "face_id",
            "metadata_json",
        ]
        return dict(zip(cols, row))

    def forget_person(self, person_id: str) -> None:
        """Hard-delete a person and all their interactions (GDPR forget)."""
        with self._lock:
            self._conn.execute(  # type: ignore[union-attr]
                "DELETE FROM interactions WHERE person_id = ?", (person_id,)
            )
            self._conn.execute("DELETE FROM persons WHERE id = ?", (person_id,))

    def list_persons(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(  # type: ignore[union-attr]
                "SELECT id, first_seen_at, last_seen_at, interaction_count FROM persons"
            ).fetchall()
        return [
            {"id": r[0], "first_seen_at": r[1], "last_seen_at": r[2], "interaction_count": r[3]}
            for r in rows
        ]

    # ── Interactions ──────────────────────────────────────────────────────────

    def log_interaction(self, person_id: str, intent: UserIntent) -> None:
        with self._lock:
            self._conn.execute(  # type: ignore[union-attr]
                """
                INSERT INTO interactions(id, person_id, timestamp, intent_class,
                                         intent_text, slots_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    intent.intent_id,
                    person_id,
                    intent.timestamp,
                    intent.intent_class,
                    intent.raw_text[:512],
                    json.dumps(intent.slot_dict),
                ),
            )

    def get_recent_interactions(self, person_id: str, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(  # type: ignore[union-attr]
                """
                SELECT id, timestamp, intent_class, intent_text, outcome
                FROM interactions WHERE person_id = ?
                ORDER BY timestamp DESC LIMIT ?
                """,
                (person_id, limit),
            ).fetchall()
        return [
            {
                "id": r[0],
                "timestamp": r[1],
                "intent_class": r[2],
                "intent_text": r[3],
                "outcome": r[4],
            }
            for r in rows
        ]

    def update_interaction_outcome(self, interaction_id: str, outcome: str) -> None:
        with self._lock:
            self._conn.execute(  # type: ignore[union-attr]
                "UPDATE interactions SET outcome = ? WHERE id = ?",
                (outcome, interaction_id),
            )

    # ── Scene episodes ────────────────────────────────────────────────────────

    def log_scene(self, snap: SceneSnapshot) -> None:
        with self._lock:
            self._conn.execute(  # type: ignore[union-attr]
                """
                INSERT INTO scene_episodes(id, timestamp, dominant_activity,
                                           person_count, object_classes_json,
                                           description, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snap.scene_id,
                    snap.timestamp,
                    snap.dominant_activity,
                    len(snap.present_person_ids),
                    json.dumps(snap.present_object_classes),
                    snap.description[:512],
                    snap.confidence,
                ),
            )

    def purge_stale(self, max_age_sec: float) -> int:
        cutoff = time.time() - max_age_sec
        with self._lock:
            cursor = self._conn.execute(  # type: ignore[union-attr]
                "DELETE FROM scene_episodes WHERE timestamp < ?", (cutoff,)
            )
        return cursor.rowcount

    # ── Known objects ─────────────────────────────────────────────────────────

    def upsert_object(
        self,
        class_name: str,
        confidence: float,
        location_x: float = 0.0,
        location_y: float = 0.0,
    ) -> None:
        now = time.time()
        obj_id = f"obj_{class_name}_{hash(class_name) & 0xFFFF:04x}"
        with self._lock:
            self._conn.execute(  # type: ignore[union-attr]
                """
                INSERT INTO known_objects(id, class_name, first_seen_at, last_seen_at,
                                          location_x, location_y, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    last_seen_at = excluded.last_seen_at,
                    confidence   = excluded.confidence,
                    location_x   = excluded.location_x,
                    location_y   = excluded.location_y
                """,
                (obj_id, class_name, now, now, location_x, location_y, confidence),
            )

    def get_known_objects(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(  # type: ignore[union-attr]
                "SELECT class_name, last_seen_at, confidence FROM known_objects"
            ).fetchall()
        return [{"class_name": r[0], "last_seen_at": r[1], "confidence": r[2]} for r in rows]
