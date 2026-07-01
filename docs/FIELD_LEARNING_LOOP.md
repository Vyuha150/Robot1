# Field Learning Loop

How a real (or, today, simulated) field failure becomes a permanent
regression test, without ever storing raw face/audio by default.

## The loop

```
1. Behavior Oracle FAIL                bonbon_behavior_validation.BehaviorOracle
        v
2. FailureCaseLogger.log_verdict()     one AnonymizedEvent per failed check
        v                              (anonymized_event_store.AnonymizedEvent --
        |                               no raw-media fields exist on the type)
        +-- debug_mode=True? --> DebugSnapshotStore (separate store, pointer only)
        v
3. HumanReviewQueue.enqueue()          PENDING
        v
   a human labels the correct expected outcome
        v
   submit_review(approve=True, corrected_expected_outcome={...})  -> APPROVED
        v
4. AnnotationExporter.export()         labeled JSONL for model training/fine-tuning
        v
5. RegressionTestGenerator.generate()  appends a new Scenario to
                                        generated_scenarios/regression_scenarios.yaml
        v
6. tests/production/test_field_pilot_learning_scenarios.py
        ::test_existing_regression_catalog_still_passes_the_oracle
        -- asserted on EVERY future test run
        v
7. dataset_version_manager.bump()      version history entry
        v
8. model_evaluation_tracker.record(EvaluationRun(...))
        v
9. deployment_allowed(candidate)       blocks deployment if regression_pass_rate
                                        dropped vs. the last recorded run
```

## Privacy, precisely

`AnonymizedEvent`'s fields are `event_id, timestamp, family,
failure_category, scenario_id, oracle_reason, metadata`. There is no field
that can hold an image or waveform — this isn't a runtime check, the type
cannot represent raw media. `AnonymizedEventStore.append()` additionally
rejects any `metadata` key matching a biometric-data denylist
(`raw_face`, `raw_audio`, `face_image`, `audio_waveform`,
`face_embedding`, `voiceprint`, `biometric_raw`), raising
`PrivacyViolationError` rather than silently dropping just that field.

Raw snapshots can *only* reach disk through `DebugSnapshotStore` — a
structurally separate store. `FailureCaseLogger.log_verdict()` only writes
to it when `debug_mode=True` **and** a snapshot path **and** a configured
`DebugSnapshotStore` are all present; the default
`FailureCaseLogger(store)` (no debug store argument) makes raw capture
impossible regardless of what `debug_mode` is passed. Full detail and the
exact tests that assert this in
[PRIVACY_SAFE_DATA_COLLECTION.md](PRIVACY_SAFE_DATA_COLLECTION.md).

## The 12 failure categories

`wrong_object`, `missed_object`, `wrong_gesture`, `missed_gesture`,
`wrong_speaker`, `wrong_person_identity`, `wrong_emotion`,
`wrong_response`, `unsafe_proposal_blocked`, `navigation_failure`,
`dashboard_mismatch`, `degraded_mode_failure` — the
`FailureCategory` StrEnum in `anonymized_event_store.py`. Each failed
oracle check maps to one of these via
`failure_case_logger.category_for_check()`, so the categorization is
automatic, not a human judgment call at logging time (the human's
judgment is reserved for the *review* step, where it matters).

## Review and regression generation

A `ReviewItem` starts `PENDING`. A human reviewer calls
`HumanReviewQueue.submit_review(event_id, reviewer, approve, corrected_expected_outcome)`.
Only `APPROVED` items are eligible for export
(`AnnotationExporter.approved_examples()`); `RegressionTestGenerator.generate()`
explicitly refuses to generate a test from anything not `APPROVED`
(`ValueError`). The generated `Scenario`'s `expected_behavior`,
`required_safety_response`, etc. come from the reviewer's
`corrected_expected_outcome` dict when supplied, falling back to a
generic-but-still-specific default built from the original
`oracle_reason` otherwise — so a regression scenario is never blank.

Scenario IDs follow `BB-REG-<FAILURE_CATEGORY>-<NNNN>`, distinct from the
generator's `BB-<FAMILY_CODE>-...` scheme so a regression-derived scenario
is recognizable at a glance.

## The deployment gate

`ModelEvaluationTracker.deployment_allowed(candidate)` compares
`candidate.regression_pass_rate` against the most recently *recorded* run
(not the candidate itself — recording only happens after a deploy
decision, so a rejected candidate's score stays visible for debugging
without becoming the new baseline). Any drop blocks deployment outright —
the literal "blocks deployment if regression worsens" requirement. This
composes with `bonbon_behavior_validation.production_score`'s safety gate
(see [PRODUCTION_READINESS_SCORING.md](PRODUCTION_READINESS_SCORING.md)):
a model needs both gates to pass.

## Tested

18 unit tests (`tests/unit/test_field_learning.py`) cover the privacy
contract directly, plus the full enqueue→approve→export→generate→version
pipeline and both deployment-gate outcomes (allowed / blocked). The 15th
production scenario file
(`tests/production/test_field_pilot_learning_scenarios.py`) drives the
real loop end-to-end and re-asserts the entire accumulated regression
catalog passes the oracle on every run.

## Commands

```bash
# run only the field-learning loop's own tests
python -m pytest tests/unit/test_field_learning.py tests/production/test_field_pilot_learning_scenarios.py -q

# see the live regression catalog (count + IDs) the dashboard reads
curl -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/field-learning/regression-tests
```
