# bonbon_data_feedback

Failure-case logging, hard-negative collection, labeled-dataset export,
model-evaluation tracking, and privacy-safe retention for model
improvement.

## Hard rule

**Raw face/audio is never stored by default.** A raw snapshot reference is
only ever persisted when `debug_mode_enabled` is an explicit launch
parameter — never inferred, never on by default. `PrivacySafeDataPolicy`
also strips any context-dict key that looks like raw biometric payload
(`face_embedding`, `audio_bytes`, etc.) **unconditionally**, even in debug
mode — debug mode controls a file-path reference, never raw payload riding
along in the general context.

## Why a separate database, not bonbon_data_stores' existing tables

This data has materially different retention rules than operational data
(face cases: 30 days; object: 90 days — see `PrivacySafeDataPolicy`) and is
specifically about model failures, which should be reviewable/exportable
independently of routine interaction logs. To honor "do not duplicate
database access," this package reuses `bonbon_data_stores`' connection and
migration machinery directly — `SQLiteConnection` and `SchemaMigrator`
(the latter extended with an optional `migrations` parameter, backward
compatible, so both packages share the same generic runner against their
own schema) — rather than writing a second ad-hoc SQLite layer.

## Core modules (`core/`, no rclpy)

| Module | Responsibility |
|---|---|
| `privacy_safe_data_policy.py` | The gate every other component consults — raw-snapshot allowance, context sanitization, per-category retention. |
| `feedback_store.py` | Repository over `failure_cases` / `dataset_versions` / `model_evaluations`, built batched from the start (`insert_failure_cases_batch`) — the audit found no repository anywhere in this project supporting batch writes. |
| `failure_case_logger.py` | General entry point for logging any failure/uncertainty case. |
| `hard_negative_collector.py` | The specific "confident but wrong" subset most valuable for retraining. |
| `annotation_export_manager.py` | Exports stored cases to JSONL for human review/training. |
| `dataset_version_manager.py` | Names and versions an export so a training run references something stable and reproducible. |
| `model_evaluation_store.py` | Records and compares model evaluation runs across versions. |

## ROS2 interface

Two ways a failure case reaches this node — automatic for one concrete
signal, explicit for everything else (deliberately not adding bespoke
per-signal-type subscription wiring for every category, which would start
to resemble detection logic creeping into a logging package):

1. **Automatic**: subscribes to `/bonbon/gesture/events` and
   `/bonbon/perception_efficiency/policy` (for the live confidence floor);
   logs automatically when a gesture's confidence is below the floor.
2. **Explicit**: `~/report_failure_case` (`bonbon_srvs/ReportFailureCase`)
   — any node can call this directly.

Publishes `/bonbon/data_feedback/data_feedback_node/health`.

## Configuration

See [`config/data_feedback_params.yaml`](bonbon_data_feedback/config/data_feedback_params.yaml).
`debug_mode_enabled` must never be `true` in a production deployment.

## Tests

55 tests across 7 core modules, run against a real temp-file SQLite
database (not mocked). Run: `python -m pytest tests/ -q`.
