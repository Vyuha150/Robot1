# Perception AI Phase 3-10 Final Report

Continuation of the Perception AI upgrade started at
[PERCEPTION_AI_CURRENT_AUDIT.md](PERCEPTION_AI_CURRENT_AUDIT.md) (Phase 1)
and [PERCEPTION_AI_UPGRADE_REPORT.md](PERCEPTION_AI_UPGRADE_REPORT.md)
(Phase 2, object recognition). This pass covers Phases 3-10. Before writing
any code, each phase was checked against work already done in an earlier,
more targeted fix pass (tasks tracked as "Fix global voice emotion to
per-person" and "Add missing gesture types + enforce FPS/degraded-mode
policy") to avoid rebuilding what already existed — several phases turned
out to be substantially or fully complete already; this report states
plainly which those were.

## Phase 3: Multi-person tracking foundation — **no fix needed, re-verified**

The original audit (item 9-13) found `bonbon_multi_person_tracker` fully
implemented and tested with no confirmed bug, unlike the emotion/gesture
items that had explicit `CONFIRMED BUG`/`CONFIRMED GAP` tags. Re-ran the
suite this pass: **53/53 tests pass**, unchanged. No code touched.

## Phase 4: Multi-human emotion recognition — **remainder closed**

Voice-emotion-to-person attribution and the `angry` state were already
fixed in an earlier pass (see `MULTI_HUMAN_EMOTION_FAILURE_ANALYSIS.md`).
The one remaining item — `"uncertain"` was never emitted anywhere — is
fixed this pass:

- New `EmotionUncertaintyHandler`
  (`bonbon_affective_ai/fusion/uncertainty_handler.py`): flags a fused
  result as `"uncertain"` when two or more modalities carry comparably-
  weighted, competing votes (default: second-highest ≥75% of the top),
  rather than silently picking the marginally-higher one. A single
  unopposed modality — even at low confidence — is never "uncertain"; there
  is no second signal to conflict with.
- `"uncertain"` added to `HumanEmotionState.msg`'s documented state list and
  to all 4 `STATE_TO_*` lookup tables (response style, distance, TTS
  emotion, patience multiplier).
- New `uncertainty_conflict_margin` config knob (default 0.75, untuned —
  see `PERCEPTION_PHASE_3_10_DATA_MODEL_NOTES.md` item 3).
- **13 new tests** (`test_uncertainty_handler.py` + `test_fusion.py`
  additions); regression-confirmed the pre-existing angry-triple case is
  unaffected (single-state vote, never flagged as conflicting).

## Phase 5: Gesture recognition for multiple humans — **remainder closed**

`go_away` and `folded_hands`/`namaste` were already added in an earlier
pass, and gesture-level Pi-efficiency FPS enforcement already existed (see
`GESTURE_RECOGNITION_FAILURE_ANALYSIS.md`). The one remaining item —
`pointing_at_object`, previously deferred as needing cross-package fusion —
is implemented this pass:

- New `PointingObjectFusion`
  (`bonbon_gesture/logic/object_pointing_fusion.py`): pure geometry, no ROS
  dependency. The elbow→wrist pointing direction and
  `bonbon_vision.DetectedObject`'s bounding box are already expressed in
  the same 2D camera-pixel space — checks whether an object's bbox center
  falls within an angular tolerance cone (default 25°) ahead of the wrist.
  Never guesses: falls back to the existing `pointing_left/right/forward`
  classification when no object qualifies, the wrist isn't visible, or
  `/bonbon/vision/objects` hasn't published recently (1.0s staleness cap).
- `gesture_node.py` now subscribes to `/bonbon/vision/objects` and performs
  the fusion after temporal smoothing confirms a stable pointing gesture.
- `GestureEvent.msg` gained `pointed_object_id`/`pointed_object_class`
  fields; `gesture_type` comment updated to the full 16-type list
  (`folded_hands` was also missing from that comment despite already being
  implemented).
- `body_part_classifier.py` and `intent_mapper.py` updated for the new
  `pointing_at_object` type (`"indicate_object"` intent).
- **7 new tests** (`test_object_pointing_fusion.py`), all pure-geometry, no
  camera/MediaPipe dependency.

## Phase 6: Human state fusion + Behavior Engine integration — **remainder closed**

`HumanState`/`bonbon_behavior_engine` integration was already verified
complete in an earlier pass. The one remaining gap — safety-relevant
gestures and human-state urgency reached the Behavior Engine only, never
the Safety Supervisor, for defense-in-depth — is fixed this pass:

- `bonbon_safety`'s `SafetyStateMachine`/`ThreatAssessor` gained two new
  signals: `gesture_emergency_detected` (from `GestureEvent
  .requires_immediate_response`, computed upstream by
  `GestureSafetyClassifier` and reused, not re-derived) and
  `human_urgency_level` (from `HumanState.urgency_level`).
- `gesture_emergency_detected` escalates to **DANGER** (full stop), the
  same tier as bumper contact — `stop_palm`/`fallen_posture` are already
  flagged `requires_immediate_response` upstream specifically for this
  severity.
- `human_urgency_level ≥ human_urgency_caution` (default 0.8) escalates to
  **CAUTION** only, deliberately not DANGER — elevated urgency alone is a
  softer signal than a physical stop request and must not, by itself,
  trigger a full stop.
- `safety_supervisor_node.py` subscribes to `/bonbon/gesture/events` and
  `/bonbon/human/state`; a `requires_immediate_response` gesture triggers
  an immediate out-of-cycle safety evaluation, same as e-stop/bumper.
- **18 new tests** across `test_threat_assessor.py` and
  `test_safety_state_machine.py`, including a regression check that
  elevated urgency alone never escalates past CAUTION.

## Phase 7: Pi perception efficiency profile — **remainder closed (scoped)**

The original audit (item 30) named `bonbon_vision` and `bonbon_affective_ai`
specifically as declaring `pi_efficiency_profile.yaml` FPS limits that were
never read. `bonbon_gesture` was fixed in the earlier pass. This pass wires
the remaining two:

- `bonbon_vision/nodes/vision_node.py`: `fps_limits.object_detection`
  (8 FPS) now applies as an **additional ceiling** on top of the existing
  `detection_rate_hz` config and the live `PerceptionBudget`-driven dynamic
  throttle — never raises the configured rate, only caps it lower.
- `bonbon_affective_ai/nodes/affective_ai_node.py`:
  `fps_limits.face_emotion` (1 FPS) now raises
  `face_sample_interval_sec` when the configured value would sample faster
  than the shared profile allows. `voice_emotion`'s yaml value (0) is
  event-gated by the file's own design, not a numeric rate — correctly
  left unenforced, not a missed case.
- `bonbon_multi_person_tracker` and `bonbon_object_intelligence` were
  **not** touched — the original audit never named a gap for
  `person_tracking`'s FPS entry, and `bonbon_object_intelligence` is a
  post-processing consumer of vision's already-throttled output, not an
  independent producer with its own rate to cap. Scoped to the two real,
  audit-confirmed gaps only.
- Both changes verified with `py_compile`; `bonbon_vision`'s own test suite
  has a pre-existing, unrelated collection failure in this dev sandbox
  (`bonbon_msgs.msg` stub missing `PerceptionBudget`) — confirmed via
  `git stash` that this failure predates this session's changes, not
  introduced by them.

## Phase 8: Dashboard perception integration — **backend complete and tested; frontend explicitly deferred**

Confirmed via `DASHBOARD_PERCEPTION_GAP_REPORT.md`: every one of these
categories was previously invisible to an operator (only a browser-side
COCO-SSD demo unrelated to the robot). This pass:

- Extended `ros2_bridge.py` to subscribe to `DetectedObjectArray`,
  `GestureEvent`, `FaceEmotion`, `VoiceEmotion`, and `HumanState` (5 new
  subscriptions), and extended the existing `PersonTrack`/`HumanEmotionState`
  handlers to also populate the new per-category caches. Same honesty
  pattern used throughout this dashboard: `None`/absent until the first
  real message arrives, never a fabricated zero-state.
- **11 new REST endpoints** (`api/perception_api.py`):
  `/perception/objects/{status,classes,active}`,
  `/perception/people/{status,active}`,
  `/perception/affective/{status,human-states}`,
  `/perception/gestures/{status,active}`,
  `/perception/human-state/active`, `/perception/efficiency/status`.
- **6 new WebSocket channels** (`websocket/perception_snapshots.py`,
  merged into `status_broadcasters.CHANNEL_SNAPSHOTS`, registered in
  `ws_manager.VALID_CHANNELS` and `ws_router._CHANNEL_MIN_PERMISSION`):
  `perception-objects`, `perception-people`, `perception-gestures`,
  `perception-affective`, `perception-human-state`,
  `perception-efficiency`.
- Safety-relevant gestures and `requires_operator_alert` human-state events
  are also re-emitted on the existing `safety-events` channel for
  cross-cutting visibility.
- **17 new tests** (`test_perception_api.py`), covering both the honest
  "unavailable" path and the "available" path with realistically-shaped
  data. Fixed one pre-existing maintenance test
  (`test_all_channel_snapshots_registered`) that needed the 6 new channel
  names added to its expected set.
- **Frontend cards deliberately not built this pass** — replacing the
  placeholder COCO-SSD demo in `App.tsx` (~3,300 lines, single file) with 6
  real backend-sourced panels was explicitly deferred rather than risking
  a rushed edit to a large, unreviewed component. The backend is complete,
  tested, and ready for that follow-up; every endpoint above already
  returns real, honestly-gated data.

## Phase 9: Data/model improvement strategy — **addendum written**

[ONLINE_DATASET_STRATEGY.md](ONLINE_DATASET_STRATEGY.md) already covers
object detection, person detection, and pose/gesture recognition in full
and remains authoritative. New this pass:
[PERCEPTION_PHASE_3_10_DATA_MODEL_NOTES.md](PERCEPTION_PHASE_3_10_DATA_MODEL_NOTES.md)
records 5 specific data gaps this pass's own fixes surfaced (the
`pointing_at_object` angular tolerance, the `go_away` static-pose proxy,
the emotion-uncertainty conflict margin, the still-untrained hospital
object taxonomy, and the FPS caps' unmeasured accuracy impact) — each
requiring real-hardware/real-camera field data before being trusted in
production, none solvable by more code in this sandbox.

## Phase 10: Final tests + verification

Full regression across every package touched in Phases 3-8, run
individually (per-package `tests/conftest.py` module names collide across
packages when run together in one pytest invocation):

| Package | Result |
|---|---|
| `bonbon_gesture` | 123/123 passed |
| `bonbon_affective_ai` | 137/137 passed |
| `bonbon_multi_person_tracker` | 53/53 passed (unchanged, Phase 3) |
| `bonbon_safety` (core, non-ROS) | 237/237 passed |
| `bonbon_operator_api` | 285/285 passed (after fixing 1 stale channel-list assertion) |
| `bonbon_vision` | `py_compile` clean; test collection blocked by a pre-existing, unrelated sandbox gap (confirmed via `git stash`, not caused by this pass) |

**835 tests passed** across the packages with a working test harness in
this sandbox, zero failures, zero skips introduced by this pass's changes.

## What this pass did not do

- Frontend perception cards (Phase 8, explicitly deferred — see above).
- Any of the 5 real-hardware/real-camera data-collection items named in
  `PERCEPTION_PHASE_3_10_DATA_MODEL_NOTES.md` — this dev sandbox has no
  camera, no real Pi, and no field data to collect.
- `bonbon_multi_person_tracker`/`bonbon_object_intelligence` Pi-efficiency
  wiring (Phase 7) — deliberately out of scope, no audit-confirmed gap
  named either.
