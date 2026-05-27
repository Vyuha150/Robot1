"""NavigationEventRepository — CRUD for the ``navigation_events`` table."""

from __future__ import annotations

import json
from typing import Any

from bonbon_data_stores.schema.models import NavigationEvent, NavigationOutcome, PrivacyLevel
from bonbon_data_stores.sqlite.connection import SQLiteConnection
from bonbon_data_stores.sqlite.repositories.base import BaseRepository


class NavigationEventRepository(BaseRepository):

    def __init__(self, conn: SQLiteConnection) -> None:
        super().__init__(conn)

    def save(self, event: NavigationEvent) -> str:
        self._assert_storable(event.privacy_level)

        sql = """
        INSERT OR IGNORE INTO navigation_events (
            event_id, timestamp, session_id, goal_id, map_id,
            start_x, start_y, goal_x, goal_y, outcome,
            distance_m, duration_sec, replanning_count, planner_used,
            privacy_level, retention_policy, metadata
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);
        """
        self._execute(
            sql,
            (
                event.event_id,
                event.timestamp,
                event.session_id,
                event.goal_id,
                event.map_id,
                event.start_x,
                event.start_y,
                event.goal_x,
                event.goal_y,
                event.outcome.value,
                event.distance_m,
                event.duration_sec,
                event.replanning_count,
                event.planner_used,
                event.privacy_level.value,
                event.retention_policy.value,
                json.dumps(event.metadata),
            ),
        )
        return event.event_id

    def get_by_id(self, event_id: str) -> NavigationEvent | None:
        row = self._fetchone("SELECT * FROM navigation_events WHERE event_id = ?;", (event_id,))
        return self._row_to_model(row) if row else None

    def get_by_outcome(self, outcome: NavigationOutcome) -> list[NavigationEvent]:
        rows = self._fetchall(
            "SELECT * FROM navigation_events WHERE outcome = ? ORDER BY timestamp DESC;",
            (outcome.value,),
        )
        return [self._row_to_model(r) for r in rows]

    def get_recent(self, limit: int = 20) -> list[NavigationEvent]:
        rows = self._fetchall(
            "SELECT * FROM navigation_events ORDER BY timestamp DESC LIMIT ?;",
            (limit,),
        )
        return [self._row_to_model(r) for r in rows]

    def delete(self, event_id: str) -> bool:
        return self._execute("DELETE FROM navigation_events WHERE event_id = ?;", (event_id,)) > 0

    def count(self) -> int:
        return self._count("navigation_events")

    @staticmethod
    def _row_to_model(row: dict[str, Any]) -> NavigationEvent:
        return NavigationEvent(
            event_id=row["event_id"],
            timestamp=row["timestamp"],
            session_id=row.get("session_id"),
            goal_id=row["goal_id"],
            map_id=row.get("map_id"),
            start_x=row["start_x"],
            start_y=row["start_y"],
            goal_x=row["goal_x"],
            goal_y=row["goal_y"],
            outcome=NavigationOutcome(row["outcome"]),
            distance_m=row["distance_m"],
            duration_sec=row["duration_sec"],
            replanning_count=row["replanning_count"],
            planner_used=row["planner_used"],
            privacy_level=PrivacyLevel(row["privacy_level"]),
            retention_policy=row["retention_policy"],
            metadata=json.loads(row.get("metadata") or "{}"),
        )
