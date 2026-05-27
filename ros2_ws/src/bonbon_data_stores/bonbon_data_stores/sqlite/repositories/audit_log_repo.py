"""AuditLogRepository — insert-only access to the ``audit_log`` table.

The audit log is append-only by design.  There is no ``update()`` method.
``delete()`` is provided only for administrative purge operations (e.g.
retention sweep) and must never be called for regular business logic.
"""

from __future__ import annotations

from typing import Any

from bonbon_data_stores.schema.models import AuditLogEntry, PrivacyLevel
from bonbon_data_stores.sqlite.connection import SQLiteConnection
from bonbon_data_stores.sqlite.repositories.base import BaseRepository


class AuditLogRepository(BaseRepository):

    def __init__(self, conn: SQLiteConnection) -> None:
        super().__init__(conn)

    def save(self, entry: AuditLogEntry) -> str:
        """Append an audit log entry.  Returns log_id."""
        sql = """
        INSERT INTO audit_log (
            log_id, timestamp, actor, action,
            target_type, target_id, outcome, detail,
            privacy_level, retention_policy
        ) VALUES (?,?,?,?,?,?,?,?,?,?);
        """
        self._execute(
            sql,
            (
                entry.log_id,
                entry.timestamp,
                entry.actor,
                entry.action,
                entry.target_type,
                entry.target_id,
                entry.outcome,
                entry.detail,
                entry.privacy_level.value,
                entry.retention_policy.value,
            ),
        )
        return entry.log_id

    def get_by_id(self, log_id: str) -> AuditLogEntry | None:
        row = self._fetchone("SELECT * FROM audit_log WHERE log_id = ?;", (log_id,))
        return self._row_to_model(row) if row else None

    def get_by_actor(self, actor: str, limit: int = 100) -> list[AuditLogEntry]:
        rows = self._fetchall(
            "SELECT * FROM audit_log WHERE actor = ? ORDER BY timestamp DESC LIMIT ?;",
            (actor, limit),
        )
        return [self._row_to_model(r) for r in rows]

    def get_recent(self, limit: int = 50) -> list[AuditLogEntry]:
        rows = self._fetchall(
            "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?;",
            (limit,),
        )
        return [self._row_to_model(r) for r in rows]

    def delete(self, log_id: str) -> bool:
        """Admin-only: delete a single log entry (e.g. retention purge)."""
        return self._execute("DELETE FROM audit_log WHERE log_id = ?;", (log_id,)) > 0

    def count(self) -> int:
        return self._count("audit_log")

    @staticmethod
    def _row_to_model(row: dict[str, Any]) -> AuditLogEntry:
        return AuditLogEntry(
            log_id=row["log_id"],
            timestamp=row["timestamp"],
            actor=row["actor"],
            action=row["action"],
            target_type=row["target_type"],
            target_id=row["target_id"],
            outcome=row["outcome"],
            detail=row["detail"],
            privacy_level=PrivacyLevel(row["privacy_level"]),
            retention_policy=row["retention_policy"],
        )
