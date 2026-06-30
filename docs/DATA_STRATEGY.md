# Data Strategy

Package: [`bonbon_data_feedback`](../ros2_ws/src/bonbon_data_feedback/README.md)

## Purpose

A continuous loop from "the robot got something wrong" to "a versioned,
reviewed dataset a retraining run can point at" — without a second database
layer and without ever storing raw biometrics by default. See
[FAILURE_CASE_LEARNING.md](FAILURE_CASE_LEARNING.md) for the workflow detail
and [PRIVACY_SAFE_DATA_COLLECTION.md](PRIVACY_SAFE_DATA_COLLECTION.md) for
the privacy rules.

## Why a separate database, not new bonbon_data_stores tables

Failure-case data has materially different retention rules than operational
data (face cases: 30 days; object: 90 days — see
`PrivacySafeDataPolicy`) and benefits from being reviewable/exportable
independently of routine interaction logs. The "do not duplicate database
access" rule is honored at the *connection/migration layer*, not the
*table* layer: `bonbon_data_feedback` reuses `bonbon_data_stores`'
`SQLiteConnection` and `SchemaMigrator` directly (the latter gained one
small, backward-compatible extension — an optional `migrations` constructor
parameter — so a second schema can be applied by the same generic runner
instead of a reimplementation). A separate database *file* is a deliberate,
documented choice, not an oversight.

## The four data flows

```
Perception nodes ──┐
                    │  (automatic: gesture confidence below the live floor)
                    ├──► FailureCaseLogger ──► failure_cases table
                    │
Any node ───────────┘  (explicit: ~/report_failure_case service)
                          │
                          ▼
                    HardNegativeCollector (confidence ≥ threshold AND wrong)
                          │
                          ▼
                    AnnotationExportManager ──► JSONL export
                          │
                          ▼
                    DatasetVersionManager ──► dataset_versions table
                                              (named, versioned, reproducible)

Separately: ModelEvaluationStore ──► model_evaluations table
            (records + compares accuracy across model versions)
```

## Why two entry points, not bespoke per-signal wiring

Adding a dedicated ROS2 subscription for every signal type (object, gesture,
face, voice, text) would mean this package re-derives knowledge of every
other package's message types and confidence semantics — creeping toward
detection logic in what's meant to be a logging package. Instead:

1. **One concrete automatic signal** (`GestureEvent` below the live
   confidence floor published by `bonbon_perception_efficiency`) proves the
   automatic path end-to-end without becoming a registry of every signal
   type.
2. **One general service** (`~/report_failure_case`,
   `bonbon_srvs/ReportFailureCase`) any node can call directly — the
   extensible mechanism for everything else.

## Retention

Enforced by an hourly sweep (`retention_sweep_rate_hz`, default ~1/hour)
calling `FeedbackStore.delete_expired(category, cutoff)` per category, using
`PrivacySafeDataPolicy.retention_days_for(category)`. Defaults: face 30
days, speaker/emotion 60 days, object/gesture 90 days.

## Tests

55 tests across 7 core modules, run against a real temp-file SQLite database
(not mocked) — see [OPTIMIZATION_TESTING.md](OPTIMIZATION_TESTING.md).

## Performance

`FeedbackStore.insert_failure_cases_batch()` p95 = 0.253 ms for a 1-row
benchmark write against a 100 ms budget (the batch API itself is what
matters under load — see [PERFORMANCE_METRICS.md](PERFORMANCE_METRICS.md)).

## Troubleshooting

- **`dataset_versions.case_count` is 0 right after `create_version()`** —
  `create_version` defaults `reviewed_only=True`; an unreviewed failure case
  is a candidate, not yet a labeled training example. Call
  `store.mark_reviewed(case_id, label)` first, or pass
  `reviewed_only=False` if that's intentional for your export.
- **Export file exists but is empty** — confirm the `category` filter
  matches what was actually logged; `AnnotationExportManager.export()`
  silently returns a zero-row file rather than erroring on an empty match.
