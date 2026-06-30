# Privacy-Safe Data Collection

Package: [`bonbon_data_feedback`](../ros2_ws/src/bonbon_data_feedback/README.md) ·
Module: [`core/privacy_safe_data_policy.py`](../ros2_ws/src/bonbon_data_feedback/bonbon_data_feedback/core/privacy_safe_data_policy.py)

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
