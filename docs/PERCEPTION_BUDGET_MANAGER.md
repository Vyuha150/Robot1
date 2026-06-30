# PerceptionBudgetManager

Package: [`bonbon_perception_efficiency`](../ros2_ws/src/bonbon_perception_efficiency/README.md) ·
Module: [`core/perception_budget_manager.py`](../ros2_ws/src/bonbon_perception_efficiency/bonbon_perception_efficiency/core/perception_budget_manager.py)

## Purpose

The single per-cycle orchestrator. Every other class in this package is
combined here into one `PerceptionBudget` snapshot, published once per cycle
on `/bonbon/perception_efficiency/budget`. No node in the project needs to
know about the other nine classes individually — only this one.

## Inputs and outputs

```python
@dataclass
class BudgetInputs:
    cpu_overloaded: bool
    memory_pressure: bool
    resource_unavailable: bool = True   # True until a real ResourceUsage arrives
    safety_caution_or_above: bool
    safety_fault_or_above: bool
    focus_person_track_id: str
    person_track_ids: list[str]
    new_candidate_ids: set[str]

@dataclass
class PerceptionBudget:
    load: LoadSheddingDecision
    degraded: DegradedModeStatus
    sample_rates: list[SampleRateRecommendation]
    confidence_policy: list[PolicyRecommendation]
    person_focus: list[PersonFocusWeight]
```

## The nine classes it owns

| Class | One-line role |
|---|---|
| `LoadSheddingController` | CPU/memory/safety → `normal`/`reduced`/`minimal`/`critical`, hysteresis-gated (escalate immediately, de-escalate only after N consistent cycles). |
| `DegradedModeManager` | System-wide degraded flag — sustained load pressure, or an immediate safety FAULT/SAFE_STOP. |
| `ConfidencePolicyManager` | Recommended (never enforced) per-signal confidence thresholds, tightened under degraded/elevated-safety conditions, clamped to each signal's configured floor. |
| `FrameSamplingManager` | Recommended sample-every-Nth-frame per consumer, scaled by current load level. |
| `ActivePersonFocusManager` | Per-person processing weight: focus person = 1.0, new arrival = 0.8 (brief priority), background = 0.3. |
| `StaleFrameDropper`, `BoundedInferenceQueue`, `TemporalSmoothingManager`, `PerceptionMetricsAggregator` | Reusable primitives a node wraps around its own logic directly — not invoked by the orchestrator's per-cycle update, since they're stateful per-stream rather than global. |

The last four are intentionally NOT inside `PerceptionBudgetManager.update()`
— they're per-stream state (one `StaleFrameDropper` per topic, one
`BoundedInferenceQueue` per executor) that a consuming node instantiates and
calls directly, exactly as `bonbon_affective_ai` does for its own voice/text
queues. `PerceptionBudgetManager` only combines the *system-wide* decisions.

## Cycle behavior

```python
mgr = PerceptionBudgetManager(
    load_shedding=LoadSheddingController(hysteresis_cycles=3),
    degraded_mode=DegradedModeManager(sustained_threshold_sec=10.0),
)
budget = mgr.update(inputs)   # called once per publish cycle (2 Hz default)
```

Each call:
1. Runs `LoadSheddingController.update(...)` → `LoadSheddingDecision`.
2. Runs `DegradedModeManager.update(load_level, safety_fault_or_above)` →
   `DegradedModeStatus`.
3. Runs `ConfidencePolicyManager.recommend(degraded, safety_caution_or_above)`.
4. Runs `FrameSamplingManager.recommend(load_shed_scale)`.
5. Runs `ActivePersonFocusManager.compute_weights(focus_id, all_ids, new_ids)`.
6. Bundles all five outputs into one `PerceptionBudget`.

## Example

Resource pressure clears after a CPU spike: `LoadSheddingController` does
not snap back to `NORMAL` on the very next cycle — it requires
`hysteresis_cycles` (default 3) consecutive cycles of measured recovery
first, so a borderline CPU reading flapping at the threshold doesn't cause
the recommended sample rate to oscillate every cycle.

## Tests

6 dedicated tests in `tests/test_perception_budget_manager.py`, covering the
orchestrator's combination logic; each of the nine owned classes has its own
focused unit suite (70 tests total package-wide). See
[OPTIMIZATION_TESTING.md](OPTIMIZATION_TESTING.md).

## Performance

p95 = 0.014 ms per `update()` cycle against a budget of 50 ms (~3500x
headroom) — see [PERFORMANCE_METRICS.md](PERFORMANCE_METRICS.md) for the
full benchmark table.

## Troubleshooting

- **Load level never leaves `normal` even under real CPU pressure** — check
  `/bonbon/system/resource_usage` is actually being published;
  `resource_unavailable=True` is the safe default and intentionally never
  sheds load on missing data (so a stopped `bonbon_safety` node doesn't
  spuriously degrade the rest of the system).
- **`current_focus_person_track_id` is empty** — this is computed by calling
  `bonbon_behavior_engine`'s `select_focus_person()` against cached
  `HumanState` messages; empty means no `HumanState` has been received yet,
  not a bug in this package.
