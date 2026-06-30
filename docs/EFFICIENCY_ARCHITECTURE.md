# Efficiency Architecture

Package: [`bonbon_perception_efficiency`](../ros2_ws/src/bonbon_perception_efficiency/README.md)

## Purpose

A 2026-06-30 efficiency audit found that confidence thresholds, frame
sampling, and stale-frame handling were configured independently per
perception package with zero coordination; that `bonbon_safety`'s
`ResourceMonitor` (CPU/memory/disk sampling) was fully implemented but never
wired to a topic; and that nothing reduced processing for background people
while prioritising the active speaker/focus person. This document covers the
architecture built to close those gaps without touching any working module.

## Guiding rules (from the brief, honored throughout)

- No redundant camera or microphone pipeline.
- No bypass of the Safety Supervisor — `bonbon_perception_efficiency` only
  *observes* `/bonbon/safety/state`, never gates or overrides it.
- No LLM control of movement/actuation — out of this package's scope entirely;
  unaffected.
- No duplicate database access — `bonbon_data_feedback` reuses
  `bonbon_data_stores`' `SQLiteConnection`/`SchemaMigrator` rather than a
  second ad-hoc layer (see [DATA_STRATEGY.md](DATA_STRATEGY.md)).
- No working module replaced — `bonbon_perception` was quarantined (renamed
  launch file, disabled entry points, README explaining why), not deleted;
  every fix to an existing node was an additive wrap around code already
  there (see [OPTIMIZATION_TESTING.md](OPTIMIZATION_TESTING.md)).

## Architecture

```
bonbon_safety (ResourceUsage, SafetyState)  ─┐
bonbon_multi_person_tracker (PersonTrack)    ─┤
bonbon_human_state_fusion (HumanState)       ─┼──► PerceptionBudgetManager
every perception node (ModuleHealth)         ─┘         │
                                                          ▼
                                    /bonbon/perception_efficiency/{policy,budget,
                                                          degraded_mode,metrics}
                                                          │
                                          (advisory only — consumed by nodes
                                           that choose to read it; see below)
```

`PerceptionBudgetManager` is the single per-cycle orchestrator. It owns one
instance of each of the other nine classes and combines their output into a
`PerceptionBudget` every cycle — see
[PERCEPTION_BUDGET_MANAGER.md](PERCEPTION_BUDGET_MANAGER.md) for the class
breakdown.

## Advisory, never command

No existing node exposes a live-reconfigure RPC, so this package cannot force
anything — it can only publish a recommendation and let a node choose to
read it. Two real consumers exist today, both additive, both verified not to
change behavior when the efficiency node isn't running:

| Consumer | What it reads | What changes |
|---|---|---|
| `bonbon_affective_ai` | nothing from this package directly — wraps its own `ThreadPoolExecutor.submit()` calls with a `BoundedInferenceQueue` it owns | Voice/text analysis requests are admission-controlled instead of queuing unbounded under load. |
| `bonbon_vision` | `/bonbon/perception_efficiency/budget`'s `sample_consumers`/`sample_every_n_frames` | `FrameThrottler.set_rate()` (an existing, documented, runtime-tunable method) is fed the recommended rate when present; falls back to its static configured rate otherwise. |

Every other recommendation (`ConfidencePolicyManager`, `ActivePersonFocusManager`,
`TemporalSmoothingManager`) is published but not yet consumed by a node — see
the "Honest limitations" section of the package README. They're built,
tested, and ready; wiring a specific node to apply one is future work, not
overclaimed here.

## What was deliberately NOT built

- **ROI-based processing** — would require deep changes to `bonbon_vision`'s
  detection pipeline; judged too high-risk for an adapter-only mandate on a
  safety-relevant module.
- **Full async restructuring of `vision_node._detection_cycle`** — it already
  has a working, tested degraded-mode/timeout-guard pattern inside
  `BaseDetector` (see below); rebuilding its threading model from scratch
  would be exactly the kind of risky surgery the brief says to avoid.
- **Replacing `affective_ai_node`'s own face-analysis dispatch** — only the
  two call sites the audit actually found unguarded (`_cb_audio`,
  `_cb_transcript`) were wrapped; `_run_face_analysis_for_person` was found
  to be dead code (defined, never called) and was left untouched — deleting
  unrelated dead code is out of scope for this work.

## What already existed and was correctly NOT duplicated

Checked before building anything new, per the brief's "do not duplicate"
rule:

| Capability | Already exists in |
|---|---|
| Model timeout guard + degraded-mode fallback | `bonbon_vision.detectors.base_detector.BaseDetector` |
| Model warmup | `bonbon_affective_ai`'s `_warmup_backends()`, `bonbon_vision`'s `ModelManager` |
| Lightweight fallback model | `bonbon_vision`'s `MockDetector`, used automatically when the configured backend fails |
| Batched database writes | Built fresh in `bonbon_data_feedback.FeedbackStore.insert_failure_cases_batch` — no prior repository in the project supported batching |

## Tests

70 unit tests across 9 core classes (`bonbon_perception_efficiency/tests/`).
See [OPTIMIZATION_TESTING.md](OPTIMIZATION_TESTING.md) for the full test
inventory across every phase.

## Performance

Every core class is bounded dict/list arithmetic over a small number of
tracked people/modules — no ML inference. Benchmarked at p95 = 0.014 ms for
a full `PerceptionBudgetManager.update()` cycle (budget: 50 ms, ~3500x
headroom). See [PERFORMANCE_METRICS.md](PERFORMANCE_METRICS.md).
