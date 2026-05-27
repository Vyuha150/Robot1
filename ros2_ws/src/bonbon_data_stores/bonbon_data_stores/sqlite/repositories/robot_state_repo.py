"""RobotStateRepository — CRUD for the ``robot_states`` table."""

from __future__ import annotations

import json
from typing import Any

from bonbon_data_stores.schema.models import PrivacyLevel, RobotState
from bonbon_data_stores.sqlite.connection import SQLiteConnection
from bonbon_data_stores.sqlite.repositories.base import BaseRepository


class RobotStateRepository(BaseRepository):

    def __init__(self, conn: SQLiteConnection) -> None:
        super().__init__(conn)

    def save(self, state: RobotState) -> str:
        self._assert_storable(state.privacy_level)

        sql = """
        INSERT OR IGNORE INTO robot_states (
            event_id, timestamp, session_id, mode,
            battery_level, position_x, position_y, position_z, orientation_yaw,
            map_id, active_task, cpu_load, memory_used_mb,
            active_nodes, error_flags, privacy_level, retention_policy, metadata
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);
        """
        self._execute(
            sql,
            (
                state.event_id,
                state.timestamp,
                state.session_id,
                state.mode.value,
                state.battery_level,
                state.position_x,
                state.position_y,
                state.position_z,
                state.orientation_yaw,
                state.map_id,
                state.active_task,
                state.cpu_load,
                state.memory_used_mb,
                json.dumps(state.active_nodes),
                json.dumps(state.error_flags),
                state.privacy_level.value,
                state.retention_policy.value,
                json.dumps(state.metadata),
            ),
        )
        return state.event_id

    def get_by_id(self, event_id: str) -> RobotState | None:
        row = self._fetchone("SELECT * FROM robot_states WHERE event_id = ?;", (event_id,))
        return self._row_to_model(row) if row else None

    def get_latest(self) -> RobotState | None:
        row = self._fetchone("SELECT * FROM robot_states ORDER BY timestamp DESC LIMIT 1;")
        return self._row_to_model(row) if row else None

    def get_range(self, start_ts: float, end_ts: float) -> list[RobotState]:
        rows = self._fetchall(
            "SELECT * FROM robot_states WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp ASC;",
            (start_ts, end_ts),
        )
        return [self._row_to_model(r) for r in rows]

    def delete(self, event_id: str) -> bool:
        return self._execute("DELETE FROM robot_states WHERE event_id = ?;", (event_id,)) > 0

    def count(self) -> int:
        return self._count("robot_states")

    @staticmethod
    def _row_to_model(row: dict[str, Any]) -> RobotState:
        return RobotState(
            event_id=row["event_id"],
            timestamp=row["timestamp"],
            session_id=row.get("session_id"),
            mode=row["mode"],
            battery_level=row["battery_level"],
            position_x=row["position_x"],
            position_y=row["position_y"],
            position_z=row["position_z"],
            orientation_yaw=row["orientation_yaw"],
            map_id=row.get("map_id"),
            active_task=row.get("active_task"),
            cpu_load=row["cpu_load"],
            memory_used_mb=row["memory_used_mb"],
            active_nodes=json.loads(row.get("active_nodes") or "[]"),
            error_flags=json.loads(row.get("error_flags") or "[]"),
            privacy_level=PrivacyLevel(row["privacy_level"]),
            retention_policy=row["retention_policy"],
            metadata=json.loads(row.get("metadata") or "{}"),
        )
