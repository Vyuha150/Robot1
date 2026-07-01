# Multi-Human Emotion Failure Analysis

Root cause of "not recognizing emotions of multiple humans properly,"
traced to specific code. The headline concern in the brief — "emotion
recognition may be global instead of per-person" — is **true for exactly
one of the three input modalities**, not the whole pipeline.

## What is already correct (and should not be rebuilt)

- **Face emotion is per-person.** `FaceEmotionAnalyzer.analyze_face_crop(face_img, tracking_id, person_id)` (`face_emotion_analyzer.py:62-106`) receives a face crop already tagged with a specific person; results are stored `self._latest_face_msgs[person_id]` (`affective_ai_node.py:106-107`).
- **Fusion is per-person.** `_run_fusion()` iterates every tracked person and calls `_fuse_and_publish(person_id)` independently for each (`affective_ai_node.py:582-632`); two people in frame produce two separate `HumanEmotionState` messages, each with its own `person_id`.
- **Text emotion is linked when a speaker_id is available.** `analyze_text(text, person_id, tracking_id)` uses the speaker_id from `SpeechCommand` (`affective_ai_node.py:455`); it only falls back to global when the upstream speaker link itself is missing (a speaker-intelligence limitation, not an affective_ai one).

## Root cause: voice emotion is genuinely global

`affective_ai_node.py:113` buffers **all** incoming audio into one
shared buffer (`self._audio_buffer: List[float]`), regardless of who is
speaking. When the buffer crosses `voice_segment_min_sec` (0.5s), it is
analyzed and the result is stored under the literal key `"_global"`
(`affective_ai_node.py:517`) — not under any person's ID. This means:

- If two people are talking near the robot, voice emotion reflects
  whichever audio happened to be in the shared buffer, attributed to
  nobody in particular.
- The per-person fusion engine at `_fuse_and_publish(person_id)` looks up
  `self._latest_voice_msgs.get(person_id)` — which will **never find a
  match** under any real person_id, because voice results are only ever
  stored under `"_global"`. In practice, voice's 0.35 fusion weight is
  silently contributing nothing to any specific person's fused state
  today (it's a dead lookup), even though the analyzer itself runs and
  produces a result.

This is the same-shaped bug regardless of how many people are present —
it's not specifically a "many people" issue, it's that voice was never
wired to the same person-keyed dictionary pattern face emotion already
uses.

## Secondary gap: the emotion vocabulary is missing 2 of 12 required states

`EmotionFusionEngine`'s `EMOTION_TO_STATE` mapping
(`emotion_fusion_engine.py:15-29`) collapses raw `"angry"`/`"anger"` into
the state `"frustrated"` — `"angry"` is never emitted as its own distinct
state, contradicting the brief's explicit 12-state list (which treats
`frustrated` and `angry` as different severities). More significantly,
**`"uncertain"` is never emitted anywhere in the file** — when face,
voice, and text signals conflict or are all low-confidence, the fusion
engine still commits to one of the 10 states it does produce rather than
reporting genuine uncertainty. This contradicts the brief's explicit
requirement ("conflicting signals produce uncertain state") and the
already-planned-for `EmotionUncertaintyHandler` class, which does not
exist yet.

## What this looks like from the outside

- Two people, one calm one angry: face emotion correctly differs between
  them (if both faces are visible and sampled); if the angry person is
  the one currently in the shared audio buffer, the OTHER (calm) person's
  fused state may still get pulled toward "frustrated" by mistake if
  voice's weight (0.35) happens to combine with any face noise — because
  voice is not scoped to the right person. In the more common case, voice
  simply contributes nothing to anyone (the dead-lookup case above), so
  the reported states are less informed than they should be, not
  necessarily obviously wrong — which is a subtler, harder-to-notice bug
  than a single global scene emotion label would be, consistent with a
  hard-to-diagnose field complaint.
- A person who is *genuinely* hard to read (mixed signals) is reported
  with unwarranted confidence in one of the 10 available states, instead
  of "uncertain" — overclaiming certainty the fusion never actually had.

## Fix scope (Phase 4)

1. Link voice analysis to `person_track_id` via the speaker turn's
   audio-visual association (already computed in
   `bonbon_speaker_intelligence`, see `SpeakerTurn.person_track_id`) —
   store per-person, not under `"_global"`.
2. Handle the off-camera/unknown-speaker case explicitly (voice signal
   exists, no person to attach it to) rather than dumping it into a
   pseudo-person key that silently poisons lookups.
3. Add `"angry"` as its own state (distinct severity from `"frustrated"`)
   and implement `EmotionUncertaintyHandler` to emit `"uncertain"` when
   confidence is low or signals conflict, per the existing temporal-
   smoothing/stability infrastructure already in place.

None of this requires changing `FaceEmotionAnalyzer`,
`TemporalEmotionSmoother`, or the existing 105 tests for parts that are
already correct — it's a targeted fix to the voice-emotion storage key
and the fusion vocabulary.
