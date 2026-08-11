# Affective AI Upgrade Report

Phase 8/14. Covers face emotion, voice emotion, speaker diarization
registry entries and `bonbon_affective_ai.fusion.emotion_fusion_engine`'s
per-person fusion.

## GAP-1 fix (new finding this pass, high priority)

`bonbon_affective_ai`'s code already defaulted to **DeepFace** (face
emotion) and **SpeechBrain** (voice emotion) at the Python-import level,
but neither package was listed in `requirements/pi2_requirements.txt` —
meaning a real Pi install would have silently fallen back to the mock
backends despite the code intending otherwise. Found during this pass's
audit (not previously known anywhere in the session). Fixed in both
places together:

- `requirements/pi2_requirements.txt` — added `deepface` and
  `speechbrain` under a new "Affective AI (bonbon_affective_ai)" section
  with an explanatory comment.
- `config/models/model_registry.yaml` — flipped
  `emotion_face_deepface`/`voice_emotion_speechbrain` to
  `enabled_by_default: true` and `emotion_face_mock`/
  `voice_emotion_text_sentiment` to `false`, so the registry's declared
  default now matches the code's actual runtime default.

This produced a follow-on validation conflict: `offline_open_source_
profile.yaml` had its own overrides re-forcing the mock backends as
default, which — after the base registry change — created a "two
enabled_by_default entries for capability X" validation error. Fixed by
removing those two override lines (DeepFace/SpeechBrain are genuinely
open-source with no commercial/gated/cloud dependency, so an "offline
open source" profile has no license reason to force them down). All 5
hardware profiles re-validated clean —
`tests/ai_models/test_model_registry.py::TestApplyProfileOverrides::test_all_five_hardware_profiles_validate_clean`.

Regression-covered in
`tests/affective_ai/test_per_person_emotion_fusion.py::TestRegistryEnablesRealBackendsNotMockByDefault`
(4 tests: registry defaults, requirements-file presence, and the rule-6
LLM-runtime check applied to face/voice emotion too).

## Per-person fusion (rule: independent state per human, 12 named states)

`EmotionFusionEngine` maintains per-`person_id` state (`_state_history`,
`_previous_state`, `_state_change_count`, `_state_change_window`) — two
different people's face/voice/text/gesture signals compute genuinely
independent `dominant_state`/`confidence`/stability results, verified in
`tests/affective_ai/test_per_person_emotion_fusion.py::TestPerPersonFusionIsIndependentAcrossPeople`.
The 12 states (`neutral`, `happy`, `confused`, `frustrated`, `angry`,
`distressed`, `fearful`, `urgent`, `tired`, `engaged`, `disengaged`, plus
the emergency-override path) each map to a `recommended_response_style`,
`recommended_distance_m`, `suggested_tts_emotion`, and
`interaction_patience_multiplier` — pre-existing, verified not rebuilt.

**Uncertainty rule enforced**: a `privacy_suppressed` face signal or a
`model_failed` voice signal is fully excluded from the weighted vote
(zero contribution, not a low-confidence guess) —
`TestWeightedVotingAcrossModalities::test_privacy_suppressed_face_is_excluded_from_voting`
/ `test_failed_voice_model_is_excluded_from_voting`. With zero usable
modalities, the engine returns `("neutral", 0.0)` rather than fabricating
a confident state.

**Emergency override is unconditional**: a `fallen_posture`/`stop_palm`
gesture or `text.emergency_detected` forces `dominant_state="urgent"`,
`dominant_confidence=1.0`, `requires_operator_alert=True` — bypassing the
weighted vote entirely, so a simultaneous "happy" face score can never
dilute a genuine emergency signal.

## Speaker diarization

Default remains the lightweight `diarization_active_speaker_approx`
(mock), not `diarization_pyannote` — pyannote requires accepting
per-model Hugging Face terms and a personal access token, with
commercial-use terms historically restrictive without a paid HF plan.
Registering it available-but-not-default is the direct enforcement of
rule 3.

## Status: `fuse()` itself is ROS2-message-gated, not code-gated

`EmotionFusionEngine.fuse()` constructs a real
`bonbon_msgs.msg.HumanEmotionState` — a rosidl-generated message class
that requires a colcon-built, sourced ROS2 workspace, not plain-
importable Python. Per rule 10, the one test that calls `fuse()` directly
(`TestFuseProducesARealMessage::test_fuse_emergency_gesture_overrides_to_urgent`)
is marked `rclpy_gated` and SKIPs honestly in this sandbox rather than
faking a pass. Every private helper `fuse()` calls (`_compute_weighted_state`,
`_contribution_scores`, `_gesture_to_state`) is pure Python with no ROS2
dependency and is fully exercised directly — this is what actually
determines fusion correctness; `fuse()` only wraps the result in a
message envelope.

## Verdict: **PASS** (GAP-1 fixed, per-person fusion logic verified correct) / **BLOCKED** (real DeepFace/SpeechBrain inference and the full `fuse()` message path require a sourced ROS2 workspace + real Pi-2 camera/mic, neither available in this sandbox).
