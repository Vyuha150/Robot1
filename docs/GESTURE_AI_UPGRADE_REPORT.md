# Gesture AI Upgrade Report

Phase 3(F)/14. Covers `gesture_recognition`/`pose_estimation` registry
entries and rule 6 ("do not use the LLM for gesture recognition").

## Selected model: MediaPipe Holistic (`gesture_mediapipe_holistic`)

- Runtime: `mediapipe`, license Apache-2.0, `hardware_target: pi_cpu` —
  open-source, CPU-viable, no gated access.
- Fallback chain: `gesture_mediapipe_holistic → gesture_mock` (terminal).
- `gesture_hailo_pose` registered separately as a Hailo-accelerated
  alternative for `pose_estimation`, not yet the default (no confirmed
  Hailo hardware active on any real Pi in this deployment as of this
  pass — see `docs/PERCEPTION_AI_UPGRADE_REPORT.md`'s Hailo bug fix).

## Rule 6 — structurally enforced, not just documented

`tests/gesture_ai/test_mediapipe_gesture_router.py::test_no_gesture_or_pose_entry_uses_an_llm_runtime`
iterates every registered `gesture_recognition`/`pose_estimation` entry
and asserts none uses the `ollama_http` runtime string — this is a live
check against the real registry file, so a future edit that accidentally
routed gesture recognition through the LLM would fail CI immediately,
not just violate an unenforced convention.

## Downstream: gesture → emotion-state mapping is deterministic

`bonbon_affective_ai.fusion.emotion_fusion_engine._gesture_to_state()` is
a plain dict lookup (`stop_palm`/`fallen_posture` → `"urgent"`, `wave` →
`"engaged"`, etc.) — not an LLM call — keeping the safety-relevant
stop-gesture path deterministic end-to-end from camera frame to fused
human state. 4 tests in
`tests/gesture_ai/test_mediapipe_gesture_router.py::TestGestureToEmotionStateMappingIsDeterministic`.
`stop_palm` and `fallen_posture` both correctly map to `urgent` and (in
`EmotionFusionEngine.fuse()`) unconditionally override the weighted-vote
result and set `requires_operator_alert=True` — this override happens
*before* any face/voice/text weighting, so a stop gesture cannot be
diluted by a simultaneous "happy" face score.

## Status on this environment

No `mediapipe` package installed in this sandbox → `gesture_recognition`
selection correctly falls back toward `gesture_mock`. Not independently
re-verified in this doc since it follows the exact same selector logic
already tested end-to-end for ASR/TTS/vision — see
`docs/AI_MODEL_BENCHMARK_REPORT.md`'s vision_gesture_fps case (reports
`fail`: "vision invoker requires a real camera frame — not exercised by
this standalone script", the correct, honest result for a camera-
dependent case run without a camera).

## Verdict: **PASS** (selection, rule-6 enforcement, and downstream mapping are correct and tested) / **BLOCKED** (real gesture recognition requires MediaPipe installed + a real camera — OAK-D Lite per the BOM).
