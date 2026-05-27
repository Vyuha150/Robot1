"""Thread-local SQLite connection manager with WAL mode.

Each thread gets its own connection object.  Connections are created lazily
on first use and reused for the lifetime of the thread.  The manager is safe
to share across threads.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


class SQLiteConnection:
    """Thread-local SQLite connection pool.

    Parameters
    ----------
    db_path:
        Absolute path to the SQLite file.  The parent directory is created
        automatically if it does not exist.
    wal_mode:
        Enable Write-Ahead Logging for better concurrent read performance.
    cache_size_kb:
        SQLite page-cache size in kilobytes (applied per connection).
    busy_timeout_ms:
        Milliseconds to wait when the database is locked before raising an
        ``OperationalError``.
    """

    def __init__(
        self,
        db_path: Path,
        wal_mode: bool = True,
        cache_size_kb: int = 16384,
        busy_timeout_ms: int = 5000,
    ) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._wal_mode = wal_mode
        self._cache_size_kb = cache_size_kb
        self._busy_timeout_ms = busy_timeout_ms
        self._local = threading.local()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path:
        return self._db_path

    def get(self) -> sqlite3.Connection:
        """Return the current thread's connection, creating it if necessary."""
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._open()
            self._local.conn = conn
        return conn

    def close(self) -> None:
        """Close the current thread's connection (if open)."""
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None

    def execute(
        self,
        sql: str,
        params: tuple = (),
    ) -> sqlite3.Cursor:
        """Execute *sql* on the current thread's connection."""
        return self.get().execute(sql, params)

    def executemany(
        self,
        sql: str,
        params_seq: list,
    ) -> sqlite3.Cursor:
        return self.get().executemany(sql, params_seq)

    def commit(self) -> None:
        self.get().commit()

    def rollback(self) -> None:
        self.get().rollback()

    def __enter__(self) -> SQLiteConnection:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _open(self) -> sqlite3.Connection:
        logger.debug(
            "Opening SQLite connection to %s (thread %s)", self._db_path, threading.get_ident()
        )
        conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,  # we manage thread-safety ourselves
            isolation_level=None,  # autocommit off; we manage transactions
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )
        conn.row_factory = sqlite3.Row
        self._apply_pragmas(conn)
        return conn

    def _apply_pragmas(self, conn: sqlite3.Connection) -> None:
        pragmas = [
            f"PRAGMA busy_timeout = {self._busy_timeout_ms};",
            f"PRAGMA cache_size  = -{self._cache_size_kb};",  # negative = KB
            "PRAGMA foreign_keys = ON;",
            "PRAGMA temp_store   = MEMORY;",
        ]
        if self._wal_mode:
            pragmas.insert(0, "PRAGMA journal_mode = WAL;")
            pragmas.append("PRAGMA synchronous = NORMAL;")
        else:
            pragmas.append("PRAGMA synchronous = FULL;")

        for pragma in pragmas:
            try:
                conn.execute(pragma)
            except sqlite3.OperationalError as exc:
                logger.warning("Failed to apply pragma %r: %s", pragma, exc)
