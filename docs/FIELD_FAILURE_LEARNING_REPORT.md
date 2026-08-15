# Field Failure Learning Report

## The real pipeline (not rebuilt, reused)

BonBon already has a two-sided field-failure learning loop, predating this pass:

1. **`bonbon_data_feedback`** (`ros2_ws/src/bonbon_data_feedback`) — the live ROS2 node, wired into `bonbon_bringup/launch/bringup.launch.py`, writing failure cases into its own SQLite store (`FeedbackStore`, via `bonbon_data_stores`' shared connection/migration machinery).
2. **`bonbon_field_learning`** (repo root, standalone) — the offline, dashboard-facing governance layer: `AnonymizedEventStore` → `HumanReviewQueue` → `AnnotationExporter` → `RegressionTestGenerator` → `DatasetVersionManager` → `ModelEvaluationTracker`. Already wired into `bonbon_operator_api`'s `validation_api.py` (`/field-learning/*`, `/datasets/*`, `/models/evaluation`, `/privacy/*`) and covered by `tests/unit/test_field_learning.py` + `tests/production/test_field_pilot_learning_scenarios.py`.

**A genuine architectural finding, stated honestly rather than glossed over:** these two use completely separate, disconnected storage (SQLite vs. JSONL/JSON). The ROS2 node's failure records do not currently flow into the dashboard-facing `AnonymizedEventStore` automatically — they are two real, tested, independently-useful layers that are not yet wired end-to-end. This was true before this pass and is unchanged by it; fixing it is a real follow-up (see "What this doesn't do" below), not something safe to silently claim as done.

## What this pass added (extension, not duplication)

- **Five new `FailureCategory` values** (`WRONG_ASR_TRANSCRIPT`, `WRONG_INTENT`, `WRONG_RAG_ANSWER`, `WRONG_SEMANTIC_LOCATION`, `STAFF_INTERVENTION`), purely additive to `bonbon_field_learning.anonymized_event_store.FailureCategory` — the brief's 13-category list was previously missing 5 of the categories it names, all four ASR/RAG/intent/location cases were falling into the generic `WRONG_RESPONSE` bucket. Verified: existing `tests/unit/test_field_learning.py` (18/18 still passing, zero behavior change to existing categories) plus `tests/data_pipeline/test_failure_logger.py`'s parametrized round-trip test for all 5 new values.
- **`/data/failure-cases` and `POST /data/failure-cases/review`** (dashboard) — reuse the exact same `AnonymizedEventStore`/`HumanReviewQueue` instances `validation_api.py`'s `/field-learning/*` already reads, under the path names this brief requests. Not a second data path.

## Required behaviors, verified

| Requirement | Verified by |
|---|---|
| A field failure creates a review item | `test_failure_logger.py::test_logged_failure_can_be_enqueued_for_review` |
| A reviewed (approved) failure can become a regression test | `test_regression_test_generator.py::test_approved_example_generates_a_scenario` (real `RegressionTestGenerator`, real `Scenario` written to a tmp catalog) |
| A rejected review never becomes a regression test | `test_regression_test_generator.py::test_rejected_example_cannot_be_generated` |
| An unreviewed (pending) case cannot be generated | `test_regression_test_generator.py::test_unreviewed_pending_example_cannot_be_generated` (raises `ValueError`) |

## What this doesn't do

Wiring `bonbon_data_feedback`'s live ROS2 SQLite writes into `bonbon_field_learning`'s `AnonymizedEventStore` so the dashboard's failure-case feed reflects real robot-side events automatically is **not done by this pass** — it's a real integration gap, named here rather than silently assumed solved.
