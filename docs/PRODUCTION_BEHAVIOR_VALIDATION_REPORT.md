# Production Behavior Validation Report

Status report for Phase 5 of finalization: does the scenario-family-based
validation system (not "100 flat tests") actually exist and work. Design
rationale: [PRODUCTION_BEHAVIOR_VALIDATION_STRATEGY.md](PRODUCTION_BEHAVIOR_VALIDATION_STRATEGY.md).
Family definitions: [SCENARIO_FAMILIES.md](SCENARIO_FAMILIES.md).
Generator mechanics: [SCENARIO_VARIATION_GENERATOR.md](SCENARIO_VARIATION_GENERATOR.md).
Oracle mechanics: [BEHAVIOR_ORACLE.md](BEHAVIOR_ORACLE.md).

## Verdict: PASS — fully implemented, all pieces tested and green

| Deliverable | Path | Status |
|---|---|---|
| 15 scenario families | `docs/SCENARIO_FAMILIES.md` | **PASS** |
| Validation strategy doc | `docs/PRODUCTION_BEHAVIOR_VALIDATION_STRATEGY.md` | **PASS** |
| Scenario schema | `tests/scenarios/scenario_schema.py` | **PASS** |
| Scenario generator | `tests/scenarios/scenario_generator.py` | **PASS** — 459 generated scenarios |
| Scenario catalog | `tests/scenarios/scenario_catalog.yaml` | **PASS** |
| Behavior Oracle | `bonbon_behavior_validation/behavior_oracle.py` | **PASS** — 14 unit tests |
| Production score | `bonbon_behavior_validation/production_score.py` | **PASS** — 14 unit tests |

## The 8 required Behavior Oracle checks (this brief's list)

All 8 are a subset of the oracle's 10 implemented checks (2 extra —
"handled low confidence correctly" and "asked clarification when
needed" — were already required by the earlier, broader behavior-
validation brief and remain in place, a superset not a gap):

| # (this brief) | Check | Oracle check name |
|---|---|---|
| 1 | correct person responded to | `responded_to_correct_person` |
| 2 | correct safety decision | `supervisor_decision_correct` |
| 3 | no identity mix-up | `no_identity_mixup` |
| 4 | no LLM direct action | `llm_no_direct_action` |
| 5 | dashboard updated | `dashboard_was_updated` |
| 6 | logs generated | `event_was_logged` |
| 7 | degraded mode correct | `degraded_mode_entered` (+ `never_disable` integrity) |
| 8 | unsafe movement blocked | `no_unsafe_movement` |

## Test totals (this environment)

- `tests/production/` (15 files, one per family): **655 passed, 10
  skipped** (`bash scripts/run_production_tests.sh`).
- `tests/unit/test_behavior_oracle.py`: **14 passed**.
- `tests/unit/test_production_score.py`: **14 passed**.
- `tests/scenarios/`: **41 passed** (scenario generator + cross-package
  scenarios).

## No-fake-PASS guarantee for this system specifically

- Scenarios with `hardware_requirement: pi` or `ai_hat` carry the
  `pi_gated`/`ai_hat_gated` markers and SKIP honestly off real hardware
  (see [HARDWARE_GATED_TESTS.md](HARDWARE_GATED_TESTS.md)).
- The Behavior Oracle never returns PASS for a check it has no data for —
  it returns `NOT_APPLICABLE`, which never masks a real failure elsewhere
  in the same verdict.
- `production_score.py`'s `ProductionMetrics` fields are `Optional`;
  missing data is `None`, never fabricated as 0% or 100% — see
  [PRODUCTION_READINESS_SCORING.md](PRODUCTION_READINESS_SCORING.md).

## What's still BLOCKED

Real-world accuracy numbers (object detection precision/recall on a live
Hailo, actual multi-person ID-switch rate in a crowded room, actual
gesture/speech recognition accuracy) all require the physical robot —
the framework is proven correct and complete; the *numbers* it will
report on real hardware are not yet known.
