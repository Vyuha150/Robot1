# Data License and Privacy Report

## License enforcement (rules 1, 2, 5)

`bonbon_data_pipeline.dataset_license_checker.DatasetLicenseChecker` is the single gate every training run and every `dataset_downloader.py` call must pass through. Fail-closed by construction:

| Rule | Enforcement | Verified by |
|---|---|---|
| 1. No unlicensed datasets | `license` empty/"unknown"/"none"/"n/a" always blocks, regardless of registry `status` | `test_license_checker.py::TestRequiredBehavior1UnknownLicenseBlocks` (3 tests) |
| 2. Every dataset must have a checked license | `status == NEEDS_REVIEW` blocks without `explicit_approval`; `commercial_allowed == "unknown"` always blocks | `test_license_checker.py::TestRequiredBehavior2CommercialDisallowedBlocksProduction` (4 tests, including the real `public_gesture_dataset_jester` fixture) |
| 5. No safety decisions from unverified AI data | `navigation` capability requires an explicit `safety_verified=True` flag on top of ordinary license checks, for **production training** specifically | `test_license_checker.py::TestRule5SafetyVerification` (3 tests) |

This does not touch or weaken `bonbon_ai_model_registry.LicenseChecker` (the equivalent gate for deployed model artifacts, already in production) or `bonbon_sarvam_adapter.sarvam_capability_detector` (the real official-access check for Sarvam) — `DatasetLicenseChecker` is a new, separate gate for a new concern (source training data), reusing the same fail-closed philosophy.

## Privacy enforcement (rules 3, 4)

`bonbon_data_pipeline.privacy_guard.PrivacyGuard` + `config/data/privacy_policy.yaml`:

- **Rule 3 (raw storage off by default):** `PrivacyPolicy()`'s three raw-storage flags (`raw_face_storage_enabled`, `raw_audio_storage_enabled`, `raw_video_storage_enabled`) default to `False`, and a missing/unreadable policy file fails closed to the same defaults — never fails open. `PrivacyGuard.check_dataset()` blocks any dataset whose `privacy_risk` names a raw-media category unless the matching flag is explicitly enabled. Verified: `test_privacy_guard.py::TestRequiredBehavior3RawStorageDisabledByDefault` (5 tests).
- **Rule 4 (consent required for face enrollment):** `PrivacyGuard.enroll_face()` raises `ConsentRequiredError` — never returns a boolean a caller could ignore — unless given a `ConsentRecord` that matches the subject, is unrevoked, and covers the `face_recognition_enrollment` scope. `face_enrollment_requires_consent` is a **fixed class attribute**, not read from any YAML, so no config edit can silently disable it. Verified: `test_privacy_guard.py::TestRequiredBehavior4ConsentRequiredForFaceEnrollment` (6 tests).

This is a distinct layer from two existing privacy mechanisms, deliberately not merged with either:

- `bonbon_field_learning.anonymized_event_store` — enforces privacy on the **runtime field-failure event log** (structurally: `AnonymizedEvent` has no raw-media fields at all).
- `bonbon_data_feedback.core.privacy_safe_data_policy.PrivacySafeDataPolicy` — the same enforcement for the robot's own live ROS2 failure capture.
- `bonbon_vision.face.privacy_guard.PrivacyGuard` — a same-named but unrelated module: live-stream face **anonymization** (blur/pixelate) on the annotated camera feed, not dataset governance. Confirmed zero overlap; the name collision is coincidental and both are correctly scoped to their own layer.

`bonbon_data_pipeline.privacy_guard` is the missing **dataset-intake-time** layer: is this specific training corpus (which may legitimately BE raw face/audio/video, e.g. a Common Voice download) allowed to be stored raw, and was a specific staff face enrollment actually consented to.

## Current honest state

No deployment site has any raw-storage flag enabled today, and BonBon does not yet implement face-recognition identity matching (only detection/tracking/emotion) — so `bonbon_staff_face_enrollment`'s consent gate currently has zero real enrollments to protect. This is stated plainly in `dataset_registry.yaml`'s entry notes, not glossed over.
