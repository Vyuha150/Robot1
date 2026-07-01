# Perception AI Current Audit

**Date:** 2026-07-01. Read-only investigation (no code changed by this
document). Findings below are cited to exact file:line where possible;
every "N tests pass" figure was independently re-run, not assumed.

**Headline finding, before the detail:** BonBon's perception stack is
**considerably more mature than the bug reports imply**. Multi-person
tracking, speaker↔person linkage, per-person face emotion, per-person
gesture assignment, and human-state fusion are all real, tested, and
wired end-to-end. The actual defects are narrower and more specific than
"emotion recognition is global" or "gesture recognition doesn't work" —
see the three failure-analysis docs for the precise, confirmed root
causes. This audit is the evidence base those docs draw from.

## 1-8. Object detection

| # | Item | Finding |
|---|---|---|
| 1 | Object detection implementation | `bonbon_object_intelligence`'s `ObjectIntelligenceNode` (`nodes/object_intelligence_node.py:72`) is a **post-processing consumer**, not a detector — it does not run inference. The actual detector is `bonbon_vision`'s `YoloDetector` (`bonbon_vision/detectors/yolo_detector.py`), which calls `ultralytics.YOLO` **directly** (yolo_detector.py:46-90), independent of `bonbon_ai_runtime`. |
| 2 | Object class list | No custom class registry anywhere. Classes come entirely from YOLO's built-in COCO label set (80 classes, `base_detector.py:50-131`). `vision_params.yaml`'s `detector.classes: []` only *filters* which COCO indices are reported — it cannot add classes the base model doesn't have. |
| 3 | Model runtime selection | `vision_params.yaml`'s `detector.backend: "mock"\|"yolo"` selects between `MockDetector` and `YoloDetector` — a **different, older abstraction** than `bonbon_ai_runtime.RuntimeSelector`. |
| 4 | Hailo runtime integration | **Not present in the live pipeline.** Grep for "RuntimeSelector"/"bonbon_ai_runtime" across `bonbon_vision` returns zero hits. `bonbon_ai_runtime` is only imported by `bonbon_operator_api` (diagnostics) and its own tests. |
| 5 | CPU fallback | YOLO runs on CPU by default via ultralytics' own device selection; there is no explicit Hailo→CPU fallback chain because Hailo was never in the chain to begin with. |
| 6 | Object tracking | Two independent trackers exist: bonbon_vision's lightweight `_SimpleTracker` (per-frame IoU-based `track_id`) and `bonbon_object_intelligence`'s `ObjectPermanenceTracker` (`object_permanence_tracker.py:90-250`, 4-state FSM: VISIBLE→OCCLUDED→MEMORY→LOST, nearest-position-within-class matching). |
| 7 | Object confidence thresholds | `ObjectConfidenceCalibrator` (`confidence_calibrator.py:55-74`): configurable `rejection_threshold` (default 0.3), small-object confidence floor (0.35 below 900px²). Separately, `vision_params.yaml`'s `detector.confidence_threshold: 0.45` gates YOLO itself — **two independent, differently-valued thresholds** in the pipeline. |
| 8 | Object dashboard status | Only a `ModuleHealth` topic (`/bonbon/objects/object_intelligence_node/health`, 1 Hz) — no active-detections, class-count, latency/FPS, or fallback-reason topic. No dashboard REST endpoint or WebSocket channel exists for objects at all. |

**Tests:** `bonbon_object_intelligence` 36/36 pass (calibrator, permanence FSM, depth fallback, memory, OCR eligibility).

## 9-13. Multi-person tracking

| # | Item | Finding |
|---|---|---|
| 9 | Multi-person tracking implementation | `bonbon_multi_person_tracker`'s `MultiPersonTrackerNode`, fully implemented and tested. |
| 10 | `person_track_id` generation | Stable UUID (`ptrk_<12-hex>`), never reused within a session (`temporary_id_allocator.py:9-24`). |
| 11 | Face crop association | Present via `PersonTrack.known_person_id`/`face_bbox` fields (`person_record.py:52,86-88`); implicit association, not a separate linking message. |
| 12 | Known/unknown identity handling | `IdentityAssociator` priority chain: face_id → body_embedding_id → spatial_proximity (`identity_associator.py:71-87`); spatial-only matching is **deliberately excluded** from the churn-merge pass specifically to avoid merging two close-together distinct people (`identity_associator.py:15`, tested at `test_multi_person_scene_manager.py:75-92`). Body re-ID backend itself is a placeholder (interface exists, no real embedding model). |
| 13 | Person arrival/leaving lifecycle | All 6 required states implemented: `new_candidate`, `present`, `active_interaction`, `temporarily_lost`, `reappeared`, `left_scene` (`lifecycle_state_machine.py:38-44`). Grace period before declaring departure: `loss_grace_sec: 4.0` (never instant deletion, `lifecycle_state_machine.py:215-232`). |

