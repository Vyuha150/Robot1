# Model Evaluation Policy

## The 7-criteria deployment gate

`bonbon_data_pipeline.model_evaluation.evaluate_for_deployment()` — a model may become the default only if **all seven** pass:

| # | Criterion | Field(s) | Unmeasured behavior |
|---|---|---|---|
| 1 | Accuracy / target metric passes | `target_metric_value` vs `target_metric_threshold` | n/a — always required |
| 2 | Latency target passes | `latency_ms` vs `latency_target_ms` | UNVERIFIED (blocks) |
| 3 | No safety delay | `safety_delay_ms` vs `safety_delay_limit_ms` | PASSED — capability has no declared safety-relevant delay budget |
| 4 | Memory stable | `ram_mb` vs `ram_baseline_mb` (±10%) | UNVERIFIED (blocks) |
| 5 | No thermal overload | `temperature_c` vs `thermal_limit_c` | UNVERIFIED (blocks) |
| 6 | Fallback works | `fallback_verified` | FAILED if not explicitly verified |
| 7 | Regression tests pass | delegated to `bonbon_field_learning.ModelEvaluationTracker.deployment_allowed()` | — |

**An unmeasured criterion blocks deployment exactly like a failed one.** This is the deliberate answer to "a model cannot become default without a benchmark": running `evaluate_for_deployment()` with no RAM/temperature reading (this dev environment's actual state — no real Pi) returns `allowed=False`, with `criteria["memory"]`/`criteria["thermal"]` reported `UNVERIFIED`, not silently `PASSED`. Verified live in this session:

```
$ python scripts/data/benchmark_candidate_on_pi.py --model-id test_model ... --out cand.json
NOTE: not running on a detected Pi/ARM device -- temperature_c will be null ...
$ python scripts/data/evaluate_candidate_model.py cand.json
BLOCKED -- failing/unverified criteria:
  - RAM usage was not measured for this candidate
  - no real hardware temperature reading available (dev/CI environment has no Pi thermal sensor)
exit code: 1
```

Full test coverage: `tests/data_pipeline/test_model_evaluation.py`, 15 tests — one per criterion (pass/fail), the fully-unmeasured case, the fully-passing case, and the record/no-record split.

## Composition, not duplication

Criterion 7 is **delegated**, not reimplemented: `evaluate_for_deployment()` calls the existing, already-dashboard-wired `bonbon_field_learning.model_evaluation_tracker.ModelEvaluationTracker.deployment_allowed()` — the "blocks deployment if regression worsens vs. the last recorded evaluation" logic that already existed before this pass. Criteria 1–6 are the genuinely new addition: the prior tracker only ever recorded `regression_pass_rate`, with no latency/memory/thermal/fallback/safety-delay dimension at all.

`evaluate_and_record()` only writes a new baseline when the gate **passes** — a rejected candidate's score is never recorded as the new comparison point (verified `test_rejected_candidate_is_not_recorded`), matching the existing tracker's own stated contract.

## Relationship to `bonbon_ai_model_registry`

`bonbon_ai_model_registry.model_benchmark_runner.BenchmarkRunner` executes the actual per-capability inference calls and produces raw latency numbers (already existed, unchanged by this pass). `scripts/data/benchmark_candidate_on_pi.py` gathers the hardware-specific numbers that runner doesn't (RAM/CPU/temperature) and merges everything into the `CandidateBenchmark` shape this policy's gate consumes — an orchestration addition, not a second benchmark engine.
