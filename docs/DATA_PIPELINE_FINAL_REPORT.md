# Data Pipeline Final Report

Consolidated summary of the data/training/fine-tuning/evaluation/deployment pipeline brief. Every number here is cited from a real test run or a real file, not estimated.

## Scope decision: extend, don't duplicate

The brief's literal file list (`bonbon_data_pipeline/field_failure_logger.py`, `human_review_queue.py`, `regression_test_generator.py`, `model_evaluation.py` as a standalone store) would have created a **third parallel implementation** of field-failure logging on top of two that already exist: `bonbon_field_learning` (dashboard-facing, already wired into `validation_api.py`, already tested) and `bonbon_data_feedback` (the live ROS2 robot-side writer). This was flagged to the user before writing any code; the user chose **"extend existing, fill real gaps only."** Concretely:

- **Reused as-is:** `bonbon_field_learning`'s `AnonymizedEventStore`, `HumanReviewQueue`, `AnnotationExporter`, `RegressionTestGenerator`, `ModelEvaluationTracker`; `bonbon_ai_model_registry`'s model-artifact license/download/benchmark machinery.
- **Extended additively:** `FailureCategory` enum (+5 values), `ModelEvaluationTracker`'s single regression check composed into a full 7-criteria gate.
- **Built new, because nothing covered it:** a *dataset*-level registry (source training data, distinct from deployed model artifacts), domain-specific annotation schemas, a dataset-ingestion privacy guard, a training manifest, an edge-export policy/deployment tracker, and the `/data/*` dashboard surface.

## 1. Approved data sources

6 datasets `APPROVED` today, all fully synthetic/internally-generated or already-anonymized (zero external rights question): `synthetic_hospital_objects`, `mediapipe_landmark_extraction` (Apache-2.0, offline Python-side, distinct from the quarantined browser `@mediapipe/hands` package), `synthetic_gesture_variations`, `bonbon_field_emotion_signals`, `simulated_hospital_maps`, `bonbon_blocked_path_failure_logs`. Full list: `docs/DATASET_REGISTRY_REPORT.md`.

## 2. Blocked data sources

2 datasets `BLOCKED` today, both real non-commercial licenses caught correctly: `public_gesture_dataset_jester` (CC BY-NC-SA 4.0) and `ravdess_voice_emotion` (CC BY-NC-SA 4.0). No public face-scraping dataset is or will be registered — enforced by omission, per `docs/DATA_LICENSE_AND_PRIVACY_REPORT.md`.

## 3. What BonBon should collect

20 datasets registered `NEEDS_REVIEW` — the honest majority, spanning ASR/TTS/object-detection/gesture/navigation/RAG per the brief's 8 categories. Every entry names its `intended_use`, `prohibited_use`, and `preprocessing_needed`. Full list: `docs/DATASET_REGISTRY_REPORT.md`.

## 4. How privacy is protected

Raw face/audio/video storage disabled by default (`PrivacyPolicy()`'s three flags default `False`, fail-closed even with a missing policy file); face-recognition enrollment requires a structurally-enforced `ConsentRecord` (`enroll_face()` raises rather than returns a boolean). 11 tests, `docs/DATA_LICENSE_AND_PRIVACY_REPORT.md`.

## 5. How training happens off-device

Every one of 7 training targets (`config/data/training_targets.yaml`) declares `training_machine: workstation_gpu`; `TrainingManifest.validate_against_registry()` structurally fails any target naming a Pi/edge board. `docs/TRAINING_AND_FINE_TUNING_PLAN.md`.

## 6. How models are exported to Pi/Hailo

Hailo HEF for vision (with ONNX CPU fallback), TFLite for small classifiers, GGUF for LLM experiments (never Hailo), SQLite/vector for RAG, cached WAV for TTS phrases — `config/data/model_export_targets.yaml`, `docs/EDGE_MODEL_EXPORT_REPORT.md`. Export scripts are real (not stubs); the Hailo compile step is honestly `HARDWARE_BLOCKED` in this dev environment, matching this repo's established hardware-gating discipline.

## 7. How benchmarks decide deployment

The literal 7-criteria gate (`bonbon_data_pipeline.model_evaluation.evaluate_for_deployment`) — an unmeasured criterion (no real Pi to read RAM/temperature from) blocks exactly like a failed one, verified live: a candidate benchmarked on this dev machine is correctly `BLOCKED`. `docs/MODEL_EVALUATION_POLICY.md`.

## 8. How failures become regression tests

`FailureCaseLogger.log_failure()` → `HumanReviewQueue.submit_review(approve=True)` → `AnnotationExporter.approved_examples()` → `RegressionTestGenerator.generate()`, all pre-existing and reused; extended with 5 new failure categories this brief required. An unreviewed or rejected case cannot be converted (`ValueError`/empty list, not a silent skip). `docs/FIELD_FAILURE_LEARNING_REPORT.md`.

## 9. Dashboard endpoints added

8 new `/api/v1/data/*` endpoints, 4 of which are thin re-exposures of already-live stores under the brief's requested path names (not a second data path). `docs/DATA_DASHBOARD_INTEGRATION_REPORT.md`.

## 10. Test results

| Suite | Result |
|---|---|
| `tests/data_pipeline/` (9 files) | **86/86 passed** |
| `bonbon_operator_api` full suite (incl. new `test_data_api.py`) | **256/256 passed** (was 246) |
| `tests/unit` + `tests/data_pipeline` + `tests/production` combined | **787 passed, 10 skipped** |
| Top-level `tests/` (repo-wide baseline) | **1099 passed, 15 skipped** (was 1013/15 — +86, zero regressions, zero new skips) |
| Lint (`ruff check` on every new file) | Clean after 4 auto-fixed issues (unused imports, import ordering) |

## Final verdict: **PASS**

All 10 critical rules hold, verified by real tests rather than asserted: unlicensed/commercial-restricted/unverified-safety datasets are blocked (real fixtures, not hypotheticals); raw media storage is off by default and face enrollment requires structural consent; no safety-relevant training proceeds without explicit verification; the LLM export path never targets a motor/servo/Nav2/safety-adjacent artifact; every training target runs off-Pi; every new model requires a full, honestly-gated benchmark before deployment; every reviewed failure has a real path to becoming a regression test. Two honest gaps are named rather than hidden: `bonbon_data_feedback`'s live ROS2 writes are not yet wired into `bonbon_field_learning`'s dashboard-facing store, and `update_rag_index.py`'s output is not yet wired into `RAGRetriever`'s in-memory load path — both real follow-up integration work, not silently claimed done.