**Tests:** `bonbon_multi_person_tracker` 53/53 pass; `bonbon_speaker_intelligence` 43/43 pass (DOA-to-person-bearing association, `audio_visual_associator.py:40-71`; `SpeakerTurn.person_track_id` populated, `""` when off-camera).

## 14-19. Emotion recognition

| # | Item | Finding |
|---|---|---|
| 14 | Face emotion recognition | DeepFace backend (configurable, `affective_config.py:18`); consumes face crops **already tagged with `person_id`/`tracking_id`** (`face_emotion_analyzer.py:62-106`); rate-limited to 1 sample per 0.5s **per person** (`affective_config.py:21`) — not every face every frame. |
| 15 | Voice emotion recognition | SpeechBrain backend; **CONFIRMED BUG**: audio is buffered globally and analyzed without a person_id, stored under the literal key `"_global"` (`affective_ai_node.py:517`) — voice emotion is scene-level, not linked to a specific speaker or person_track_id. See [MULTI_HUMAN_EMOTION_FAILURE_ANALYSIS.md](MULTI_HUMAN_EMOTION_FAILURE_ANALYSIS.md). |
| 16 | Text emotion/sentiment | Rule-based keyword classifier (`text_emotion_analyzer.py`), with emergency/distress/safety-concern/medical-concern keyword sets; optional transformer backend. Linked via `speaker_id` when available, else global. |
| 17 | Emotion fusion | `EmotionFusionEngine.fuse()` (`emotion_fusion_engine.py:89-369`) — weighted voting (face 0.4/voice 0.35/text 0.15/gesture 0.10) with an emergency override, called **once per tracked person** (`affective_ai_node.py:582-632`). |
| 18 | Per-person emotion state | **Confirmed correct for face+text+fusion output** — `HumanEmotionState.person_id` is populated per person, multiple people produce multiple messages. Voice input feeding that fusion is the one non-per-person signal (item 15). |
| 19 | Multi-human emotion support | Architecturally sound; **CONFIRMED GAP**: the fusion engine's output vocabulary is missing 2 of the 12 required states — `"angry"` always collapses into `"frustrated"` (`emotion_fusion_engine.py:27`) and `"uncertain"` is never emitted at all (absent from every mapping table in the file). |

**Tests:** `bonbon_affective_ai` 105/105 pass. Privacy gate present (`privacy/privacy_gate.py`), zeros out scores when suppressed; no raw face/audio file writes found.

## 20-25. Gesture recognition

| # | Item | Finding |
|---|---|---|
| 20 | Gesture recognition backend | MediaPipe (configurable to mock), `gesture.yaml`. Three classifiers: hand (`classifiers/hand_gesture_classifier.py`), body (`classifiers/body_gesture_classifier.py`), head (`classifiers/head_gesture_classifier.py`). |
| 21 | Supported gesture types | **12 of 16 required types actually produced**: `wave`, `raised_hand`, `stop_palm`, `pointing_left`, `pointing_right`, `pointing_forward`, `thumbs_up`, `thumbs_down`, `come_here`, `head_nod_yes`, `head_shake_no`, `fallen_posture` (≈`fallen_or_bent_posture`), plus `unknown_gesture`. **CONFIRMED MISSING**: `go_away` (referenced in `safety_classifier.py:27`/`intent_mapper.py:28`/`body_part_classifier.py:22` as a known category string, but **no classifier ever produces it** — plumbed for, not implemented), `pointing_at_object` (no object-detection fusion exists to distinguish this from directional pointing), `folded_hands`/`namaste` (absent everywhere). See [GESTURE_RECOGNITION_FAILURE_ANALYSIS.md](GESTURE_RECOGNITION_FAILURE_ANALYSIS.md). |
| 22 | Hand/body/head landmark handling | MediaPipe backend extracts 21-pt hand ×2, 33-pt body pose, 468-pt face mesh (subset used for head nod/shake via 6-point nose tracking). |
| 23 | Gesture-to-person assignment | **Confirmed correct** — `_assign_persons()` (`gesture_node.py:484-518`) maps MediaPipe tracking IDs to `bonbon_multi_person_tracker`'s `person_track_id`; `GestureEvent.person_track_id` populated per detected person; multiple people produce multiple independent events. |
| 24 | Gesture temporal smoothing | `GestureTemporalSmoother`: majority-vote over a sliding window, minimum 2 frames before firing (`temporal_smoother.py:87`) — prevents one-frame false positives. Safety gestures (`stop_palm`, `raised_hand`, `fallen_posture`) are exempt from the smoothing/cooldown delay and fire immediately (`temporal_smoother.py:94-104`). |
| 25 | Safety-relevant gesture flagging | `GestureSafetyClassifier` sets `GestureEvent.safety_relevant`/`safety_class`/`requires_immediate_response` (`safety_classifier.py:22-76`). **Confirmed: gestures never touch hardware directly** — the event is published for downstream consumption only. **CONFIRMED GAP**: `bonbon_behavior_engine` does consume it (`decide_safety_gesture_response()`), but `bonbon_safety`'s Safety Supervisor node has **no subscription to `/bonbon/gesture/events` or `/bonbon/human/state`** — safety-relevant gestures reach the Behavior Engine only, not the Safety Supervisor itself, for defense-in-depth. |

