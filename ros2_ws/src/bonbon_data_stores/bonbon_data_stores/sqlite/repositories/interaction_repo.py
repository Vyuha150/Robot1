"""InteractionHistoryRepository — CRUD for the ``interactions`` table."""

from __future__ import annotations

import json
from typing import Any

from bonbon_data_stores.schema.models import InteractionEvent, PrivacyLevel
from bonbon_data_stores.sqlite.connection import SQLiteConnection
from bonbon_data_stores.sqlite.repositories.base import BaseRepository


class InteractionHistoryRepository(BaseRepository):

    def __init__(self, conn: SQLiteConnection) -> None:
        super().__init__(conn)

    # ------------------------------------------------------------------

    def save(self, event: InteractionEvent) -> str:
        self._assert_storable(event.privacy_level)

        sql = """
        INSERT OR IGNORE INTO interactions (
            event_id, timestamp, session_id, user_id,
            input_modality, input_text, intent, intent_confidence,
            response_text, response_modality, tts_latency_ms,
            satisfaction_score, language, audio_ref,
            privacy_level, retention_policy, metadata
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);
        """
        self._execute(
            sql,
            (
                event.event_id,
                event.timestamp,
                event.session_id,
                event.user_id,
                event.input_modality,
                event.input_text,
                event.intent,
                event.intent_confidence,
                event.response_text,
                event.response_modality,
                event.tts_latency_ms,
                event.satisfaction_score,
                event.language,
                event.audio_ref,
                event.privacy_level.value,
                event.retention_policy.value,
                json.dumps(event.metadata),
            ),
        )
        return event.event_id

    def get_by_id(self, event_id: str) -> InteractionEvent | None:
        row = self._fetchone("SELECT * FROM interactions WHERE event_id = ?;", (event_id,))
        return self._row_to_model(row) if row else None

    def get_by_user(self, user_id: str, limit: int = 50, offset: int = 0) -> list[InteractionEvent]:
        rows = self._fetchall(
            "SELECT * FROM interactions WHERE user_id = ? ORDER BY timestamp DESC LIMIT ? OFFSET ?;",
            (user_id, limit, offset),
        )
        return [self._row_to_model(r) for r in rows]

    def get_by_session(self, session_id: str) -> list[InteractionEvent]:
        rows = self._fetchall(
            "SELECT * FROM interactions WHERE session_id = ? ORDER BY timestamp ASC;",
            (session_id,),
        )
        return [self._row_to_model(r) for r in rows]

    def get_recent(self, limit: int = 20) -> list[InteractionEvent]:
        rows = self._fetchall(
            "SELECT * FROM interactions ORDER BY timestamp DESC LIMIT ?;",
            (limit,),
        )
        return [self._row_to_model(r) for r in rows]

    def delete(self, event_id: str) -> bool:
        return self._execute("DELETE FROM interactions WHERE event_id = ?;", (event_id,)) > 0

    def count(self) -> int:
        return self._count("interactions")

    def purge_by_retention(self, policy: str, cutoff_ts: float) -> int:
        sql = "DELETE FROM interactions WHERE retention_policy = ? AND timestamp < ?;"
        cur = self._conn.get().execute(sql, (policy, cutoff_ts))
        self._conn.get().commit()
        return cur.rowcount

    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_model(row: dict[str, Any]) -> InteractionEvent:
        return InteractionEvent(
            event_id=row["event_id"],
            timestamp=row["timestamp"],
            session_id=row.get("session_id"),
            user_id=row.get("user_id"),
            input_modality=row["input_modality"],
            input_text=row.get("input_text"),
            intent=row.get("intent"),
            intent_confidence=row["intent_confidence"],
            response_text=row.get("response_text"),
            response_modality=row["response_modality"],
            tts_latency_ms=row["tts_latency_ms"],
            satisfaction_score=row.get("satisfaction_score"),
            language=row["language"],
            audio_ref=row.get("audio_ref"),
            privacy_level=PrivacyLevel(row["privacy_level"]),
            retention_policy=row["retention_policy"],
            metadata=json.loads(row.get("metadata") or "{}"),
        )
