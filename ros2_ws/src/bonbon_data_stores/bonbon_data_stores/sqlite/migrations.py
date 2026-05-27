"""Schema migration runner for bonbon_data_stores.

Migrations are stored in ``schema.sql_schema.MIGRATIONS`` as a list of
``(version: int, description: str, sql: str)`` tuples.  The runner applies
any migration whose version number is higher than the current database version.

This is a forward-only, append-only migration system.  There is no rollback.
"""

from __future__ import annotations

import logging

from bonbon_data_stores.schema.sql_schema import MIGRATIONS
from bonbon_data_stores.sqlite.connection import SQLiteConnection

logger = logging.getLogger(__name__)

_CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    description TEXT    NOT NULL,
    applied_at  REAL    NOT NULL DEFAULT (unixepoch('now', 'subsec'))
);
"""


class SchemaMigrator:
    """Apply pending migrations to a SQLite database.

    Usage::

        migrator = SchemaMigrator(conn)
        migrator.migrate()          # idempotent; only applies missing versions
        print(migrator.current_version())
    """

    def __init__(self, conn: SQLiteConnection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def migrate(self) -> int:
        """Apply all pending migrations.

        Returns the new schema version after migration.
        """
        db = self._conn.get()

        # Ensure migrations table exists before querying it
        db.execute(_CREATE_MIGRATIONS_TABLE)
        db.commit()

        current = self._get_version(db)
        pending = [(v, d, s) for v, d, s in MIGRATIONS if v > current]

        if not pending:
            logger.debug("Schema is up to date at version %d", current)
            return current

        for version, description, sql in sorted(pending):
            logger.info("Applying migration v%d: %s", version, description)
            try:
                db.executescript(sql)
                db.execute(
                    "INSERT OR REPLACE INTO schema_migrations (version, description) VALUES (?, ?);",
                    (version, description),
                )
                db.commit()
                logger.info("Migration v%d applied successfully", version)
            except Exception as exc:
                db.rollback()
                logger.error("Migration v%d failed: %s", version, exc)
                raise

        return self._get_version(db)

    def current_version(self) -> int:
        """Return the highest applied migration version (0 if none)."""
        db = self._conn.get()
        db.execute(_CREATE_MIGRATIONS_TABLE)
        db.commit()
        return self._get_version(db)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_version(db) -> int:
        try:
            row = db.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations;").fetchone()
            return int(row[0]) if row else 0
        except Exception:
            return 0
