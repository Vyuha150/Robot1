# Data Dashboard Integration Report

## Endpoints (all live, all tested)

New router: `ros2_ws/src/bonbon_operator_api/bonbon_operator_api/api/data_api.py`, registered in `main.py` at `/api/v1` alongside every other router.

| Endpoint | Reads from | Permission |
|---|---|---|
| `GET /data/datasets` | `bonbon_data_pipeline.dataset_registry.DatasetRegistry` (new) | `diagnostics:read` |
| `GET /data/license-status` | `bonbon_data_pipeline.dataset_license_checker.DatasetLicenseChecker` (new, live decision per dataset) | `diagnostics:read` |
| `GET /data/failure-cases` | `bonbon_field_learning.AnonymizedEventStore` + `HumanReviewQueue` (existing, reused) | `diagnostics:read` |
| `POST /data/failure-cases/review` | `bonbon_field_learning.HumanReviewQueue.submit_review` (existing, reused) | `diagnostics:write` (engineer+) |
| `GET /data/training-runs` | `bonbon_data_pipeline.training_manifest.TrainingManifest` (new) + live cross-check against the dataset registry | `diagnostics:read` |
| `GET /data/model-evaluations` | `bonbon_field_learning.ModelEvaluationTracker` (existing, reused) | `diagnostics:read` |
| `GET /data/regression-tests` | `bonbon_field_learning.RegressionTestGenerator` (existing, reused) | `diagnostics:read` |
| `GET /data/edge-models` | `bonbon_data_pipeline.export_for_edge.EdgeDeploymentTracker` (new) + `ExportTargetRegistry` (new) | `diagnostics:read` |

**Not a second data path.** Four of the eight endpoints (`failure-cases`, the review POST, `model-evaluations`, `regression-tests`) read the exact same store instances `validation_api.py`'s existing `/field-learning/*`, `/datasets/*`, `/models/evaluation` endpoints already use — exposed under the `/data/*` names this brief requests, not duplicated state.

## Dashboard sections, mapped to real data

| Brief section | Backing |
|---|---|
| Dataset Registry (approved/blocked/needs-review/license) | `GET /data/datasets` (`countByStatus`), `GET /data/license-status` |
| Field Failure Cases (open/reviewed/converted) | `GET /data/failure-cases` (`openCount`, `approvedCount`), `GET /data/regression-tests` for the converted count |
| Training Status (candidate/dataset version/metric/benchmark) | `GET /data/training-runs` (`readyForProductionTraining`, `blockingIssues`), `GET /data/model-evaluations` |
| Edge Deployment Status (active/fallback/version/rollback) | `GET /data/edge-models` |

## Truthfulness, verified not asserted

- `GET /data/training-runs` on the real current config reports `readyForProductionTraining: false` with 18 real blocking issues — never silently reports "ready" while most datasets are still `NEEDS_REVIEW`. Verified: `test_data_api.py::test_data_training_runs_reads_real_targets_and_cross_checks_registry`.
- `GET /data/edge-models` on a fresh install reports `count: 0` — no fabricated "deployed" state. Verified: `test_data_api.py::test_data_edge_models_reports_export_targets_and_empty_deployments`.
- `GET /data/model-evaluations` / `/data/failure-cases` report empty/`available: true` with zero counts when nothing has happened yet, never a placeholder value. Verified: `test_data_api.py::test_data_model_evaluations_honest_when_empty`, `test_data_failure_cases_honest_when_empty`.
- The review POST returns HTTP 404 for an unknown `event_id` and HTTP 403 for a caller without `diagnostics:write` — never a silent 200. Verified: `test_review_unknown_event_id_returns_404`, `test_review_requires_diagnostics_write_permission`.

## Regression

Full `bonbon_operator_api` suite: **256/256 passed** (246 pre-existing + 10 new), confirming the new router doesn't break app startup or any existing endpoint.
