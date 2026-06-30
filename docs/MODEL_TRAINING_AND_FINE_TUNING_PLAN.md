# Model Training and Fine-Tuning Plan

How a dataset (public, per `ONLINE_DATASET_STRATEGY.md`, or field-derived,
per `FIELD_LEARNING_LOOP.md`) actually becomes a model running on BonBon,
and how that model is allowed — or blocked — from shipping.

## Pipeline

```
1. Pretrain / acquire base model        <- public datasets (license-cleared)
        v
2. BonBon-environment fine-tune         <- site-captured, BonBon-specific data
        v
3. Evaluate against the regression catalog   <- bonbon_field_learning.model_evaluation_tracker
        v
4. deployment_allowed(candidate)?
        |
   NO ──+── YES
   |         v
 BLOCKED   5. Deploy + bump dataset_version_manager entry referencing
            the dataset(s)/checklist passes that produced this model
```

## Stage 1 — Pretrain / acquire

Use a public base model or dataset that has passed `DATASET_LICENSE_CHECKLIST.md`
for the target capability (object detection, ASR, pose/gesture, etc., per
`ONLINE_DATASET_STRATEGY.md`'s per-category table). This stage never touches
BonBon field data — it establishes a baseline that should already be
reasonable before any site-specific tuning.

## Stage 2 — BonBon-environment fine-tune

Fine-tune on data actually captured by BonBon robots: this robot's cameras,
this mic array, real deployment-site lighting/acoustics. This is where the
"final performance" half of the dataset strategy's headline rule happens.
Field-derived labeled examples (`bonbon_field_learning.annotation_exporter.AnnotationExporter.export()`)
feed directly into this stage — they are the fastest-improvement data per
the strategy doc, because they target a gap the model is known to actually
have, not a generic capability gap.

## Stage 3 — Evaluate against the regression catalog

Every candidate model is run against the full set of `tests/production/`
scenarios — both the original generated catalog (`tests/scenarios/generated_scenarios/`)
and, critically, the field-derived regression catalog
(`tests/scenarios/generated_scenarios/regression_scenarios.yaml`) that
`bonbon_field_learning.regression_test_generator` has accumulated. The
result is a `regression_pass_rate` recorded as an
`EvaluationRun(model_version, dataset_version, regression_pass_rate, ...)`.

```bash
python -m pytest tests/production -m "not hardware_gated" -q
# regression_pass_rate = passed / (passed + failed) restricted to
# tests/production/test_field_pilot_learning_scenarios.py's regression-
# catalog assertions, recorded via ModelEvaluationTracker.record(...)
```

## Stage 4 — Deployment gate

`bonbon_field_learning.model_evaluation_tracker.ModelEvaluationTracker.deployment_allowed(candidate)`
compares the candidate's `regression_pass_rate` against the most recently
recorded run. Any drop blocks deployment outright — this is the literal
"blocks deployment if regression worsens" requirement, and it composes
directly with `bonbon_behavior_validation.production_score`'s safety-gate
logic (Phase 7): a model can only ship once both gates pass.

```python
tracker = ModelEvaluationTracker(path)
allowed, reason = tracker.deployment_allowed(candidate_run)
if not allowed:
    raise SystemExit(reason)  # BLOCKED, with the exact pass-rate delta
tracker.record(candidate_run)  # only recorded once the deploy decision is made
```

## Stage 5 — Deploy + version

On a successful gate pass, `bonbon_field_learning.dataset_version_manager.DatasetVersionManager.bump(reason, new_examples_count)`
records which dataset version produced this model (referencing the
license-checklist-cleared public sources plus the count of newly
field-derived examples merged in since the last bump).

## What this plan deliberately does not do

- It does not auto-deploy. `deployment_allowed` returning `True` is a gate
  passing, not a trigger — an operator/CI pipeline still decides when to
  actually roll the model out, consistent with "do not make unsafe changes
  without tests" and "do not fake hardware PASS": a passing regression
  suite on a dev machine is not the same claim as a verified on-robot
  rollout, and this plan does not conflate the two.
- It does not retrain emotion models toward "more confident" outputs —
  per `ONLINE_DATASET_STRATEGY.md` category 6/7, emotion signals stay
  policy-uncertain regardless of training data quality.
