"""Schema for bonbon_data_feedback's own database.

A separate database file from bonbon_data_stores' operational data
(interactions, safety events, navigation events) — not a duplicate
connection-management layer (that's reused directly, see
bonbon_data_feedback.core.feedback_store), but a separate FILE because this
data has materially different retention/privacy rules (see
PrivacySafeDataPolicy) than routine operational logging.

Migration format matches bonbon_data_stores.schema.sql_schema.MIGRATIONS
exactly — (version: int, description: str, sql: str) — so the SAME
SchemaMigrator class applies them unmodified.
"""

from __future__ import annotations

MIGRATIONS: list[tuple[int, str, str]] = [
    (
        1,
        "initial failure_cases / dataset_versions / model_evaluations schema",
        """
        CREATE TABLE IF NOT EXISTS failure_cases (
            case_id           TEXT PRIMARY KEY,
            category          TEXT NOT NULL,
            signal_name       TEXT NOT NULL,
            expected_label    TEXT NOT NULL DEFAULT '',
            actual_label      TEXT NOT NULL,
            confidence        REAL NOT NULL,
            person_track_id   TEXT NOT NULL DEFAULT '',
            context_json      TEXT NOT NULL DEFAULT '{}',
            is_hard_negative  INTEGER NOT NULL DEFAULT 0,
            has_raw_snapshot  INTEGER NOT NULL DEFAULT 0,
            raw_snapshot_path TEXT NOT NULL DEFAULT '',
            created_at        REAL NOT NULL,
            reviewed          INTEGER NOT NULL DEFAULT 0,
            review_label      TEXT NOT NULL DEFAULT '',
            reviewed_at       REAL
        );
        CREATE INDEX IF NOT EXISTS idx_failure_cases_category ON failure_cases(category);
        CREATE INDEX IF NOT EXISTS idx_failure_cases_created_at ON failure_cases(created_at);
        CREATE INDEX IF NOT EXISTS idx_failure_cases_hard_negative ON failure_cases(is_hard_negative);
        CREATE INDEX IF NOT EXISTS idx_failure_cases_reviewed ON failure_cases(reviewed);

        CREATE TABLE IF NOT EXISTS dataset_versions (
            version_id   TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            category     TEXT NOT NULL,
            case_count   INTEGER NOT NULL,
            created_at   REAL NOT NULL,
            export_path  TEXT NOT NULL,
            notes        TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS model_evaluations (
            eval_id        TEXT PRIMARY KEY,
            model_name     TEXT NOT NULL,
            model_version  TEXT NOT NULL,
            category       TEXT NOT NULL,
            sample_count   INTEGER NOT NULL,
            accuracy       REAL,
            notes          TEXT NOT NULL DEFAULT '',
            created_at     REAL NOT NULL
        );
        """,
    ),
    (
        2,
        "add site_id + language_code to failure_cases for per-site/per-language analysis",
        """
        ALTER TABLE failure_cases ADD COLUMN site_id TEXT NOT NULL DEFAULT '';
        ALTER TABLE failure_cases ADD COLUMN language_code TEXT NOT NULL DEFAULT '';
        CREATE INDEX IF NOT EXISTS idx_failure_cases_site_id ON failure_cases(site_id);
        """,
    ),
]
