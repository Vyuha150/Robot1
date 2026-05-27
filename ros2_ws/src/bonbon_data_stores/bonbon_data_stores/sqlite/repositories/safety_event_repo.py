"""SafetyEventRepository — CRUD for the ``safety_events`` table."""

from __future__ import annotations

import json
from typing import Any

from bonbon_data_stores.schema.models import PrivacyLevel, SafetyEvent, SafetyEventType
from bonbon_data_stores.sqlite.connection import SQLiteConnection
from bonbon_data_stores.sqlite.repositories.base import BaseRepository


class SafetyEventRepository(BaseRepository):

    def __init__(self, conn: SQLiteConnection) -> None:
        super().__init__(conn)

    def save(self, event: SafetyEvent) -> str:
        self._assert_storable(event.privacy_level)

        sql = """
        INSERT OR IGNORE INTO safety_events (
            event_id, timestamp, session_id, event_type, severity,
            source_node, description, position_x, position_y,
            obstacle_distance_m, resolved, resolved_at,
            privacy_level, retention_policy, metadata
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);
        """
        self._execute(
            sql,
            (
                event.event_id,
                event.timestamp,
                event.session_id,
                event.event_type.value,
                event.severity,
                event.source_node,
                event.description,
                event.position_x,
                event.position_y,
                event.obstacle_distance_m,
                int(event.resolved),
                event.resolved_at,
                event.privacy_level.value,
                event.retention_policy.value,
                json.dumps(event.metadata),
            ),
        )
        return event.event_id

    def get_by_id(self, event_id: str) -> SafetyEvent | None:
        row = self._fetchone("SELECT * FROM safety_events WHERE event_id = ?;", (event_id,))
        return self._row_to_model(row) if row else None

    def get_unresolved(self) -> list[SafetyEvent]:
        rows = self._fetchall(
            "SELECT * FROM safety_events WHERE resolved = 0 ORDER BY timestamp DESC;"
        )
        return [self._row_to_model(r) for r in rows]

    def get_by_type(self, event_type: SafetyEventType) -> list[SafetyEvent]:
        rows = self._fetchall(
            "SELECT * FROM safety_events WHERE event_type = ? ORDER BY timestamp DESC;",
            (event_type.value,),
        )
        return [self._row_to_model(r) for r in rows]

    def mark_resolved(self, event_id: str) -> bool:
        count = self._execute(
            "UPDATE safety_events SET resolved = 1, resolved_at = ? WHERE event_id = ?;",
            (self._now(), event_id),
        )
        return count > 0

    def delete(self, event_id: str) -> bool:
        return self._execute("DELETE FROM safety_events WHERE event_id = ?;", (event_id,)) > 0

    def count(self) -> int:
        return self._count("safety_events")

    @staticmethod
    def _row_to_model(row: dict[str, Any]) -> SafetyEvent:
        return SafetyEvent(
            event_id=row["event_id"],
            timestamp=row["timestamp"],
            session_id=row.get("session_id"),
            event_type=SafetyEventType(row["event_type"]),
            severity=row["severity"],
            source_node=row["source_node"],
            description=row["description"],
            position_x=row["position_x"],
            position_y=row["position_y"],
            obstacle_distance_m=row.get("obstacle_distance_m"),
            resolved=bool(row["resolved"]),
            resolved_at=row.get("resolved_at"),
            privacy_level=PrivacyLevel(row["privacy_level"]),
            retention_policy=row["retention_policy"],
            metadata=json.loads(row.get("metadata") or "{}"),
        )
