# Production-Ready Testing Framework

The capstone doc for BonBon's behavior improvement and production
validation framework. Each section below answers one of the framework's
required questions, with pointers to the deeper doc and the real code/test
evidence.

## 1. Why 100 fixed tests are not enough

A fixed list checks exactly the points someone thought to write down, in a
space that is effectively infinite (environment × lighting × people ×
gesture × speech × robot-state × sensor-health). It cannot grow on its
own, and it does not learn from what the robot actually gets wrong in the
field. Full argument: [PRODUCTION_BEHAVIOR_VALIDATION_STRATEGY.md](PRODUCTION_BEHAVIOR_VALIDATION_STRATEGY.md).

## 2. How many scenario families were created

**15**, one per required domain (boot/deployment topology, Pi+AI HAT
runtime, safety/e-stop, sensor failure, power/thermal, navigation, object
recognition, multi-person tracking, gesture, speech/diarization,
human-state fusion, behavior engine, dashboard/operator, degraded mode,
field pilot learning) — fully specified in
[SCENARIO_FAMILIES.md](SCENARIO_FAMILIES.md) (purpose, risk, modules,
variables, expected behavior, safety constraints, dashboard expectations,
pass/fail criteria, recovery, logs, metrics, and CI-safe/simulation/
hardware-gated strategy for each).

## 3. How scenario variations are generated

`tests/scenarios/scenario_generator.py` expands each family's declared
axes (from `scenario_catalog.yaml`) into the cartesian product of just
those axes, then deterministically stride-samples down to a per-family cap
— **459 concrete scenarios** currently, regenerable and growable by
widening the YAML, not by writing more test functions. Full detail:
[SCENARIO_VARIATION_GENERATOR.md](SCENARIO_VARIATION_GENERATOR.md).

## 4. Which tests are CI-safe

Everything under `tests/production/` except scenarios explicitly marked
`hardware_gated` (and its more specific `pi_gated`/`ai_hat_gated`
sub-markers). CI-safe means every input is a fixture, mock, or simulation
replay — no physical sensor, actuator, or accelerator read. Run with:

```bash
python -m pytest tests/production -m "not hardware_gated" -q
```

**655 tests pass this way today** (10 skipped — the hardware-gated ones,
honestly, not counted as passed).

## 5. Which tests are hardware-gated

Every family whose correctness genuinely depends on real hardware: boot
topology's live one-supervisor check, the AI HAT's real Hailo inference,
the physical e-stop button under real load, live sensor unplug/replug,
real thermal/CPU measurement, live multi-person/gesture/speech accuracy
in a room, and live degraded-mode trigger/recovery. Off the named
hardware they **SKIP** with a stated BLOCKED reason
(`tests/production/_hardware_gates.py`'s `pi_gated`/`ai_hat_gated`
markers, reusing `bonbon_ai_runtime`'s real `HailoDeviceDetector` — no
mock). They never silently pass and never disappear from the report.

```bash
BONBON_HAILO_HW_TEST=1 BONBON_PI_HW_TEST=1 python -m pytest tests/production -m hardware_gated -q
```

## 6. How field failures become regression tests

Behavior Oracle `FAIL` → `FailureCaseLogger` (anonymized event, one per
failed check) → `HumanReviewQueue` (human labels the correct outcome) →
`AnnotationExporter` (labeled JSONL) → `RegressionTestGenerator` (new
`Scenario` appended to `generated_scenarios/regression_scenarios.yaml`) →
asserted forever after by
`tests/production/test_field_pilot_learning_scenarios.py`. Full loop,
including the exact privacy contract:
[FIELD_LEARNING_LOOP.md](FIELD_LEARNING_LOOP.md).

## 7. How online data can be used safely

Public datasets for base capability (per-category breakdown of what each
buys and what it can't:
[ONLINE_DATASET_STRATEGY.md](ONLINE_DATASET_STRATEGY.md)), gated through
an 8-item pre-training checklist
([DATASET_LICENSE_CHECKLIST.md](DATASET_LICENSE_CHECKLIST.md)) before any
dataset touches a training run. No dataset has been sourced yet in this
repo — `config/dataset_license_checklist.yaml` honestly reports every
capability as `NOT_SOURCED` rather than a fabricated "cleared" state.

