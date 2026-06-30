# bonbon_human_state_fusion

Fuses identity/lifecycle, emotion, gesture, and speech into one `HumanState`
per person for the Behavior Engine. Does not re-derive emotion, gesture, or
speech — consumes the existing outputs of `bonbon_multi_person_tracker`,
`bonbon_affective_ai`, `bonbon_gesture`, and `bonbon_speaker_intelligence`,
and replaces the dead `HumanStateEstimate.msg` stub (defined in this repo,
never published or subscribed anywhere).

## Why this package exists, and what it does NOT do

`bonbon_affective_ai` already fuses face+voice+text+gesture into
`HumanEmotionState` — this package does not redo that fusion. It adds the one
layer none of the existing packages have: identity-lifecycle awareness,
speaker-turn awareness, and a single per-person output keyed to
`person_track_id` (the lifecycle-aware identity from `bonbon_multi_person_tracker`,
not any package's raw per-frame ID).

## The hard part: bridging three different ID spaces

| Source | ID space | Bridge used |
|---|---|---|
| `GestureEvent` (bonbon_gesture) | already `person_track_id` | direct join |
| `SpeakerTurn` (bonbon_speaker_intelligence) | already `person_track_id` | direct join |
| `HumanEmotionState` / `FaceEmotion` / `VoiceEmotion` (bonbon_affective_ai) | bonbon_vision's raw per-frame `track_id` ("person_3") | via `PersonTrack.raw_track_id`, refreshed every cycle, empty while `temporarily_lost` |
| `UserIntent` / `TextEmotion` | the diarizer's per-utterance `speaker_id` | via "most recent active speaker" — text always follows speech; never bridged across an implausible time gap |

`PersonTrack.raw_track_id` was added specifically to support the second
bridge (see the message-contracts commit) — `bonbon_affective_ai` predates
`bonbon_multi_person_tracker` and was never updated to key off the newer
identity space.

## Core modules (`bonbon_human_state_fusion/core/`, no rclpy)

| Module | Responsibility |
|---|---|
| `human_state_fusion_engine.py` | The orchestrator — `update_*` ingest methods + `build_human_state`/`build_all`. |
| `active_speaker_tracker.py` | Per-person speaking recency + the speaker-id bridge for text intent/sentiment. |
| `confidence_calculator.py` | `HumanState.confidence` — explicitly **not an average**; scales down with missing modalities so 1 confident reading never looks as solid as 4 agreeing ones. |
| `urgency_engagement_estimator.py` | `engagement_level`/`urgency_level` from real signals only (lifecycle state, gesture safety-relevance, emotion classification) — no invented gaze tracking or stress sensors. |
| `evidence_summary.py` | Human-readable explainability string — which modalities contributed and why. |
| `focus_publish_gate.py` | The real consumer of `bonbon_perception_efficiency`'s `ActivePersonFocusManager` weight — background people publish at a reduced cadence; the focus person, new arrivals, and `left_scene` departures are never throttled. Reuses `select_focus_person` (`bonbon_behavior_engine`) and `ActivePersonFocusManager` directly. |

## Rules enforced (with tests)

- **Never mix one person's evidence with another's.** A raw-ID bridge that's
  been reassigned (tracker churn) never leaks stale evidence to the old
  `person_track_id`. Text intent is only attributed to the genuinely most
  recent speaker, never to a silent bystander.
- **New person tracked separately from existing person** — every
  `person_track_id` has its own independent fusion record.
- **Updates on departure** — a `left_scene` `PersonTrack` still produces one
  final `HumanState` before the record is evicted (mirrors
  `bonbon_multi_person_tracker`'s snapshot-then-evict pattern).
- **Preserves uncertainty** — `confidence` reflects modality coverage, not
  just the available readings' average.
- **Explains evidence** — every `HumanState.evidence_summary` says which
  modalities contributed.

## ROS2 interface

**Subscribes:** `/bonbon/persons/tracks`, `/bonbon/affective/human_state`,
`/bonbon/affective/face_emotion`, `/bonbon/affective/voice_emotion`,
`/bonbon/gesture/events`, `/bonbon/speaker/turns`, `/perception/intent`,
`/bonbon/affective/text_emotion`, `/bonbon/safety/state`.

**Publishes:** `/bonbon/human/state` (`HumanState`), health.

**Services:** `~/health_check`.

## Tests

```
tests/test_active_speaker_tracker.py          12 tests
tests/test_urgency_engagement_estimator.py    13 tests
tests/test_evidence_summary.py                10 tests
tests/test_confidence_calculator.py            6 tests
tests/test_human_state_fusion_engine.py       23 tests
tests/test_focus_publish_gate.py               9 tests
```
Run: `python -m pytest tests/ -q` (no rclpy required).

## Performance target

Human state fusion **< 100 ms** per cycle. The core engine is dict lookups
and arithmetic over a bounded number of tracked people (`bonbon_multi_person_tracker`
caps this at `max_persons`, default 20) — well under budget.
