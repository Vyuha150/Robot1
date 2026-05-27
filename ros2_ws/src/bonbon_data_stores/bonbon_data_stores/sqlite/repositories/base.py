"""BaseRepository — abstract base for all SQLite repository classes.

All data-access logic lives inside repositories.  No code outside a repository
should ever construct raw SQL or touch the connection directly.

Design rules
------------
* All queries are parameterised — never use string interpolation in SQL.
* Parameterised queries use positional ``?`` placeholders (sqlite3 style).
* The ``_conn`` attribute is a ``SQLiteConnection``; call ``_conn.get()`` for
  the raw ``sqlite3.Connection``.
* ``do_not_store`` events must be screened before calling ``save()``.  The
  base class provides ``_assert_storable()`` for this check.
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any

from bonbon_data_stores.schema.models import PrivacyLevel
from bonbon_data_stores.sqlite.connection import SQLiteConnection

logger = logging.getLogger(__name__)


class BaseRepository(ABC):
    """Abstract repository base class."""

    def __init__(self, conn: SQLiteConnection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def save(self, record: Any) -> str:
        """Persist *record* and return its primary-key string."""

    @abstractmethod
    def get_by_id(self, record_id: str) -> Any | None:
        """Return the record with *record_id*, or ``None`` if not found."""

    @abstractmethod
    def delete(self, record_id: str) -> bool:
        """Delete by primary key.  Return ``True`` if a row was removed."""

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _assert_storable(privacy_level: PrivacyLevel) -> None:
        """Raise ``ValueError`` if the privacy level forbids storage."""
        if privacy_level == PrivacyLevel.DO_NOT_STORE:
            raise ValueError(
                "do_not_store: this record must never be written to any storage backend"
            )

    @staticmethod
    def _now() -> float:
        return time.time()

    @staticmethod
    def _to_json(obj: Any) -> str:
        if obj is None:
            return "null"
        if isinstance(obj, str):
            return obj
        return json.dumps(obj, ensure_ascii=False)

    @staticmethod
    def _from_json(text: str | None) -> Any:
        if not text:
            return None
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text

    def _fetchone(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        """Execute *sql* and return the first row as a plain dict, or None."""
        row = self._conn.get().execute(sql, params).fetchone()
        if row is None:
            return None
        return dict(row)

    def _fetchall(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Execute *sql* and return all rows as plain dicts."""
        rows = self._conn.get().execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def _execute(self, sql: str, params: tuple = ()) -> int:
        """Execute a write statement; return rowcount."""
        cur = self._conn.get().execute(sql, params)
        self._conn.get().commit()
        return cur.rowcount

    def _count(self, table: str, where: str = "1=1", params: tuple = ()) -> int:
        row = (
            self._conn.get()
            .execute(f"SELECT COUNT(*) FROM {table} WHERE {where};", params)
            .fetchone()
        )
        return int(row[0]) if row else 0

    def purge_expired(self, table: str, ts_column: str, cutoff_ts: float) -> int:
        """Delete rows older than *cutoff_ts* from *table*.  Return deleted count."""
        sql = f"DELETE FROM {table} WHERE {ts_column} < ?;"
        cur = self._conn.get().execute(sql, (cutoff_ts,))
        self._conn.get().commit()
        deleted = cur.rowcount
        if deleted:
            logger.debug("Purged %d expired rows from %s", deleted, table)
        return deleted
