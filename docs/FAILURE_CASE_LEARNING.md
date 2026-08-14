# Failure Case Learning

Package: [`bonbon_data_feedback`](../ros2_ws/src/bonbon_data_feedback/README.md)

## Purpose

The workflow a human reviewer or ML engineer actually follows to turn
logged model failures into a retraining signal — what each class in the
package is for, in the order you'd use them.

## Step 1 — A failure case gets logged

Two paths land in the same `failure_cases` table (see
[DATA_STRATEGY.md](DATA_STRATEGY.md) for why there are exactly two):

```python
# Automatic — gesture confidence below the live recommended floor
logger.log(category="gesture", signal_name="gesture_below_confidence_floor",
           actual_label="point", confidence=0.4, person_track_id="ptrk_3")

# Explicit — any node, via the ReportFailureCase service
ros2 service call /bonbon/data_feedback/data_feedback_node/report_failure_case \
  bonbon_srvs/srv/ReportFailureCase "{category: 'object', ...}"
```

## Step 2 — Is it a hard negative?

`HardNegativeCollector.is_hard_negative(confidence, was_correct)` is `True`
only when the model was *confident* (≥ `confidence_threshold`, default 0.7)
*and wrong*. An honest low-confidence miss is a normal failure case, not a
hard negative — the distinction matters because hard negatives are the
highest-value examples for retraining (the model was sure, and shouldn't
have been).

```python
collector.collect(category="gesture", signal_name="wave_detector",
                   actual_label="wave", confidence=0.95, was_correct=False)
# -> persisted with is_hard_negative=True
```

## Step 3 — Human review

A reviewer calls `FeedbackStore.mark_reviewed(case_id, review_label)` with
the correct label. `DatasetVersionManager.create_version()` defaults to
`reviewed_only=True`, so unreviewed cases are excluded from a dataset export
by default — review is a deliberate gate, not a courtesy.

## Step 4 — Export and version

```python
version_id = version_manager.create_version(
    name="gesture_dataset_v3", category="gesture", reviewed_only=True,
)
```

This writes a JSONL export (`AnnotationExportManager`) and records a named,
immutable `dataset_versions` row pointing at it — `case_count`,
`export_path`, `created_at` are all captured so a training run references
something stable and reproducible, not a moving query result.

## Step 5 — Train, evaluate, compare

`ModelEvaluationStore` is independent of the dataset-versioning flow above —
it records the *result* of training/evaluating a model version:

```python
eval_store.record_evaluation("gesture_classifier", "v3", "gesture",
                              sample_count=500, accuracy=0.91)
cmp = eval_store.compare("gesture_classifier", "v2", "v3")
# cmp.improved -> True/False/None (None if either version has no recorded eval)
```

See [PERFORMANCE_METRICS.md](PERFORMANCE_METRICS.md) for the model
comparison report template built from this.

## Example end-to-end

A gesture is detected as "point" at 0.95 confidence but a reviewer later
confirms it was actually "wave": logged automatically isn't possible here
(0.95 is above the confidence floor, so nothing auto-triggers) — this is a
case for the explicit `~/report_failure_case` path with `was_correct=False`,
which `HardNegativeCollector` classifies as a hard negative given the
confidence is ≥ 0.7. A reviewer marks it reviewed with `review_label="wave"`.
The next `gesture_dataset_vN` export includes it.

## Per-site and per-language capture (continuous-improvement audit fix)

Before this fix, `failure_cases` had no `site_id` or `language_code`
column at all — for a robot deployed across multiple hospital sites in
India with different dominant regional languages, there was no way to
query "which site has the worst gesture-recognition rate" or "does ASR
fail more often on code-mixed Hindi-English speech than pure English."

- **`site_id`** is a deployment-time node parameter
  (`data_feedback_node`'s `site_id` param, `""` default — set per real
  hospital at launch, e.g. `site_id:=hospital_pune_01`), stamped onto
  every failure case automatically by the node itself. It is never
  supplied per-call, matching the config-not-per-message pattern other
  packages use for deployment identity (e.g.
  `bonbon_distributed_network_monitor`'s `pi_role`).
- **`language_code`** is caller-supplied on `ReportFailureCase.srv`
  (new field, `""` default) — the node has no ASR/speech subscription of
  its own and does no language detection itself; it only persists
  whatever the calling node already knows.
- `FeedbackStore.query_failure_cases()` gained `site_id`/`language_code`
  filter parameters for exactly this analysis.
- Added as migration v2 (`ALTER TABLE ... ADD COLUMN`, both `NOT NULL
  DEFAULT ''`) — existing rows get an honest empty value, not a
  fabricated guess; forward-only, matches this repo's only other
  migration precedent (`bonbon_data_stores`).

**Deliberately NOT done in this round:** wiring `language_code` from a
real detector. `bonbon_speech_ai`'s `language_detector.py` computes
`language_code`/`is_code_mixed` per utterance (see
[SPEECH_AI_UPGRADE_REPORT.md](SPEECH_AI_UPGRADE_REPORT.md)), but no node
anywhere calls `~/report_failure_case` at all yet — not for ASR
low-confidence, not for `intent_engine`'s `is_ambiguous`/
`fallback_response`, not for `bonbon_llm`'s `safety_block`/
`hallucination` events. The `report_failure_case` service has existed
since this package's original build with zero external callers
(confirmed by repo-wide grep). Wiring those callers is a larger,
cross-package decision (which failure signals are worth the write
volume, whether every one needs human review) left for a dedicated task
rather than added silently here — the `language_code` field exists now
specifically so that future wiring doesn't require another schema
migration.

## Tests

74 tests across the package (was 62 before the site_id/language_code fix
above) — `failure_case_logger.py` and `hard_negative_collector.py`
specifically have 8 + 8 tests covering the classification boundary,
privacy gating, and the site_id/language_code fix. See
[OPTIMIZATION_TESTING.md](OPTIMIZATION_TESTING.md).

## Troubleshooting

- **A confident-but-wrong case isn't showing up as a hard negative** — check
  `was_correct` was actually passed `False`; `HardNegativeCollector.collect()`
  silently returns `None` (does not persist anything) when the confidence/
  correctness combination doesn't meet the bar — this is intentional (see
  [DATA_STRATEGY.md](DATA_STRATEGY.md)), not a bug.
