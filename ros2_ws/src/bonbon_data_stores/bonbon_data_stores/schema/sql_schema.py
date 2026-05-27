"""SQL DDL for all 14 tables in the bonbon_data_stores SQLite database.

Tables
------
1.  schema_migrations        — migration version tracking
2.  users                    — known user profiles
3.  user_preferences         — per-user key/value preferences
4.  interactions             — conversation / interaction history
5.  robot_states             — periodic robot state snapshots
6.  safety_events            — safety-critical occurrences
7.  navigation_events        — goal + outcome records
8.  audit_log                — immutable append-only audit trail
9.  map_metadata             — stored map records
10. environment_zones        — named zones within maps
11. ai_context               — LLM context fragments
12. vector_index_meta        — FAISS index catalogue
13. chroma_collection_meta   — ChromaDB collection catalogue
14. sessions                 — active / historical sessions
"""

from __future__ import annotations

# Each entry is (version: int, description: str, sql: str)
MIGRATIONS: list[tuple[int, str, str]] = [
    # ------------------------------------------------------------------
    # V1 — initial schema
    # ------------------------------------------------------------------
    (
        1,
        "initial schema",
        """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    description TEXT    NOT NULL,
    applied_at  REAL    NOT NULL DEFAULT (unixepoch('now', 'subsec'))
);

CREATE TABLE IF NOT EXISTS users (
    user_id                      TEXT PRIMARY KEY,
    display_name                 TEXT    NOT NULL,
    language                     TEXT    NOT NULL DEFAULT 'en',
    preferred_interaction_style  TEXT    NOT NULL DEFAULT 'friendly',
    accessibility_needs          TEXT    NOT NULL DEFAULT '[]',   -- JSON array
    face_encoding_ref            TEXT,
    voice_profile_ref            TEXT,
    created_at                   REAL    NOT NULL,
    last_seen_at                 REAL    NOT NULL,
    interaction_count            INTEGER NOT NULL DEFAULT 0,
    privacy_level                TEXT    NOT NULL DEFAULT 'sensitive',
    retention_policy             TEXT    NOT NULL DEFAULT 'permanent_until_deleted',
    is_anonymous                 INTEGER NOT NULL DEFAULT 0        -- boolean
);

CREATE TABLE IF NOT EXISTS user_preferences (
    pref_id     TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    category    TEXT NOT NULL DEFAULT 'general',
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    updated_at  REAL NOT NULL DEFAULT (unixepoch('now', 'subsec')),
    UNIQUE (user_id, category, key)
);

CREATE TABLE IF NOT EXISTS interactions (
    event_id            TEXT PRIMARY KEY,
    timestamp           REAL    NOT NULL,
    session_id          TEXT,
    user_id             TEXT    REFERENCES users(user_id) ON DELETE SET NULL,
    input_modality      TEXT    NOT NULL DEFAULT 'speech',
    input_text          TEXT,
    intent              TEXT,
    intent_confidence   REAL    NOT NULL DEFAULT 0.0,
    response_text       TEXT,
    response_modality   TEXT    NOT NULL DEFAULT 'speech',
    tts_latency_ms      REAL    NOT NULL DEFAULT 0.0,
    satisfaction_score  REAL,
    language            TEXT    NOT NULL DEFAULT 'en',
    audio_ref           TEXT,
    privacy_level       TEXT    NOT NULL DEFAULT 'internal',
    retention_policy    TEXT    NOT NULL DEFAULT '30_days',
    metadata            TEXT    NOT NULL DEFAULT '{}'         -- JSON
);

CREATE TABLE IF NOT EXISTS robot_states (
    event_id         TEXT PRIMARY KEY,
    timestamp        REAL    NOT NULL,
    session_id       TEXT,
    mode             TEXT    NOT NULL DEFAULT 'idle',
    battery_level    REAL    NOT NULL DEFAULT 1.0,
    position_x       REAL    NOT NULL DEFAULT 0.0,
    position_y       REAL    NOT NULL DEFAULT 0.0,
    position_z       REAL    NOT NULL DEFAULT 0.0,
    orientation_yaw  REAL    NOT NULL DEFAULT 0.0,
    map_id           TEXT,
    active_task      TEXT,
    cpu_load         REAL    NOT NULL DEFAULT 0.0,
    memory_used_mb   REAL    NOT NULL DEFAULT 0.0,
    active_nodes     TEXT    NOT NULL DEFAULT '[]',   -- JSON
    error_flags      TEXT    NOT NULL DEFAULT '[]',   -- JSON
    privacy_level    TEXT    NOT NULL DEFAULT 'internal',
    retention_policy TEXT    NOT NULL DEFAULT '7_days',
    metadata         TEXT    NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS safety_events (
    event_id            TEXT PRIMARY KEY,
    timestamp           REAL    NOT NULL,
    session_id          TEXT,
    event_type          TEXT    NOT NULL,
    severity            INTEGER NOT NULL DEFAULT 1,
    source_node         TEXT    NOT NULL DEFAULT '',
    description         TEXT    NOT NULL DEFAULT '',
    position_x          REAL    NOT NULL DEFAULT 0.0,
    position_y          REAL    NOT NULL DEFAULT 0.0,
    obstacle_distance_m REAL,
    resolved            INTEGER NOT NULL DEFAULT 0,
    resolved_at         REAL,
    privacy_level       TEXT    NOT NULL DEFAULT 'internal',
    retention_policy    TEXT    NOT NULL DEFAULT '1_year',
    metadata            TEXT    NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS navigation_events (
    event_id          TEXT PRIMARY KEY,
    timestamp         REAL    NOT NULL,
    session_id        TEXT,
    goal_id           TEXT    NOT NULL,
    map_id            TEXT,
    start_x           REAL    NOT NULL DEFAULT 0.0,
    start_y           REAL    NOT NULL DEFAULT 0.0,
    goal_x            REAL    NOT NULL DEFAULT 0.0,
    goal_y            REAL    NOT NULL DEFAULT 0.0,
    outcome           TEXT    NOT NULL DEFAULT 'success',
    distance_m        REAL    NOT NULL DEFAULT 0.0,
    duration_sec      REAL    NOT NULL DEFAULT 0.0,
    replanning_count  INTEGER NOT NULL DEFAULT 0,
    planner_used      TEXT    NOT NULL DEFAULT '',
    privacy_level     TEXT    NOT NULL DEFAULT 'internal',
    retention_policy  TEXT    NOT NULL DEFAULT '30_days',
    metadata          TEXT    NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS audit_log (
    log_id           TEXT PRIMARY KEY,
    timestamp        REAL NOT NULL,
    actor            TEXT NOT NULL,
    action           TEXT NOT NULL,
    target_type      TEXT NOT NULL DEFAULT '',
    target_id        TEXT NOT NULL DEFAULT '',
    outcome          TEXT NOT NULL DEFAULT 'success',
    detail           TEXT NOT NULL DEFAULT '',
    privacy_level    TEXT NOT NULL DEFAULT 'internal',
    retention_policy TEXT NOT NULL DEFAULT '1_year'
    -- audit_log is intentionally insert-only; no metadata column
);

CREATE TABLE IF NOT EXISTS map_metadata (
    map_id          TEXT PRIMARY KEY,
    map_name        TEXT NOT NULL,
    file_path       TEXT NOT NULL DEFAULT '',
    pgm_path        TEXT NOT NULL DEFAULT '',
    yaml_path       TEXT NOT NULL DEFAULT '',
    resolution_m    REAL NOT NULL DEFAULT 0.05,
    origin_x        REAL NOT NULL DEFAULT 0.0,
    origin_y        REAL NOT NULL DEFAULT 0.0,
    width_cells     INTEGER NOT NULL DEFAULT 0,
    height_cells    INTEGER NOT NULL DEFAULT 0,
    created_at      REAL NOT NULL,
    last_updated_at REAL NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS environment_zones (
    zone_id      TEXT PRIMARY KEY,
    map_id       TEXT NOT NULL REFERENCES map_metadata(map_id) ON DELETE CASCADE,
    zone_name    TEXT NOT NULL,
    zone_type    TEXT NOT NULL DEFAULT 'room',
    polygon_json TEXT NOT NULL DEFAULT '[]',
    description  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS ai_context (
    event_id         TEXT PRIMARY KEY,
    timestamp        REAL    NOT NULL,
    session_id       TEXT,
    context_type     TEXT    NOT NULL DEFAULT 'conversation',
    content_hash     TEXT    NOT NULL DEFAULT '',
    content_text     TEXT    NOT NULL DEFAULT '',
    token_count      INTEGER NOT NULL DEFAULT 0,
    model_name       TEXT    NOT NULL DEFAULT '',
    embedding_ref    TEXT,
    privacy_level    TEXT    NOT NULL DEFAULT 'internal',
    retention_policy TEXT    NOT NULL DEFAULT '7_days',
    metadata         TEXT    NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS vector_index_meta (
    index_name   TEXT PRIMARY KEY,
    index_path   TEXT NOT NULL,
    vector_count INTEGER NOT NULL DEFAULT 0,
    dimension    INTEGER NOT NULL DEFAULT 384,
    index_type   TEXT NOT NULL DEFAULT 'Flat',
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS chroma_collection_meta (
    collection_name TEXT PRIMARY KEY,
    description     TEXT NOT NULL DEFAULT '',
    document_count  INTEGER NOT NULL DEFAULT 0,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    started_at   REAL NOT NULL,
    ended_at     REAL,
    user_id      TEXT REFERENCES users(user_id) ON DELETE SET NULL,
    robot_mode   TEXT NOT NULL DEFAULT 'active',
    is_active    INTEGER NOT NULL DEFAULT 1
);

-- Performance indexes
CREATE INDEX IF NOT EXISTS idx_interactions_user_id   ON interactions(user_id);
CREATE INDEX IF NOT EXISTS idx_interactions_timestamp ON interactions(timestamp);
CREATE INDEX IF NOT EXISTS idx_interactions_session   ON interactions(session_id);
CREATE INDEX IF NOT EXISTS idx_robot_states_timestamp ON robot_states(timestamp);
CREATE INDEX IF NOT EXISTS idx_safety_events_type     ON safety_events(event_type);
CREATE INDEX IF NOT EXISTS idx_safety_events_ts       ON safety_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_navigation_events_ts   ON navigation_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_log_actor        ON audit_log(actor);
CREATE INDEX IF NOT EXISTS idx_audit_log_ts           ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_ai_context_session     ON ai_context(session_id);
CREATE INDEX IF NOT EXISTS idx_ai_context_hash        ON ai_context(content_hash);
""",
    ),
]

# Flat DDL used by tests / tooling that just wants the raw SQL
ALL_DDL: str = "\n".join(sql for (_, _, sql) in MIGRATIONS)