**Tests:** `bonbon_gesture` 94/94 pass.

## 26-30. Dashboard, metrics, tests, config

| # | Item | Finding |
|---|---|---|
| 26 | Dashboard endpoints | **None exist** for objects/people/affective/gestures/human-state. `bonbon_operator_api`'s `api/` directory has no perception-specific router. |
| 27 | Dashboard WebSockets | `VALID_CHANNELS` (`websocket/ws_manager.py`) has 10 channels, none perception-specific (`robot-status`, `safety-events`, `navigation-events`, `diagnostics`, `live-logs`, `boot-topology`, `ai-runtime`, `pi-efficiency`, `validation`, `deployment-readiness`). |
| 28 | Metrics publishing | The ROS2 bridge (`ros2/ros2_bridge.py`) subscribes to `PersonTrack` and `PerceptionEfficiencyMetrics` only — **not** to `HumanState`, `GestureEvent`, `FaceEmotion`, `VoiceEmotion`, or `HumanEmotionState`. Frontend has "Perception"/"Affective AI"/"Gesture"/"Behavior Engine" tabs (`App.tsx`) but they show a **browser-side COCO-SSD demo and testbench status cards**, not real backend perception data. |
| 29 | Tests | No `tests/perception/` or `tests/dashboard/` directory exists at the repo root yet (confirmed absent). Per-package tests are extensive and passing (see totals above); `bonbon_human_state_fusion` 73/73, `bonbon_behavior_engine` 164/164. |
| 30 | Raspberry Pi runtime configs | `config/pi_efficiency_profile.yaml` already has `object_detection`/`gesture_recognition`/`face_emotion`/`voice_emotion` FPS entries (ranks 7-9, 17 in the priority order) — but **no dedicated `config/pi_perception_profile.yaml`** exists (confirmed absent), and none of these entries are actually read by `bonbon_vision`, `bonbon_gesture`, or `bonbon_affective_ai` today (confirmed no imports of `pi_efficiency_profile` in those packages) — the FPS numbers exist in config but aren't enforced by the modules themselves. |

## Human State Fusion + Behavior Engine (context for the gap analysis above)

Both are **essentially complete**: `HumanState.msg` has all 18 required
fields; `human_state_fusion_node` wires all 8 required inputs and
publishes per-person; `bonbon_behavior_engine` subscribes to it and has
decision rules matching 7 of the brief's 7 example behaviors; it remains
the sole constructor of `BehaviorDecision`/`ActuationGesture` messages
(re-confirmed by grep, zero other constructors found). 73 and 164 tests
pass respectively. These are not rebuilt in this pass — see Phase 6 for
the one real integration gap (Safety Supervisor not subscribing to
gesture/human-state).

## Launch integration

All packages audited above (`bonbon_object_intelligence`,
`bonbon_multi_person_tracker`, `bonbon_affective_ai`, `bonbon_gesture`,
`bonbon_speaker_intelligence`, `bonbon_human_state_fusion`,
`bonbon_behavior_engine`) are included in `bringup.launch.py`'s AI group,
gated by `enable_ai` (default true). No launch-file work is needed.
