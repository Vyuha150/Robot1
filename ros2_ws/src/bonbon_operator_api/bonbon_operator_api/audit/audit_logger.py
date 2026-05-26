"""AuditLogger — immutable append-only audit trail in SQLite.

Every command, auth event, and config change is recorded here.
Failures in audit logging NEVER block the primary operation —
they are silently captured and logged to stderr.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    event_id     TEXT PRIMARY KEY,
    timestamp    REAL NOT NULL,
    actor_id     TEXT NOT NULL,
    actor_name   TEXT NOT NULL,
    actor_role   TEXT NOT NULL,
    action       TEXT NOT NULL,
    target       TEXT NOT NULL DEFAULT '',
    request_data TEXT NOT NULL DEFAULT '{}',
    outcome      TEXT NOT NULL DEFAULT 'success',
    detail       TEXT NOT NULL DEFAULT '',
    ip_address   TEXT NOT NULL DEFAULT '',
    duration_ms  REAL
);
CREATE INDEX IF NOT EXISTS idx_audit_ts     ON audit_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_actor  ON audit_events(actor_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_events(action);
"""


class AuditLogger:
    """Append-only audit log stored in SQLite.

    Parameters
    ----------
    db_path:
        Path to the SQLite audit database.
    max_events:
        Soft cap — oldest events are pruned when exceeded.
    """

    def __init__(self, db_path: Path, max_events: int = 100_000) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._max_events = max_events
        self._init_db()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log(
        self,
        actor_id: str,
        actor_name: str,
        actor_role: str,
        action: str,
        target: str = "",
        request_data: Optional[Dict[str, Any]] = None,
        outcome: str = "success",
        detail: str = "",
        ip_address: str = "",
        duration_ms: Optional[float] = None,
    ) -> str:
        """Append one audit entry.  Returns event_id (never raises)."""
        event_id = str(uuid.uuid4())
        try:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO audit_events
                        (event_id, timestamp, actor_id, actor_name, actor_role,
                         action, target, request_data, outcome, detail,
                         ip_address, duration_ms)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?);
                    """,
                    (
                        event_id,
                        time.time(),
                        actor_id,
                        actor_name,
                        actor_role,
                        action,
                        target,
                        json.dumps(request_data or {}),
                        outcome,
                        detail,
                        ip_address,
                        duration_ms,
                    ),
                )
                conn.commit()
        except Exception as exc:
            # Audit failure MUST NOT break the primary operation
            logger.error("AuditLogger write failed: %s", exc)
        return event_id

    def query(
        self,
        actor_id: Optional[str] = None,
        action: Optional[str] = None,
        since_ts: Optional[float] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Query audit events with optional filters."""
        conditions = []
        params: list = []
        if actor_id:
            conditions.append("actor_id = ?")
            params.append(actor_id)
        if action:
            conditions.append("action LIKE ?")
            params.append(f"%{action}%")
        if since_ts:
            conditions.append("timestamp >= ?")
            params.append(since_ts)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM audit_events {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?;"
        params += [limit, offset]
        try:
            with self._conn() as conn:
                rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("AuditLogger query failed: %s", exc)
            return []

    def count(self) -> int:
        try:
            with self._conn() as conn:
                row = conn.execute("SELECT COUNT(*) FROM audit_events;").fetchone()
            return int(row[0])
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def _init_db(self) -> None:
        try:
            with self._conn() as conn:
                conn.executescript(_SCHEMA)
                conn.commit()
        except Exception as exc:
            logger.error("AuditLogger init failed: %s", exc)

    def _prune(self) -> None:
        """Delete oldest rows when max_events is exceeded."""
        try:
            count = self.count()
            if count > self._max_events:
                excess = count - self._max_events
                with self._conn() as conn:
                    conn.execute(
                        "DELETE FROM audit_events WHERE event_id IN "
                        "(SELECT event_id FROM audit_events ORDER BY timestamp ASC LIMIT ?);",
                        (excess,),
                    )
                    conn.commit()
        except Exception as exc:
            logger.error("AuditLogger prune failed: %s", exc)
