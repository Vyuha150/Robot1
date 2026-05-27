"""
bonbon_safety.core.incident_logger
=====================================
Append-only safety incident log backed by SQLite.

Every state transition and hazard event is recorded here for operator review,
regulatory compliance, and post-incident analysis.  The log is APPEND-ONLY —
no rows are ever updated or deleted programmatically (retention is handled by
a separate scheduled job that archives old rows).

Schema
------
CREATE TABLE incidents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL    NOT NULL,      -- Unix epoch seconds (float)
    iso_time    TEXT    NOT NULL,      -- ISO-8601 for human readability
    from_state  TEXT    NOT NULL,
    to_state    TEXT    NOT NULL,
    trigger     TEXT    NOT NULL,
    reason      TEXT    NOT NULL,
    -- Sensor context
    nearest_obstacle_m  REAL,
    nearest_human_m     REAL,
    battery_percent     REAL,
    cpu_temp_c          REAL,
    -- Flags
    operator_notified   INTEGER,       -- boolean
    auto_recovery       INTEGER,       -- boolean
    -- Extra JSON context
    extra_json          TEXT
);
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bonbon_safety.core.safety_state_machine import StateTransition

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS incidents (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           REAL    NOT NULL,
    iso_time            TEXT    NOT NULL,
    from_state          TEXT    NOT NULL,
    to_state            TEXT    NOT NULL,
    trigger             TEXT    NOT NULL,
    reason              TEXT    NOT NULL,
    nearest_obstacle_m  REAL,
    nearest_human_m     REAL,
    battery_percent     REAL,
    cpu_temp_c          REAL,
    operator_notified   INTEGER NOT NULL DEFAULT 0,
    auto_recovery       INTEGER NOT NULL DEFAULT 0,
    extra_json          TEXT
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_incidents_timestamp ON incidents (timestamp);
"""

_INSERT = """
INSERT INTO incidents (
    timestamp, iso_time, from_state, to_state, trigger, reason,
    nearest_obstacle_m, nearest_human_m, battery_percent, cpu_temp_c,
    operator_notified, auto_recovery, extra_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""


class IncidentLogger:
    """
    Thread-safe append-only safety incident logger.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.  Created if it does not exist.
        Use `:memory:` for testing.
    robot_id:
        Identifier embedded in every log row for fleet-wide queries.
    """

    def __init__(self, db_path: Path | str, robot_id: str = "bonbon-01") -> None:
        self._db_path = str(db_path)
        self._robot_id = robot_id
        self._conn: sqlite3.Connection | None = None
        self._connect()
        logger.info("IncidentLogger initialised: %s", self._db_path)

    def _connect(self) -> None:
        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,  # supervisor uses a single thread
            timeout=5.0,
        )
        self._conn.execute("PRAGMA journal_mode=WAL;")  # writes don't block reads
        self._conn.execute(_CREATE_TABLE)
        self._conn.execute(_CREATE_INDEX)
        self._conn.commit()

    def log_transition(
        self,
        transition: StateTransition,
        *,
        trigger: str = "state_machine",
        operator_notified: bool = False,
        auto_recovery: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> int:
        """
        Write a state transition to the incident log.

        Returns the row id of the inserted record.
        """
        now = time.time()
        iso = datetime.fromtimestamp(now, tz=UTC).isoformat()

        snap = transition.snapshot
        extra_dict: dict[str, Any] = extra or {}
        extra_dict["robot_id"] = self._robot_id

        try:
            assert self._conn is not None
            cursor = self._conn.execute(
                _INSERT,
                (
                    now,
                    iso,
                    transition.from_state.name,
                    transition.to_state.name,
                    trigger,
                    transition.reason,
                    snap.nearest_obstacle_m if snap else None,
                    snap.nearest_human_m if snap else None,
                    snap.battery_percent if snap else None,
                    snap.cpu_temp_c if snap else None,
                    int(operator_notified),
                    int(auto_recovery),
                    json.dumps(extra_dict),
                ),
            )
            self._conn.commit()
            row_id: int = cursor.lastrowid or 0
            logger.debug(
                "Incident logged: id=%d  %s → %s  '%s'",
                row_id,
                transition.from_state.name,
                transition.to_state.name,
                transition.reason,
            )
            return row_id

        except sqlite3.Error:
            logger.exception("Failed to write incident log — attempting reconnect")
            try:
                self._connect()
            except Exception:
                logger.exception("Reconnect failed — incident NOT logged")
            return -1

    def recent_incidents(self, limit: int = 50) -> list[dict]:
        """Return the most recent incidents as a list of dicts (for dashboard)."""
        assert self._conn is not None
        cursor = self._conn.execute(
            "SELECT * FROM incidents ORDER BY timestamp DESC LIMIT ?", (limit,)
        )
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
