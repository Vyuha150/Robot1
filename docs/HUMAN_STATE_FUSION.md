# Human State Fusion

Package: [`bonbon_human_state_fusion`](../ros2_ws/src/bonbon_human_state_fusion/README.md)

## Purpose

Fuses identity/lifecycle, emotion, gesture, and speech into one `HumanState`
per person for the Behavior Engine — replacing `HumanStateEstimate.msg`, a
message defined in this repo but never published or subscribed anywhere
(found during the original audit). Does not re-derive emotion, gesture, or
speech: `bonbon_affective_ai` already fuses face+voice+text+gesture into
`HumanEmotionState`; this package adds the layer none of the existing
packages had — identity-lifecycle awareness and a single output keyed to
`person_track_id`.

## Architecture

```
bonbon_multi_person_tracker ─PersonTrack──────────┐
bonbon_affective_ai ─HumanEmotionState/Face/Voice──┤
bonbon_gesture ─GestureEvent────────────────────────┼──► HumanStateFusionEngine ──► /bonbon/human/state
bonbon_speaker_intelligence ─SpeakerTurn───────────┤        (HumanState)
bonbon_perception_ai ─UserIntent───────────────────┤
bonbon_affective_ai ─TextEmotion───────────────────┘
```

### The hard part: bridging three ID spaces

| Source | ID space | Bridge |
|---|---|---|
| `GestureEvent` / `SpeakerTurn` | already `person_track_id` | direct join |
| `HumanEmotionState` / `FaceEmotion` / `VoiceEmotion` | `bonbon_vision`'s raw track_id | via `PersonTrack.raw_track_id` (added this round specifically for this bridge) |
| `UserIntent` / `TextEmotion` | the diarizer's per-utterance speaker_id | via "most recent active speaker" (text always follows speech) — never bridged across an implausible gap |

### Design principles (enforced by tests)

- **Never mix one person's evidence with another's** — a raw-ID bridge that's
  been reassigned (tracker churn) never leaks stale evidence to the old
  `person_track_id`.
- **`confidence` is explicitly NOT an average** — it scales down with
  missing modality coverage (`confidence_calculator.py`), so one confident
  reading never looks as solid as four agreeing ones.
- **Every state explains its evidence** — `evidence_summary` says which
  modalities contributed and why.
- **A `left_scene` person still gets one final `HumanState`** before
  eviction, mirroring `bonbon_multi_person_tracker`'s snapshot-then-evict
  pattern.

## ROS2 interface

| Topic/Service | Type | Direction |
|---|---|---|
| `/bonbon/persons/tracks` | `PersonTrack` | sub |
| `/bonbon/affective/human_state` | `HumanEmotionState` | sub |
| `/bonbon/affective/face_emotion`, `/bonbon/affective/voice_emotion` | `FaceEmotion`, `VoiceEmotion` | sub |
| `/bonbon/gesture/events` | `GestureEvent` | sub |
| `/bonbon/speaker/turns` | `SpeakerTurn` | sub |
| `/perception/intent` | `UserIntent` | sub |
| `/bonbon/affective/text_emotion` | `TextEmotion` | sub |
| `/bonbon/human/state` | `HumanState` | pub |

## Configuration

See [`config/human_state_fusion_params.yaml`](../ros2_ws/src/bonbon_human_state_fusion/bonbon_human_state_fusion/config/human_state_fusion_params.yaml).
Key knobs: `speaking_window_sec` (2.0), `recently_spoke_window_sec` (15.0),
`privacy_mode`.

## Example

Alice waves (gesture) while Bob, standing nearby, says "I'm angry about
this" (speech + emotion). Each `HumanState` reflects only its own person:
Alice's shows `current_gesture=wave`, empty `emotional_state`; Bob's shows
`emotional_state=angry`, `current_gesture=none` — verified directly by test
(`test_human_state_fusion_engine.py::TestNeverMixIdentities`).

## A real bug this round caught and fixed

`behavior_engine_node` subscribed `/bonbon/affective/state`, but
`affective_ai_node` publishes `/bonbon/affective/human_state` — a silent
topic-name mismatch meaning the Behavior Engine had never actually received
an emotion message from `bonbon_affective_ai` in any deployment. Fixed as
part of this round's integration work.

## Tests

64 tests across 5 core modules. Plus 3 of the 25 cross-package scenarios
(emotion differs per person, robot does not mix identities, new/existing
speaker transitions).

## Performance tuning

Target: **human state fusion ≤ 100 ms**. Measured p99 ≈ 0.6 ms for 5
simultaneous people — see [performance_tuning.md](performance_tuning.md).

## Troubleshooting

- **`HumanEmotionState` never bridges to a person** — confirm
  `bonbon_multi_person_tracker` is publishing `raw_track_id` (non-empty
  while the person is `present`, not `temporarily_lost`).
- **`text_intent`/`text_sentiment` always empty** — these only attach when
  someone spoke within `recently_spoke_window_sec`; check
  `bonbon_speaker_intelligence` is publishing turns for that person.
- **Confidence seems low even with good data** — by design, confidence
  reflects modality COVERAGE, not just data quality; a person with only
  lifecycle evidence will never report as confident as one with four
  agreeing modalities, even if that one modality is itself certain.