## 8. What BonBon-specific data is still needed

Everything that depends on this robot's own hardware and deployment
sites: the entire safety-relevant gesture vocabulary (no public dataset
has `stop_palm`), emergency-phrase ASR on this mic array, multi-person
ID-switch rate on this camera, and — unconditionally, per the brief's own
rule — all navigation validation and all behavior-validation judgments
(there is no public dataset for "was that the correct robot behavior").
See category-by-category detail in
[ONLINE_DATASET_STRATEGY.md](ONLINE_DATASET_STRATEGY.md).

## 9. How production readiness score is calculated

15 metrics → 7 weighted categories (safety 30% / reliability 20% /
perception 15% / HRI 15% / edge 10% / dashboard 5% / maintainability 5%),
with a hard gate: safety below 95% forces `FAIL` regardless of the
weighted total, and any metric nobody measured stays `None` (never
fabricated as 0 or 100%) — so a fresh checkout without a real robot
honestly reports `BLOCKED`, not a fake pass. Full formula and honesty
rules: [PRODUCTION_READINESS_SCORING.md](PRODUCTION_READINESS_SCORING.md).

## 10. Exact commands to run tests

```bash
# CI-safe production scenario suite
python -m pytest tests/production -m "not hardware_gated" -q

# a single family
python -m pytest tests/production/test_safety_scenarios.py -m safety -q

# with a real JUnit XML report the dashboard reads
bash scripts/run_production_tests.sh          # CI-safe only
bash scripts/run_production_tests.sh --all     # + hardware_gated (SKIPs off-Pi)

# hardware-gated, on a real Pi 5 + AI HAT only
BONBON_HAILO_HW_TEST=1 BONBON_PI_HW_TEST=1 python -m pytest tests/production -m hardware_gated -q

# oracle + field-learning + production-score unit tests
python -m pytest tests/unit/test_behavior_oracle.py tests/unit/test_field_learning.py tests/unit/test_production_score.py -q

# everything pure-Python in the repo (unchanged suites + this framework)
bash scripts/test.sh --no-ros2
```

## 11. Exact commands to generate scenario reports

```bash
# (re)generate the full scenario catalog from tests/scenarios/scenario_catalog.yaml
python tests/scenarios/scenario_generator.py

# regenerate a single family while iterating
python tests/scenarios/scenario_generator.py --family gesture_understanding

# production readiness score report
python -m bonbon_behavior_validation.production_score --report
```

## 12. Exact dashboard endpoints added

```
GET  /api/v1/validation/scenario-families
GET  /api/v1/validation/generated-scenarios
GET  /api/v1/validation/test-results
GET  /api/v1/validation/production-score
GET  /api/v1/field-learning/failure-cases
GET  /api/v1/field-learning/regression-tests
GET  /api/v1/datasets/status
GET  /api/v1/datasets/license-checklist
GET  /api/v1/models/evaluation
GET  /api/v1/privacy/data-collection-status
```

Full endpoint-by-endpoint source/fallback table and the frontend panel:
[DASHBOARD_VALIDATION_INTEGRATION.md](DASHBOARD_VALIDATION_INTEGRATION.md).

## Architecture map

```
docs/SCENARIO_FAMILIES.md (15 families)
        v
tests/scenarios/{scenario_schema,scenario_generator,scenario_catalog}.{py,yaml}
        v
tests/scenarios/generated_scenarios/  (459 scenarios + regression_scenarios.yaml)
        v
tests/production/test_*_scenarios.py  (15 files, real modules driven where they exist)
        v
bonbon_behavior_validation/  (BehaviorOracle + 10 checks + production_score.py)
        |
        +-- bonbon_field_learning/  (failure -> review -> regression -> version -> gate)
        v
bonbon_operator_api/api/validation_api.py  (10 dashboard endpoints)
        v
frontend "Behavior Validation Framework" panel
```
