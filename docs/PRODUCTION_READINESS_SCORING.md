# Production Readiness Scoring

`bonbon_behavior_validation.production_score` turns the 15 required
metrics into one number and one verdict — honestly, meaning a metric
nobody measured is never silently treated as 0% or 100%.

## The 15 metrics → 7 weighted categories

| Category | Weight | Metrics |
|---|---|---|
| **safety** | 30% | safety pass rate, emergency stop reliability |
| **reliability** | 20% | degraded mode recovery rate, field failure rate (inverted), regression pass rate |
| **perception** | 15% | object detection precision, object detection recall, person ID switch rate (inverted), speaker diarization error rate (inverted), active speaker assignment accuracy |
| **hri_behavior** | 15% | gesture false trigger rate (inverted), behavior correctness rate |
| **edge_performance** | 10% | average response latency (normalized against a budget), CPU/memory/temperature stability |
| **dashboard_readiness** | 5% | dashboard accuracy rate |
| **maintainability** | 5% | real introspection — see below, not a metric anyone reports |

Weights sum to exactly 1.0 (asserted at import time). All 15 raw metrics
are 0.0–1.0 "higher is better" — callers invert raw error rates (ID-switch
rate, diarization error rate, gesture false-trigger rate, field failure
rate) before constructing `ProductionMetrics`, so the scorer never has to
guess a metric's polarity.

## Honest by construction

Every field on `ProductionMetrics` is `float | None`. A category's score
is the mean of whichever of its metrics are present; if none are present,
the category score is `None` — never 0 (which would look like "measured
and bad") and never silently excluded from the total in a way that hides
the gap. The final verdict:

```python
class Verdict(StrEnum):
    PASS = "PASS"        # safety >= threshold, every category has data
    FAIL = "FAIL"         # safety has data but is below threshold
    PARTIAL = "PARTIAL"   # safety >= threshold, but some other category is missing data
    BLOCKED = "BLOCKED"   # safety has NO data at all -- can't judge production readiness
```

`maintainability_score` is the one exception that's always computable
without hardware: `compute_maintainability_score()` is real introspection
— it checks that every family declared in
`tests/scenarios/generated_scenarios/MANIFEST.yaml` has a matching
`tests/production/test_*_scenarios.py` file, returning the real coverage
ratio (currently `1.0` — all 15 families covered). It is not a
placeholder number; running it against a repo missing production test
files returns a real fraction less than 1.0.

## The hard safety gate

```python
if safety_score < SAFETY_THRESHOLD:   # 0.95
    return ProductionReadinessScore(..., verdict=Verdict.FAIL, ...)
```

This check runs *before* the weighted total is even consulted for the
verdict (the total is still computed and returned for visibility, but it
cannot rescue the verdict). A robot with perfect navigation, perfect
dashboard accuracy, and 100% maintainability still gets `FAIL` if its
safety category is at 80% — `tests/unit/test_production_score.py::TestSafetyGate::test_low_safety_fails_even_with_perfect_everything_else`
asserts exactly this.

## Where the dashboard gets real numbers

`GET /validation/production-score` (Phase 8) builds `ProductionMetrics`
from two real sources: `compute_maintainability_score()` (always live) and
per-family pass rates parsed out of the real JUnit XML written by
`scripts/run_production_tests.sh` (e.g. `safety_pass_rate` and
`emergency_stop_reliability` both come from `test_safety_scenarios`'s pass
rate; `behavior_correctness_rate` from `test_behavior_engine_scenarios`;
etc.). Metrics this server cannot honestly derive without the actual robot
(CPU/temperature stability, true response latency under load) stay `None`
— which is exactly why a fresh checkout's `/validation/production-score`
honestly reports `BLOCKED`, not a fabricated PASS.

## Commands

```bash
# generate the test-results artifact the score is partly derived from
bash scripts/run_production_tests.sh

# compute the score from the CLI (uses real maintainability; everything
# else None unless you pass --metrics-json)
python -m bonbon_behavior_validation.production_score --report

# via the dashboard, after logging in as a viewer-or-above role
curl -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/validation/production-score
```
