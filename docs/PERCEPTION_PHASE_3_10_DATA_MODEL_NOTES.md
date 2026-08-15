# Perception Phase 3-10 Data/Model Improvement Notes

Phase 9 of the Perception AI Phase 3-10 pass. This is **not** a replacement
for [ONLINE_DATASET_STRATEGY.md](ONLINE_DATASET_STRATEGY.md), which already
covers object detection, person detection, and pose/gesture recognition in
full (public-dataset-vs-BonBon-data-vs-failure-case-data policy for each).
That document remains authoritative. This one records the specific new data
gaps this session's Phase 3-8 fixes surfaced, so they don't get lost between
the fix and the next real-hardware pass.

## 1. `pointing_at_object` fusion (Phase 5) needs real camera + object validation

`logic/object_pointing_fusion.py`'s angular-cone heuristic (default 25°
tolerance) was built and unit-tested purely in image-pixel-space geometry —
no real camera frame, no real MediaPipe pose output, and no real
`DetectedObjectArray` from a running YOLO/Hailo detector has ever been fed
through it together. The 7 tests in `test_object_pointing_fusion.py` prove
the geometry is internally consistent; they cannot prove 25° is the right
tolerance for a real arm-pointing gesture at real hospital-lobby distances.
**Required before relying on this in production:** a short real-camera
capture session (a person pointing at 5-10 known objects at varying
distances/angles) to tune `pointing_object_angle_tolerance_deg` and confirm
the elbow→wrist direction vector is a good proxy for actual gaze/intent at
this camera's FOV and mounting height.

## 2. `go_away` gesture is a static-pose proxy, not a validated motion detector

Per `GESTURE_RECOGNITION_FAILURE_ANALYSIS.md`, `_is_go_away()` is an
honestly-documented best-effort proxy (open hand, arm extended
sideways/forward, at or below shoulder height) standing in for what is
fundamentally a *motion*-based gesture (a dismissive wave/push-away
movement). No field data has validated the false-positive rate against,
e.g., a person simply resting their arm in that position. **Required:**
field-collected "go away" attempts + a matched set of superficially-similar
non-gesture poses, both run through the current proxy, to measure real
precision before this gesture is used for anything beyond an
informational/logged signal.

## 3. Emotion-fusion `uncertainty_conflict_margin` (Phase 4) is an untuned default

`EmotionUncertaintyHandler`'s default `conflict_margin=0.75` was chosen by
reasoning about the vote-weight math (see `emotion_fusion_engine.py`'s own
comments), not by measuring how often real face+voice+text combinations
actually disagree. Set too low, "uncertain" fires too rarely (overclaiming
confidence); set too high, it fires too often (useless hedging). **Required:**
a field dataset of labeled multi-modal disagreement cases (a person whose
face reads neutral but voice reads distressed, etc.) to tune this threshold
before it gates any behavior-engine response-style decision.

## 4. Hospital object-class taxonomy still has no trained detector

Unchanged from `PERCEPTION_AI_UPGRADE_REPORT.md`: `hospital_class_registry.py`'s
6 hospital-specific classes (wheelchair, stretcher, iv_stand, hospital_bed,
walker, crutches) are a target allowlist only — no model in this codebase
has ever been trained or fine-tuned to actually recognize them. This
session's Phase 3-8 work did not change that. Per
[ONLINE_DATASET_STRATEGY.md](ONLINE_DATASET_STRATEGY.md) item 1's rule,
site-specific object classes require BonBon-captured fine-tuning data
regardless of what public detector backbone is used.

## 5. `pi_efficiency_profile` FPS caps' accuracy impact is unmeasured (Phase 7)

Wiring `fps_limits.object_detection` (8 FPS) and `fps_limits.face_emotion`
(1 FPS) into `bonbon_vision`/`bonbon_affective_ai` as an additional ceiling
(this session, Phase 7) changes real-world detection/tracking latency and
miss rate on a loaded Pi -- nothing in this dev sandbox can measure that,
since there is no real camera or Pi CPU load profile here. **Required:** a
real-Pi run comparing detection continuity (ID-switch rate, missed-frame
rate) with the cap enabled vs. disabled, using
`bonbon_multi_person_tracker`'s existing ID-switch metric
(`docs/EFFICIENCY_COMPLIANCE_REPORT.md`'s check 9) as the measurement.

## Not new: what's already correctly handled

- Voice/face emotion as an always-uncertain signal (never a standalone
  behavior trigger) — governed by
  [ONLINE_DATASET_STRATEGY.md](ONLINE_DATASET_STRATEGY.md) items 6-7 and
  the Behavior Oracle's `low_confidence_handling` check; this session's
  `uncertain` state addition (item 3 above) is additive to that policy, not
  a change to it.
- Field-failure-to-regression-test loop (`FIELD_LEARNING_LOOP.md`) already
  exists and applies to every gap above once real field data is collected —
  no new infrastructure is needed, only the data-collection sessions
  themselves.
