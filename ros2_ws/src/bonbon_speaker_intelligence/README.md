# bonbon_speaker_intelligence

Persistent speaker identity, transcript-to-speaker mapping, and audio-visual
speaker association for the BonBon service robot. Does not run VAD, STT, or
diarization — it consumes `bonbon_speech`'s existing output and adds what
that pipeline collapses away before publishing.

## Why this package exists

`bonbon_speech`'s diarizer already computes per-segment speaker detail every
utterance (`DiarizationResult.segments`), but `speech_node` discarded it,
publishing only a collapsed `dominant_speaker` + `all_speaker_ids`. Diarizer
labels (`SPEAKER_00`/`01`) also reset every utterance call — there is no
acoustic-embedding model anywhere in this repo that could recognise "this is
the same voice as before" across separate calls.

This package:
1. Required a small, surgical extension to `bonbon_speech` (not a new audio
   pipeline) to expose the per-segment detail it already computed —
   see `SpeechTranscription.msg`'s `segment_*` fields.
2. Adds the one missing layer: persistent identity, transcript-to-speaker
   attribution, and linking a speaker turn to a visible person.

## Architecture

```
bonbon_speech/speech_node
    │ /speech/transcription (SpeechTranscription: text, words+timing,
    │                         segment_speaker_ids/start/end/confidence)
    ▼
bonbon_speaker_intelligence/speaker_intelligence_node
    │ /bonbon/speaker/turns (SpeakerTurn)
    ▼
bonbon_human_state_fusion (consumer)
```

### Core modules (`bonbon_speaker_intelligence/core/`, no rclpy)

| Module | Responsibility | Honest limitation |
|---|---|---|
| `speaker_identity_manager.py` | Persistent `speaker_id` via DOA + recency matching | **Not a voiceprint.** Two different people speaking from the same direction in quick succession will be merged; the same person moving will be treated as new. |
| `transcript_segment_mapper.py` | Attributes transcript text to diarization segments using per-word timestamps | When word timestamps aren't available AND there are multiple segments, text is left unattributed rather than guessed (no per-word data = no way to know whose words are whose). |
| `audio_visual_associator.py` | Links a speaker turn's DOA to a `bonbon_multi_person_tracker` `person_track_id` | A single DOA describes the WHOLE utterance, not each diarization segment — confidence is halved for overlapping-speech turns. |
| `voice_emotion_cache.py` | Attaches the latest `bonbon_affective_ai` `VoiceEmotion` reading if fresh | `bonbon_affective_ai`'s voice analyzer is not itself speaker-attributed (`person_id=""` always, by its own design) — this is "most recent reading if plausible," not verified per-speaker emotion. |
| `speaker_turn_builder.py` | Orchestrates the above into `SpeakerTurnResult` per segment | — |

## ROS2 interface

**Subscribes**
| Topic | Type |
|---|---|
| `/speech/transcription` | `SpeechTranscription` (existing, extended — see Phase 3 commit) |
| `/bonbon/affective/voice_emotion` | `VoiceEmotion` (existing) |
| `/bonbon/persons/tracks` | `PersonTrack` (from `bonbon_multi_person_tracker`) |
| `/bonbon/safety/state` | `SafetyState` |

**Publishes**
| Topic | Type |
|---|---|
| `/bonbon/speaker/turns` | `SpeakerTurn` |
| `/bonbon/speaker/speaker_intelligence_node/health` | `ModuleHealth` |

**Services:** `~/health_check` (`bonbon_srvs/HealthCheck`)

## Configuration

See [`config/speaker_intelligence_params.yaml`](bonbon_speaker_intelligence/config/speaker_intelligence_params.yaml).
`privacy_mode: true` suppresses `person_track_id` in all published turns.

## Failure handling

| Failure | Behavior |
|---|---|
| Diarizer disabled/timed out (no `segment_*` fields) | Falls back to one synthetic segment spanning the whole utterance, attributed to `speaker_id`/whole text — still produces a turn for the primary speaker. |
| No visible `PersonTrack`s | `person_track_id=""`, `is_off_camera=true` — never guessed. |
| Overlapping speakers, no word timestamps | Transcript left empty for all segments in that utterance (honest gap, not misattribution). |
| `VoiceEmotion` stale (> `voice_emotion_max_age_sec`) | `voice_emotion=""`, never a stale guess. |

## Tests

```
tests/test_speaker_identity_manager.py     8 tests
tests/test_transcript_segment_mapper.py    7 tests
tests/test_audio_visual_associator.py      7 tests
tests/test_voice_emotion_cache.py          4 tests
tests/test_speaker_turn_builder.py        12 tests
```
Run: `python -m pytest tests/ -q` (no rclpy required).

## Performance target

Speaker turn update **< 1 sec** after the speech segment completes (project
performance brief). The core pipeline here is pure dict/list lookups and
arithmetic, far under budget; the dominant latency is upstream STT/diarization
in `bonbon_speech`, which this package does not add to.
