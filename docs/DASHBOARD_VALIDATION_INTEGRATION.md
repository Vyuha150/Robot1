# Dashboard Validation Integration

The 10 endpoints + 1 frontend panel that make the entire behavior
validation framework (Phases 1–7) observable from the operator dashboard,
added in `ros2_ws/src/bonbon_operator_api/bonbon_operator_api/api/validation_api.py`.

## Endpoints

| Endpoint | Real source | Honest fallback |
|---|---|---|
| `GET /validation/scenario-families` | `tests/scenarios/scenario_catalog.yaml` | `available:false` if missing |
| `GET /validation/generated-scenarios` | `generated_scenarios/MANIFEST.yaml` | points at `scenario_generator.py` |
| `GET /validation/test-results` | real JUnit XML, parsed with stdlib `xml.etree` | points at `scripts/run_production_tests.sh` |
| `GET /validation/production-score` | live `ProductionScoreCalculator` fed from the JUnit XML's per-family pass rates + live maintainability introspection | metrics without a real source stay `None` (see [PRODUCTION_READINESS_SCORING.md](PRODUCTION_READINESS_SCORING.md)) |
| `GET /field-learning/failure-cases` | live `AnonymizedEventStore` | empty list when nothing logged yet (true, not fake) |
| `GET /field-learning/regression-tests` | live `RegressionTestGenerator` catalog | empty when no field failure has been reviewed yet |
| `GET /datasets/status` | live `DatasetVersionManager` | starts at `0.0.0`, empty history |
| `GET /datasets/license-checklist` | `config/dataset_license_checklist.yaml` | every category `NOT_SOURCED` until actually cleared |
| `GET /models/evaluation` | live `ModelEvaluationTracker` | `latest: null` when no run recorded |
| `GET /privacy/data-collection-status` | introspects `AnonymizedEvent.__dataclass_fields__` directly + checks for an active debug-snapshot index | reports the real field list, not a self-attested "compliant" flag |

All ten require `diagnostics:read` (the same permission gate the
deployment endpoints use) via FastAPI's `require_permission` dependency,
and all return the standard `APIResponse` envelope (`{success, data,
error, timestamp}`).

## "No fake PASS" — by construction, not by convention

- `/validation/test-results` and `/validation/production-score` both read
  from the *same* JUnit XML — there's no path where the dashboard shows a
  test as passed without a real pytest run having produced that record.
- `/datasets/license-checklist` starts every capability at `NOT_SOURCED`;
  nothing flips to `CLEARED` without someone editing
  `config/dataset_license_checklist.yaml` after actually running the
  8-item checklist (see
  [DATASET_LICENSE_CHECKLIST.md](DATASET_LICENSE_CHECKLIST.md)).
- `/privacy/data-collection-status` doesn't ask the field-learning code
  "are you privacy-compliant?" (a self-report that could drift from
  reality) — it reads the dataclass's actual field names and checks
  whether any of them look like raw-media storage. If a future change
  added a `raw_face_bytes` field to `AnonymizedEvent`, this endpoint would
  immediately start reporting it, because the check is structural.

## Frontend

`frontend/src/services/api.ts` gained 10 methods
(`getScenarioFamilies`, `getGeneratedScenarios`, `getValidationTestResults`,
`getProductionScore`, `getFieldLearningFailureCases`,
`getFieldLearningRegressionTests`, `getDatasetsStatus`,
`getDatasetsLicenseChecklist`, `getModelsEvaluation`,
`getPrivacyDataCollectionStatus`). `App.tsx`'s System tab gained a
**"Behavior Validation Framework"** panel (10 buttons, one per endpoint),
positioned directly after the existing "Raspberry Pi Deployment" panel,
structurally identical to it (button → `loadValidation(kind)` → JSON
pretty-printed into a `<pre className="json-view">`).

Verified in a live browser via the preview tools: `tsc --noEmit` clean
(no type errors), the Overview tab renders with no console errors, the
System tab's new panel is present with all 10 labeled buttons, and a
button click is handled gracefully (network failure caught and logged via
the existing `addLog` mechanism, no unhandled exception) even with no
backend server running.

## Commands

```bash
# generate the artifacts the dashboard reads
python tests/scenarios/scenario_generator.py
bash scripts/run_production_tests.sh

# start the dashboard backend + frontend (see scripts/README.md / launch.json)
# then, once logged in:
curl -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/validation/scenario-families
curl -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/validation/production-score
```
