# Privacy-Safe Data Collection

Two independent, complementary layers enforce the same rule from different
parts of the system:

- **Live perception feedback** — [`bonbon_data_feedback`](../ros2_ws/src/bonbon_data_feedback/README.md)
  (module: [`core/privacy_safe_data_policy.py`](../ros2_ws/src/bonbon_data_feedback/bonbon_data_feedback/core/privacy_safe_data_policy.py)),
  documented below.
- **Field pilot failure capture** — [`bonbon_field_learning`](../bonbon_field_learning/)
  (the Phase 6 behavior-validation failure pipeline), documented in
  ["The field-learning layer"](#the-field-learning-layer-bonbon_field_learning)
  further down.

## The hard rule

**Raw face/audio is never stored by default.** This is enforced at the
lowest layer every other class in the package consults before persisting
anything — `PrivacySafeDataPolicy` — not as a convention callers are trusted
to follow.

## Two independent protections

### 1. Raw snapshot gating

```python
policy = PrivacySafeDataPolicy()                       # debug_mode_enabled=False (default)
policy.is_raw_snapshot_allowed()                        # -> False, always

policy = PrivacySafeDataPolicy(debug_mode_enabled=True)  # must be explicit
policy.is_raw_snapshot_allowed()                         # -> True
```

`debug_mode_enabled` is never inferred — it is a launch parameter
(`debug_mode_enabled` in
[`data_feedback_params.yaml`](../ros2_ws/src/bonbon_data_feedback/bonbon_data_feedback/config/data_feedback_params.yaml),
hardcoded to `false`) that must be deliberately overridden at launch time.
`FailureCaseLogger.log()` checks this before ever setting
`has_raw_snapshot=True`/storing `raw_snapshot_path` — when the policy
disallows it, a supplied path is silently dropped, not stored.

### 2. Context sanitization — unconditional, even in debug mode

```python
policy.sanitize_context({"face_embedding": [...], "frame_idx": 9})
# -> SanitizeResult(sanitized={"frame_idx": 9}, stripped_keys=["face_embedding"])
```

Forbidden keys (`face_embedding`, `face_image`, `audio_bytes`,
`audio_samples`, `raw_image`, `raw_audio`, `image_bytes`,
`voice_embedding`, `biometric_template`) are stripped **regardless of debug
mode**. This is deliberate defense-in-depth: debug mode controls whether a
*file-path reference* may be stored, never whether raw payload can ride
along in the general JSON context dict by a caller's mistake. A test
(`test_forbidden_keys_stripped_EVEN_in_debug_mode`) exists specifically to
catch a future regression of this property.

## Retention

| Category | Default retention |
|---|---|
| face | 30 days (shortest — most sensitive) |
| speaker, emotion | 60 days |
| object, gesture | 90 days |
| (unmapped) | 90 days |

Enforced by `DataFeedbackNode`'s hourly retention sweep calling
`FeedbackStore.delete_expired(category, cutoff)` — see
[DATA_STRATEGY.md](DATA_STRATEGY.md).

## What this does NOT cover

- `person_track_id` is stored (a session-scoped tracking reference, not a
  raw biometric) — this is a deliberate choice to allow grouping examples
  by person during review; it is not anonymized further.
- This policy governs `bonbon_data_feedback` only. It has no authority over
  what `bonbon_vision`/`bonbon_affective_ai` themselves do with frames in
  memory before any failure case is logged — those packages' own privacy
  guards (`PrivacyGuard` in `bonbon_vision`, `PrivacyGate` in
  `bonbon_affective_ai`) are unrelated, pre-existing, untouched mechanisms.

## Tests

13 dedicated tests in `test_privacy_safe_data_policy.py`, plus privacy
assertions embedded in `test_failure_case_logger.py` (4 tests) and Phase 6
scenarios 14–15 in
[`tests/scenarios/test_efficiency_and_feedback_scenarios.py`](../tests/scenarios/test_efficiency_and_feedback_scenarios.py).
See [OPTIMIZATION_TESTING.md](OPTIMIZATION_TESTING.md).

## Troubleshooting

- **A raw snapshot path I supplied isn't showing up in the database** — this
  is almost certainly correct behavior, not a bug: check
  `debug_mode_enabled` is actually `true` in the running node's parameters
  (`ros2 param get /bonbon/data_feedback/data_feedback_node debug_mode_enabled`).
- **`debug_mode_enabled` should never be `true` in a production deployment**
  — there is no override or exception path for this; if you need raw
  snapshots for debugging, set it explicitly for that session and turn it
  back off.

## The field-learning layer (`bonbon_field_learning`)

The Phase 6 behavior-validation failure pipeline (when an oracle-flagged
field failure gets logged, reviewed, and turned into a regression test —
see [FIELD_LEARNING_LOOP.md](FIELD_LEARNING_LOOP.md)) enforces the same
"no raw face/audio by default" rule, independently, at the type level:

- `bonbon_field_learning.anonymized_event_store.AnonymizedEvent` is a
  dataclass with fields `event_id`, `timestamp`, `family`,
  `failure_category`, `scenario_id`, `oracle_reason`, `metadata`
  (`dict[str, str]`) — there is no field that *can* hold an image or audio
  payload. This isn't a runtime check; the type cannot represent raw media.
- `AnonymizedEventStore.append()` additionally scans every `metadata` key
  against a denylist (`raw_face`, `raw_audio`, `face_image`,
  `audio_waveform`, `face_embedding`, `voiceprint`, `biometric_raw`) and
  raises `PrivacyViolationError` rather than silently dropping the
  offending key — the same defense-in-depth posture as
  `sanitize_context()` above, applied to this pipeline's own data shape.
- Raw snapshots can only reach disk through `bonbon_field_learning.failure_case_logger.DebugSnapshotStore`,
  a structurally separate store from `AnonymizedEventStore` that is only
  written when `debug_mode=True` **and** a snapshot path **and** a debug
  store instance are all explicitly supplied — the default
  `FailureCaseLogger(store)` (no debug store argument) makes raw capture
  impossible regardless of `debug_mode`.

Tested directly in `tests/unit/test_field_learning.py::TestPrivacyContract`
(5 tests: no raw-media fields on the type, smuggled-metadata rejection,
normal metadata accepted, debug-mode-on snapshot isolation, debug-mode-off
snapshot drop) and re-asserted per-scenario in
`tests/production/test_field_pilot_learning_scenarios.py`.

This layer and `bonbon_data_feedback`'s are independent on purpose — a bug
in one does not compromise the other, and the field-learning store has no
access to whatever live frames/audio `bonbon_vision`/`bonbon_affective_ai`
hold in memory at evaluation time. See `/privacy/data-collection-status`
(Phase 8) for the combined live status of both layers.
