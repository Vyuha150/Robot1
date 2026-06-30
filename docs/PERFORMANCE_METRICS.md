# Performance Metrics

Packages: [`bonbon_perception_efficiency`](../ros2_ws/src/bonbon_perception_efficiency/README.md),
[`bonbon_data_feedback`](../ros2_ws/src/bonbon_data_feedback/README.md),
[`bonbon_safety`](../ros2_ws/src/bonbon_safety/README.md) (benchmark host)

## Metric catalogue

Every metric named in the brief, and where it is actually produced. None of
these are a new collection pipeline — each aggregates a value an existing
node already computes.

| Metric | Source | Topic/field |
|---|---|---|
| Object detection accuracy | `bonbon_data_feedback.ModelEvaluationStore` | `model_evaluations.accuracy` (category="object") |
| Gesture false trigger rate | `bonbon_data_feedback.HardNegativeCollector` | `failure_cases` where `category="gesture"`, `is_hard_negative=1` |
| Person tracking ID switches | `bonbon_multi_person_tracker` (pre-existing) | not duplicated here — see its own health/metrics |
| Speaker diarization errors | `bonbon_speaker_intelligence` (pre-existing) | not duplicated here |
| Human-state fusion confidence | `bonbon_human_state_fusion`'s `HumanState.confidence` (pre-existing) | aggregated per-module in `ModuleHealth.error_count`/`warning_count` |
| Model latency | `PerceptionEfficiencyMetrics.avg_latency_ms`/`max_latency_ms` | `/bonbon/perception_efficiency/metrics`, aggregated from every node's own `ModuleHealth.latency_ms` |
| Queue delay | `BoundedInferenceQueue.oldest_age_sec()` | computed in-process by the owning node (e.g. `bonbon_affective_ai`'s voice/text queues) |
| Dropped frames | `StaleFrameDropper`, `BoundedInferenceQueue.dropped_count` | computed in-process by the owning node |
| CPU/memory/temperature | `ResourceUsage` | `/bonbon/system/resource_usage` (published by `bonbon_safety`, wired in Phase 1 of this round — previously dead code) |
| Degraded mode duration | `DegradedModeStatus.duration_sec` | `/bonbon/perception_efficiency/degraded_mode` |
| Unsafe action blocked rate | `bonbon_safety`/`bonbon_behavior_engine`'s existing authorization denial counters | not duplicated here |

`PerceptionEfficiencyMetrics` (published on `/bonbon/perception_efficiency/metrics`,
2 Hz default) is the single aggregation point for the metrics this round's
work owns:

```
module_count, worst_status, worst_status_module,
avg_latency_ms, max_latency_ms, total_errors, total_processed,
cpu_percent, memory_percent, recommended_load_shed,
load_level, degraded_mode_active
```

## Evaluation dashboard data schema

A dashboard needs exactly three subscriptions for the full picture this
round's work adds — no new aggregation service required:

```json
{
  "resource": {
    "topic": "/bonbon/system/resource_usage",
    "type": "bonbon_msgs/ResourceUsage",
    "fields": ["cpu_percent", "memory_percent", "memory_mb", "disk_free_percent",
               "cpu_overloaded", "memory_pressure", "disk_low", "recommended_load_shed"]
  },
  "perception_metrics": {
    "topic": "/bonbon/perception_efficiency/metrics",
    "type": "bonbon_msgs/PerceptionEfficiencyMetrics",
    "fields": ["module_count", "worst_status", "worst_status_module",
               "avg_latency_ms", "max_latency_ms", "total_errors", "total_processed",
               "load_level", "degraded_mode_active"]
  },
  "degraded_mode": {
    "topic": "/bonbon/perception_efficiency/degraded_mode",
    "type": "bonbon_msgs/DegradedModeStatus",
    "fields": ["is_degraded", "reason", "duration_sec"]
  }
}
```

For model evaluation history, query `bonbon_data_feedback`'s
`ModelEvaluationStore.list_evaluations()` / `FeedbackStore.list_dataset_versions()`
directly (SQLite, not a topic — these are not high-rate streaming values).

## Benchmark scripts

[`bench_hotpaths.py`](../ros2_ws/src/bonbon_safety/tests/benchmarks/bench_hotpaths.py)
is the canonical benchmark, extended this round (not duplicated) with:

```bash
cd ros2_ws/src/bonbon_safety
python tests/benchmarks/bench_hotpaths.py        # human-readable table
python tests/benchmarks/bench_hotpaths.py --json # machine-readable
python -m pytest tests/benchmarks/bench_hotpaths.py -q  # CI latency assertions
```

| Budget | Target | Measured p95 |
|---|---|---|
| `perception_budget_cycle` | ≤ 50 ms | 0.014 ms |
| `failure_case_log_write` | ≤ 100 ms | 0.253 ms |

`perf_targets.py` catalogue: 16 budgets total (14 from prior work, 2 added
this round).

## Regression test reports

`scripts/test.sh --no-ros2` is the CI-equivalent gate (the `python-tests`
CI job runs exactly this). It now includes every package touched this
round — `bonbon_perception_efficiency`, `bonbon_data_feedback`, `bonbon_llm`
(previously not in the gate at all), and the extended
`tests/scenarios/` suite. A pass/fail report is pytest's own per-package
summary line; there is no separate report-generation step — adding one
would duplicate what CI's own log already provides.

```bash
bash scripts/test.sh --no-ros2
# ... per-package pytest summaries ...
### All pure-Python suites passed ###
```

## Model comparison report template

Built from `ModelEvaluationStore.compare()`:

```python
from bonbon_data_feedback.core.model_evaluation_store import ModelEvaluationStore

store = ModelEvaluationStore(feedback_store)
cmp = store.compare(model_name="gesture_classifier", version_a="v2", version_b="v3")
```

```
Model Comparison: gesture_classifier
=====================================
  v2 accuracy: {cmp.accuracy_a}
  v3 accuracy: {cmp.accuracy_b}
  Improved:    {cmp.improved}   # True / False / None (None = a version has no recorded eval)
```

`cmp.improved is None` is a distinct, checkable state from `False` — it
means the comparison couldn't be made (a version was never evaluated), not
that v3 regressed. A report generator should surface this distinction
rather than collapsing it to "no improvement."

## Tests

`test_perf_targets.py` (5 tests, catalogue integrity), `bench_hotpaths.py`
(17 latency-assertion tests, 2 new this round),
`test_perception_metrics_aggregator.py` (8 tests),
`test_model_evaluation_store.py` (5 tests). See
[OPTIMIZATION_TESTING.md](OPTIMIZATION_TESTING.md) for the complete
inventory.
